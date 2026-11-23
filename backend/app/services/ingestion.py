"""Safe file inspection, immutable local storage, and raw-row persistence."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import mapping
from pyproj import CRS
from pyproj.exceptions import CRSError
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import (
    AuditLog,
    DataSource,
    JobStatus,
    ProcessingJob,
    RawLandRecord,
    UploadedFile,
)
from app.services.object_storage import delete_original, local_storage_root, store_original

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xlsm", ".json", ".geojson", ".zip"}
MAX_ROWS_PER_FILE = 250_000


class IngestionError(ValueError):
    """An upload cannot be safely or correctly ingested."""


class UnsupportedFileType(IngestionError):
    """The file type is not in the supported input set."""


class InvalidDataset(IngestionError):
    """The file is malformed or is not the dataset its extension claims."""


class DuplicateUpload(IngestionError):
    """The same file content has already been uploaded to this workspace."""


class UploadTooLarge(IngestionError):
    """An upload exceeds the configured size limit."""


@dataclass(frozen=True)
class UploadPayload:
    filename: str
    media_type: str | None
    content: bytes


@dataclass(frozen=True)
class ParsedDataset:
    rows: list[dict[str, Any]]
    columns: list[str]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class IngestedFile:
    id: UUID
    filename: str
    detected_format: str
    sha256: str
    size_bytes: int
    row_count: int
    columns: list[str]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class IngestionResult:
    job_id: UUID
    workspace_id: UUID
    source_id: UUID
    status: str
    total_records: int
    files: list[IngestedFile]


def _safe_filename(filename: str) -> str:
    leaf = PurePosixPath(filename.replace("\\", "/")).name
    leaf = re.sub(r"[\x00-\x1f\x7f]", "", leaf).strip()
    if not leaf or leaf in {".", ".."}:
        raise InvalidDataset("A valid filename is required")
    return leaf[:240]


def detect_format(filename: str) -> str:
    suffix = Path(_safe_filename(filename)).suffix.lower()
    formats = {
        ".csv": "csv",
        ".xlsx": "excel",
        ".xlsm": "excel",
        ".json": "json",
        ".geojson": "geojson",
        ".zip": "shapefile_zip",
    }
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileType(
            f"Unsupported extension '{suffix or '(none)'}'. Use CSV, XLSX/XLSM, JSON, GeoJSON, or a zipped Shapefile."
        )
    return formats[suffix]


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if hasattr(value, "__geo_interface__"):
        return _json_value(mapping(value))
    if pd.isna(value):
        return None
    return value if isinstance(value, (str, int, bool)) else str(value)


def _frame_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if len(frame) > MAX_ROWS_PER_FILE:
        raise UploadTooLarge(f"Datasets may contain at most {MAX_ROWS_PER_FILE:,} rows per file")
    return [
        {str(column): _json_value(value) for column, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def _json_records(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    metadata: dict[str, Any] = {}
    if isinstance(payload, dict) and payload.get("type") in {"FeatureCollection", "Feature"}:
        features = payload.get("features", [payload])
        if not isinstance(features, list):
            raise InvalidDataset("GeoJSON FeatureCollection must contain a feature list")
        rows: list[dict[str, Any]] = []
        for feature in features:
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                raise InvalidDataset("Every GeoJSON feature must have type 'Feature'")
            properties = feature.get("properties") or {}
            if not isinstance(properties, dict):
                raise InvalidDataset("GeoJSON feature properties must be an object or null")
            row = {str(key): _json_value(value) for key, value in properties.items()}
            row["geometry"] = _json_value(feature.get("geometry"))
            rows.append(row)
        declared_crs = payload.get("crs")
        crs_name = (((declared_crs or {}).get("properties") or {}).get("name") if isinstance(declared_crs, dict) else None)
        try:
            metadata["source_crs"] = CRS.from_user_input(crs_name).to_string() if crs_name else "EPSG:4326"
        except CRSError as exc:
            raise InvalidDataset(f"GeoJSON declares an invalid CRS: {crs_name}") from exc
        metadata["geometry_types"] = sorted(
            {
                geometry.get("type")
                for geometry in (row.get("geometry") for row in rows)
                if isinstance(geometry, dict) and geometry.get("type")
            }
        )
        return rows, metadata

    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        record_candidate = payload.get("records", payload.get("data"))
        records = record_candidate if isinstance(record_candidate, list) else [payload]
    else:
        raise InvalidDataset("JSON must contain an array of records, an object, or a GeoJSON feature collection")

    if not all(isinstance(record, dict) for record in records):
        raise InvalidDataset("JSON record arrays must contain objects")
    return [
        {str(key): _json_value(value) for key, value in record.items()}
        for record in records
    ], metadata


def _parse_shapefile_zip(content: bytes) -> ParsedDataset:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, OSError) as exc:
        raise InvalidDataset("ZIP upload is not a valid Shapefile archive") from exc

    with archive:
        infos = archive.infolist()
        max_uncompressed_bytes = settings.max_upload_mb * 1024 * 1024 * 5
        if sum(info.file_size for info in infos) > max_uncompressed_bytes:
            raise UploadTooLarge("Shapefile archive expands beyond the allowed extraction size")
        files: list[PurePosixPath] = []
        for info in infos:
            path = PurePosixPath(info.filename.replace("\\", "/"))
            mode = info.external_attr >> 16
            if (
                path.is_absolute()
                or (path.parts and path.parts[0].endswith(":"))
                or ".." in path.parts
                or stat.S_ISLNK(mode)
            ):
                raise InvalidDataset("Shapefile ZIP contains an unsafe path")
            if not info.is_dir():
                files.append(path)
        shapefiles = [path for path in files if path.suffix.lower() == ".shp"]
        if len(shapefiles) != 1:
            raise InvalidDataset("ZIP must contain exactly one .shp file")
        shape_path = shapefiles[0]
        siblings = {path.name.casefold() for path in files if path.parent == shape_path.parent}
        stem = shape_path.stem.casefold()
        if f"{stem}.dbf" not in siblings or f"{stem}.shx" not in siblings:
            raise InvalidDataset("Shapefile ZIP must include matching .dbf and .shx files")

        with tempfile.TemporaryDirectory(prefix="land-shapefile-") as temporary_dir:
            root = Path(temporary_dir)
            for info in infos:
                path = PurePosixPath(info.filename.replace("\\", "/"))
                if info.is_dir():
                    continue
                target = root.joinpath(*path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
            source_path = root.joinpath(*shape_path.parts)
            try:
                frame = gpd.read_file(source_path, engine="pyogrio")
            except Exception as exc:
                raise InvalidDataset(f"Could not read Shapefile: {exc}") from exc

        geometry_name = frame.geometry.name
        records = _frame_to_records(frame.drop(columns=[geometry_name]))
        geometries = [_json_value(geometry) for geometry in frame.geometry]
        for record, geometry in zip(records, geometries, strict=True):
            record["geometry"] = geometry
        metadata = {
            "source_crs": frame.crs.to_string() if frame.crs else None,
            "geometry_column": geometry_name,
            "geometry_types": sorted(
                {geometry.geom_type for geometry in frame.geometry if geometry is not None}
            ),
        }
        return ParsedDataset(
            rows=records,
            columns=[str(column) for column in frame.columns],
            metadata=metadata,
        )


def parse_dataset(filename: str, content: bytes) -> ParsedDataset:
    """Parse one supported upload without changing its original bytes."""

    file_format = detect_format(filename)
    if not content:
        raise InvalidDataset("The uploaded file is empty")
    metadata: dict[str, Any] = {"detected_format": file_format}

    try:
        if file_format == "csv":
            frame = pd.read_csv(io.BytesIO(content), dtype=object)
            rows = _frame_to_records(frame)
            columns = [str(column) for column in frame.columns]
        elif file_format == "excel":
            workbook = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
            if not workbook.sheet_names:
                raise InvalidDataset("Excel workbook has no worksheets")
            sheet_name = workbook.sheet_names[0]
            frame = pd.read_excel(workbook, sheet_name=sheet_name, dtype=object)
            rows = _frame_to_records(frame)
            columns = [str(column) for column in frame.columns]
            metadata["sheet_names"] = workbook.sheet_names
            metadata["selected_sheet"] = sheet_name
            if "Source_Metadata" in workbook.sheet_names:
                details = pd.read_excel(workbook, sheet_name="Source_Metadata", header=None, dtype=object)
                source_metadata = {}
                for _, values in details.iterrows():
                    if len(values) >= 2 and pd.notna(values.iloc[0]) and pd.notna(values.iloc[1]):
                        source_metadata[str(values.iloc[0]).strip()] = str(values.iloc[1]).strip()
                metadata["source_metadata"] = source_metadata
                for key, value in source_metadata.items():
                    normalized_key = re.sub(r"[^a-z]", "", key.lower())
                    if normalized_key in {"coordinatereferencesystem", "crs"}:
                        match = re.search(r"EPSG\s*:\s*\d+", value, re.IGNORECASE)
                        if match:
                            metadata["source_crs"] = CRS.from_user_input(match.group(0)).to_string()
                    elif normalized_key in {"areaunit", "defaultareaunit"}:
                        metadata["default_area_unit"] = value
        elif file_format in {"json", "geojson"}:
            try:
                payload = json.loads(content.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise InvalidDataset("JSON file is not valid UTF-8 JSON") from exc
            rows, geo_metadata = _json_records(payload)
            metadata.update(geo_metadata)
            columns = list(dict.fromkeys(key for row in rows for key in row))
        else:
            parsed = _parse_shapefile_zip(content)
            metadata.update(parsed.metadata)
            return ParsedDataset(
                rows=parsed.rows,
                columns=parsed.columns,
                metadata=metadata,
            )
    except IngestionError:
        raise
    except Exception as exc:
        raise InvalidDataset(f"Could not read {file_format} file: {exc}") from exc

    if not columns:
        raise InvalidDataset("Dataset must contain at least one column")
    if not rows:
        raise InvalidDataset("Dataset must contain at least one data row")
    if len(rows) > MAX_ROWS_PER_FILE:
        raise UploadTooLarge(f"Datasets may contain at most {MAX_ROWS_PER_FILE:,} rows per file")
    return ParsedDataset(rows=rows, columns=columns, metadata=metadata)


def _storage_root() -> Path:
    return local_storage_root()


def ingest_files(
    db: Session,
    *,
    workspace_id: UUID,
    user_id: UUID,
    source_name: str,
    jurisdiction: str | None,
    default_crs: str | None,
    files: list[UploadPayload],
) -> IngestionResult:
    """Persist one batch and its raw rows atomically, cleaning stored files on failure."""

    if not files:
        raise InvalidDataset("Upload at least one file")
    source_name = source_name.strip()
    if not source_name or len(source_name) > 200:
        raise InvalidDataset("Source name must contain 1 to 200 characters")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if sum(len(file.content) for file in files) > max_bytes:
        raise UploadTooLarge(f"Total upload size may not exceed {settings.max_upload_mb} MB")

    if default_crs:
        try:
            default_crs = CRS.from_user_input(default_crs).to_string()
        except CRSError as exc:
            raise InvalidDataset(f"'{default_crs}' is not a recognized coordinate reference system") from exc

    parsed_files: list[tuple[UploadPayload, ParsedDataset, str, str]] = []
    for upload in files:
        filename = _safe_filename(upload.filename)
        if len(upload.content) > max_bytes:
            raise UploadTooLarge(f"'{filename}' exceeds the {settings.max_upload_mb} MB file limit")
        file_format = detect_format(filename)
        parsed = parse_dataset(filename, upload.content)
        if default_crs and not parsed.metadata.get("source_crs"):
            parsed.metadata["source_crs"] = default_crs
        sha256 = hashlib.sha256(upload.content).hexdigest()
        duplicate = db.scalar(
            select(UploadedFile.id).where(
                UploadedFile.workspace_id == workspace_id,
                UploadedFile.sha256 == sha256,
            )
        )
        if duplicate is not None:
            raise DuplicateUpload(f"'{filename}' has already been uploaded to this workspace")
        parsed_files.append((upload, parsed, file_format, sha256))

    written_keys: list[str] = []
    try:
        source = db.scalar(
            select(DataSource).where(
                DataSource.workspace_id == workspace_id,
                DataSource.name == source_name,
            )
        )
        if source is None:
            source = DataSource(
                workspace_id=workspace_id,
                name=source_name,
                jurisdiction=jurisdiction,
                default_crs=default_crs,
                created_by=user_id,
            )
            db.add(source)
            db.flush()
        elif jurisdiction or default_crs:
            source.jurisdiction = jurisdiction or source.jurisdiction
            source.default_crs = default_crs or source.default_crs

        job = ProcessingJob(
            workspace_id=workspace_id,
            requested_by=user_id,
            status=JobStatus.INGESTING,
            started_at=datetime.now(UTC),
            config={"source_name": source_name, "file_count": len(files)},
        )
        db.add(job)
        db.flush()

        file_results: list[IngestedFile] = []
        total_records = 0
        for upload, parsed, file_format, sha256 in parsed_files:
            original_filename = _safe_filename(upload.filename)
            file_id = uuid.uuid4()
            object_key = f"{workspace_id}/{file_id}{Path(original_filename).suffix.lower()}"
            store_original(object_key, upload.content, upload.media_type)
            written_keys.append(object_key)

            metadata = {
                **parsed.metadata,
                "row_count": len(parsed.rows),
                "columns": parsed.columns,
                "source_crs_override": default_crs,
                "storage_backend": settings.storage_backend,
            }
            uploaded = UploadedFile(
                id=file_id,
                workspace_id=workspace_id,
                source_id=source.id,
                job_id=job.id,
                original_filename=original_filename,
                object_key=object_key,
                sha256=sha256,
                media_type=upload.media_type,
                detected_format=file_format,
                size_bytes=len(upload.content),
                metadata_json=metadata,
            )
            db.add(uploaded)
            db.flush()

            raw_rows = [
                {
                    "id": uuid.uuid4(),
                    "workspace_id": workspace_id,
                    "uploaded_file_id": file_id,
                    "job_id": job.id,
                    "row_number": row_number,
                    "original_data": row,
                }
                for row_number, row in enumerate(parsed.rows, start=1)
            ]
            for start in range(0, len(raw_rows), 1000):
                db.execute(insert(RawLandRecord), raw_rows[start : start + 1000])
            file_results.append(
                IngestedFile(
                    id=file_id,
                    filename=original_filename,
                    detected_format=file_format,
                    sha256=sha256,
                    size_bytes=len(upload.content),
                    row_count=len(parsed.rows),
                    columns=parsed.columns,
                    metadata=metadata,
                )
            )
            total_records += len(parsed.rows)

        job.status = JobStatus.MAPPING
        job.finished_at = datetime.now(UTC)
        job.summary = {
            "file_count": len(file_results),
            "total_records": total_records,
            "source_name": source_name,
            "files": [
                {
                    "uploaded_file_id": str(item.id),
                    "filename": item.filename,
                    "format": item.detected_format,
                    "rows": item.row_count,
                    "columns": item.columns,
                }
                for item in file_results
            ],
        }
        db.add(
            AuditLog(
                workspace_id=workspace_id,
                actor_id=user_id,
                action="dataset.ingested",
                object_type="processing_job",
                object_id=job.id,
                details={"file_count": len(file_results), "total_records": total_records},
            )
        )
        db.commit()
        return IngestionResult(
            job_id=job.id,
            workspace_id=workspace_id,
            source_id=source.id,
            status=job.status.value,
            total_records=total_records,
            files=file_results,
        )
    except Exception:
        db.rollback()
        for object_key in written_keys:
            try:
                delete_original(object_key)
            except Exception:
                logger.exception("Could not clean up failed upload object %s", object_key)
        raise
