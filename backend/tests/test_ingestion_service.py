"""Parser and upload integration tests using synthetic land-record data."""

import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon
from sqlalchemy import delete, select

from app.database.session import SessionLocal
from app.main import app
from app.models.entities import (
    AuditLog,
    DataSource,
    ProcessingJob,
    RawLandRecord,
    UploadedFile,
    User,
    Workspace,
    WorkspaceMembership,
)
from app.services.ingestion import (
    InvalidDataset,
    UnsupportedFileType,
    _storage_root,
    parse_dataset,
)

client = TestClient(app)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_parser_reads_csv_excel_json_and_geojson_fixtures() -> None:
    sample_dir = PROJECT_ROOT / "data" / "sample"
    cases = [
        ("source_a.csv", "csv"),
        ("source_b.xlsx", "excel"),
        ("source_c.geojson", "geojson"),
    ]
    for filename, expected_format in cases:
        parsed = parse_dataset(filename, (sample_dir / filename).read_bytes())
        assert parsed.metadata["detected_format"] == expected_format
        assert parsed.rows
        assert parsed.columns

    json_content = json.dumps([{"plot_id": "JSON-1", "area_acres": 1.75}]).encode()
    parsed_json = parse_dataset("records.json", json_content)
    assert parsed_json.rows == [{"plot_id": "JSON-1", "area_acres": 1.75}]


def test_parser_reads_a_zipped_shapefile_with_gdal_backed_pyogrio() -> None:
    with tempfile.TemporaryDirectory(prefix="land-fixture-") as temporary_dir:
        temporary = Path(temporary_dir)
        shapefile_path = temporary / "parcels.shp"
        frame = gpd.GeoDataFrame(
            {"plot_id": ["SHP-1"], "owner": ["Synthetic Owner"]},
            geometry=[Polygon([(77, 28), (77.01, 28), (77.01, 28.01), (77, 28.01), (77, 28)])],
            crs="EPSG:4326",
        )
        frame.to_file(shapefile_path, driver="ESRI Shapefile", engine="pyogrio")
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in temporary.iterdir():
                archive.write(path, arcname=path.name)

        parsed = parse_dataset("parcels.zip", archive_buffer.getvalue())
        assert parsed.rows[0]["plot_id"] == "SHP-1"
        assert parsed.metadata["source_crs"] == "EPSG:4326"
        assert parsed.rows[0]["geometry"]["type"] == "Polygon"


def test_parser_rejects_unsafe_zip_paths_and_unknown_types() -> None:
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("../parcels.shp", b"not a shapefile")
    with pytest.raises(InvalidDataset, match="unsafe path"):
        parse_dataset("bad.zip", archive_buffer.getvalue())

    with pytest.raises(UnsupportedFileType):
        parse_dataset("records.exe", b"not data")


def test_authenticated_batch_upload_preserves_files_and_raw_lineage() -> None:
    email = f"phase5-{uuid4().hex}@example.com"
    password = "correct-horse-battery-staple"
    user_id: UUID | None = None
    workspace_id: UUID | None = None
    csv_bytes = b"Khasra_No,Owner_Name,Area_Acres\nK-501,Asha Example,2.75\n"
    geojson_bytes = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"Plot_Number": "G-701", "Landholder": "Ravi Example"},
                    "geometry": {
                        "type": "Point",
                        "coordinates": [77.209, 28.614],
                    },
                }
            ],
        }
    ).encode()
    source_name = f"Synthetic source {uuid4().hex[:8]}"

    try:
        registration = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password},
        )
        assert registration.status_code == 201, registration.text
        user_id = UUID(registration.json()["user"]["id"])
        token = registration.json()["access_token"]
        with SessionLocal() as db:
            workspace_id = db.scalar(
                select(WorkspaceMembership.workspace_id).where(
                    WorkspaceMembership.user_id == user_id
                )
            )
        assert workspace_id is not None

        upload = client.post(
            "/api/v1/ingestion/uploads",
            headers={"Authorization": f"Bearer {token}"},
            data={"source_name": source_name, "jurisdiction": "Synthetic District"},
            files=[
                ("files", ("parcels.csv", csv_bytes, "text/csv")),
                ("files", ("boundaries.geojson", geojson_bytes, "application/geo+json")),
            ],
        )
        assert upload.status_code == 201, upload.text
        result = upload.json()
        assert result["total_records"] == 2
        assert result["status"] == "mapping"
        assert {item["filename"] for item in result["files"]} == {
            "parcels.csv",
            "boundaries.geojson",
        }
        job_id = UUID(result["job_id"])

        with SessionLocal() as db:
            files = db.scalars(
                select(UploadedFile).where(UploadedFile.job_id == job_id)
            ).all()
            raw_rows = db.scalars(
                select(RawLandRecord).where(RawLandRecord.job_id == job_id)
            ).all()
            assert len(raw_rows) == 2
            assert all(row.original_data for row in raw_rows)
            for item in files:
                stored = _storage_root().joinpath(*PurePosixPath(item.object_key).parts)
                original = csv_bytes if item.original_filename == "parcels.csv" else geojson_bytes
                assert stored.read_bytes() == original

        job_response = client.get(
            f"/api/v1/ingestion/jobs/{job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert job_response.status_code == 200
        assert job_response.json()["summary"]["total_records"] == 2

        duplicate = client.post(
            "/api/v1/ingestion/uploads",
            headers={"Authorization": f"Bearer {token}"},
            data={"source_name": source_name},
            files=[("files", ("copy.csv", csv_bytes, "text/csv"))],
        )
        assert duplicate.status_code == 409
    finally:
        if user_id is not None and workspace_id is not None:
            with SessionLocal.begin() as db:
                db.execute(delete(AuditLog).where(AuditLog.workspace_id == workspace_id))
                db.execute(delete(ProcessingJob).where(ProcessingJob.workspace_id == workspace_id))
                db.execute(delete(DataSource).where(DataSource.workspace_id == workspace_id))
                db.execute(delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id))
                db.execute(delete(Workspace).where(Workspace.id == workspace_id))
                db.execute(delete(User).where(User.id == user_id))
            shutil.rmtree(_storage_root() / str(workspace_id), ignore_errors=True)
