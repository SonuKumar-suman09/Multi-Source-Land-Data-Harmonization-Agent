"""Deterministic mapping and harmonization workflow tests."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text

from app.database.session import SessionLocal
from app.main import app
from app.models.entities import (
    AgentExecution, AuditLog, DataSource, DuplicateRecord, HarmonizedLandRecord, ProcessingJob,
    RawLandRecord, RecordProvenance, SchemaMapping, User, ValidationResult,
    Workspace, WorkspaceMembership,
)
from app.services.harmonization import _area, _geometry, _record_date, map_columns
from app.services.quality_assurance import _schema_findings
from fastapi.testclient import TestClient

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[2]


def test_deterministic_schema_area_date_and_geometry_conversions() -> None:
    mapped, ambiguous = map_columns(["Khasra_No", "Plot_Number", "Size_Hectares", "Surveyed_On"])
    assert mapped == {"Size_Hectares": "area_acres", "Surveyed_On": "recorded_at"}
    assert ambiguous == {"Khasra_No": "plot_id", "Plot_Number": "plot_id"}
    acres, issue = _area("0.51", "Size_Hectares", None)
    assert acres == Decimal("1.260237")
    assert issue is None
    assert _record_date("2024-01-15") == (date(2024, 1, 15), None)
    assert _record_date("04/05/2024")[0] is None

    fields, _ = map_columns(["Easting_m", "Northing_m"])
    geometry, normalized_crs, error = _geometry(
        {"Easting_m": 716300, "Northing_m": 3168000}, fields, "EPSG:32643"
    )
    assert geometry is not None and error is None
    assert normalized_crs == "EPSG:32643"
    assert 76 < geometry.x < 78 and 28 < geometry.y < 29


def test_unknown_area_unit_and_invalid_coordinate_are_not_silently_fixed() -> None:
    assert _area(2, "Size", None)[0] is None
    mapped, _ = map_columns(["Latitude", "Longitude"])
    geometry, _, error = _geometry({"Latitude": 91, "Longitude": 77}, mapped, None)
    assert geometry is None
    assert "bounds" in error


def test_pandera_reports_invalid_canonical_fields_by_record() -> None:
    record_id = uuid4()
    record = HarmonizedLandRecord(
        id=record_id, plot_id="", owner_name="", area_acres=Decimal("-2"), quality_score=120
    )
    findings = _schema_findings([record])
    assert findings
    assert all(item.record_id == record_id for item in findings)
    assert {item.code for item in findings} >= {"qa_schema_plot_id", "qa_schema_area_acres", "qa_schema_quality_score"}


def test_harmonization_endpoint_processes_fixture_batch_with_lineage() -> None:
    email = f"phase6-{uuid4().hex}@example.com"
    password = "correct-horse-battery-staple"
    user_id: UUID | None = None
    workspace_id: UUID | None = None
    source_name = f"Synthetic harmonization {uuid4().hex[:8]}"
    headers: dict[str, str] = {}
    job_id: UUID | None = None
    try:
        registration = client.post("/api/v1/auth/register", json={"email": email, "password": password})
        assert registration.status_code == 201, registration.text
        user_id = UUID(registration.json()["user"]["id"])
        headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}
        with SessionLocal() as db:
            workspace_id = db.scalar(select(WorkspaceMembership.workspace_id).where(WorkspaceMembership.user_id == user_id))
        fixture_names = ["source_a.csv", "source_b.xlsx", "source_c.geojson"]
        upload = client.post(
            "/api/v1/ingestion/uploads", headers=headers, data={"source_name": source_name},
            files=[("files", (name, (ROOT / "data" / "sample" / name).read_bytes(), "application/octet-stream")) for name in fixture_names],
        )
        assert upload.status_code == 201, upload.text
        job_id = UUID(upload.json()["job_id"])
        response = client.post(f"/api/v1/harmonization/jobs/{job_id}/run", headers=headers)
        assert response.status_code == 200, response.text
        summary = response.json()
        assert summary["harmonized_records"] == 11
        assert summary["duplicate_pairs"] >= 2
        assert summary["validation_findings"] > 0

        quality = client.post(f"/api/v1/quality/jobs/{job_id}/run", headers=headers)
        assert quality.status_code == 200, quality.text
        quality_report = quality.json()
        assert quality_report["records_checked"] == 11
        assert quality_report["critical_errors"] > 0
        assert quality_report["warnings"] > 0
        assert 0 <= quality_report["quality_score"] <= 100
        repeated_quality = client.post(f"/api/v1/quality/jobs/{job_id}/run", headers=headers)
        assert repeated_quality.status_code == 200
        assert repeated_quality.json()["already_completed"] is True

        workflow = client.post(f"/api/v1/workflows/jobs/{job_id}/run", headers=headers)
        assert workflow.status_code == 200, workflow.text
        workflow_result = workflow.json()
        assert workflow_result["stage"] == "completed"
        assert [event["node"] for event in workflow_result["events"]] == [
            "orchestrator", "ingestion", "harmonization", "quality_assurance", "orchestrator"
        ]
        workflow_status = client.get(f"/api/v1/workflows/jobs/{job_id}", headers=headers)
        assert workflow_status.status_code == 200
        assert workflow_status.json()["stage"] == "completed"
        rerun_workflow = client.post(f"/api/v1/workflows/jobs/{job_id}/run", headers=headers)
        assert rerun_workflow.status_code == 200
        assert rerun_workflow.json()["already_completed"] is True

        with SessionLocal() as db:
            records = db.scalars(select(HarmonizedLandRecord).where(HarmonizedLandRecord.job_id == job_id)).all()
            assert len(records) == 11
            assert db.scalar(select(RecordProvenance.id).join(HarmonizedLandRecord).where(HarmonizedLandRecord.job_id == job_id))
            assert db.scalar(select(SchemaMapping.id).where(SchemaMapping.job_id == job_id))
            assert db.scalar(select(DuplicateRecord.id).where(DuplicateRecord.job_id == job_id))
            assert db.scalar(select(ValidationResult.id).where(ValidationResult.job_id == job_id))
            execution = db.scalar(select(AgentExecution).where(AgentExecution.job_id == job_id, AgentExecution.agent_name == "workflow_orchestrator"))
            assert execution is not None and execution.status == "completed"
            checkpoint_count = db.scalar(
                text("SELECT count(*) FROM checkpoints WHERE thread_id = :thread_id"),
                {"thread_id": f"land-harmonization:{job_id}"},
            )
            assert checkpoint_count and checkpoint_count > 0
            hectares_record = next(record for record in records if record.plot_id == "K-102" and record.source_crs and "32643" in record.source_crs)
            assert hectares_record.area_acres == Decimal("1.260237")
            assert hectares_record.geometry is not None

        repeated = client.post(f"/api/v1/harmonization/jobs/{job_id}/run", headers=headers)
        assert repeated.status_code == 409
    finally:
        if user_id is not None and workspace_id is not None:
            with SessionLocal.begin() as db:
                if job_id is not None and db.scalar(text("SELECT to_regclass('public.checkpoints')")):
                    thread_id = f"land-harmonization:{job_id}"
                    for table_name in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                        db.execute(text(f"DELETE FROM {table_name} WHERE thread_id = :thread_id"), {"thread_id": thread_id})
                db.execute(delete(AuditLog).where(AuditLog.workspace_id == workspace_id))
                db.execute(delete(ProcessingJob).where(ProcessingJob.workspace_id == workspace_id))
                db.execute(delete(DataSource).where(DataSource.workspace_id == workspace_id))
                db.execute(delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id))
                db.execute(delete(Workspace).where(Workspace.id == workspace_id))
                db.execute(delete(User).where(User.id == user_id))
            from app.services.ingestion import _storage_root
            import shutil
            shutil.rmtree(_storage_root() / str(workspace_id), ignore_errors=True)
