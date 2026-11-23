"""Deterministic mapping and harmonization workflow tests."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.database.session import SessionLocal
from app.main import app
from app.models.entities import (
    AuditLog, DataSource, DuplicateRecord, HarmonizedLandRecord, ProcessingJob,
    RawLandRecord, RecordProvenance, SchemaMapping, User, ValidationResult,
    Workspace, WorkspaceMembership,
)
from app.services.harmonization import _area, _geometry, _record_date, map_columns
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

        with SessionLocal() as db:
            records = db.scalars(select(HarmonizedLandRecord).where(HarmonizedLandRecord.job_id == job_id)).all()
            assert len(records) == 11
            assert db.scalar(select(RecordProvenance.id).join(HarmonizedLandRecord).where(HarmonizedLandRecord.job_id == job_id))
            assert db.scalar(select(SchemaMapping.id).where(SchemaMapping.job_id == job_id))
            assert db.scalar(select(DuplicateRecord.id).where(DuplicateRecord.job_id == job_id))
            assert db.scalar(select(ValidationResult.id).where(ValidationResult.job_id == job_id))
            hectares_record = next(record for record in records if record.plot_id == "K-102" and record.source_crs and "32643" in record.source_crs)
            assert hectares_record.area_acres == Decimal("1.260237")
            assert hectares_record.geometry is not None

        repeated = client.post(f"/api/v1/harmonization/jobs/{job_id}/run", headers=headers)
        assert repeated.status_code == 409
    finally:
        if user_id is not None and workspace_id is not None:
            with SessionLocal.begin() as db:
                db.execute(delete(AuditLog).where(AuditLog.workspace_id == workspace_id))
                db.execute(delete(ProcessingJob).where(ProcessingJob.workspace_id == workspace_id))
                db.execute(delete(DataSource).where(DataSource.workspace_id == workspace_id))
                db.execute(delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id))
                db.execute(delete(Workspace).where(Workspace.id == workspace_id))
                db.execute(delete(User).where(User.id == user_id))
            from app.services.ingestion import _storage_root
            import shutil
            shutil.rmtree(_storage_root() / str(workspace_id), ignore_errors=True)
