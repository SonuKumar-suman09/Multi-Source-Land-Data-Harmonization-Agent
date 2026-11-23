"""Deterministic schema mapping and canonical land-record transformation."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from geoalchemy2.shape import from_shape
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError
from shapely.geometry import shape
from shapely import transform as transform_geometry
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    AuditLog,
    DuplicateRecord,
    HarmonizedLandRecord,
    JobStatus,
    ProcessingJob,
    RawLandRecord,
    RecordProvenance,
    RecordStatus,
    SchemaMapping,
    UploadedFile,
    ValidationResult,
    FindingSeverity,
)

AREA_FACTORS = {
    "acre": Decimal("1"), "acres": Decimal("1"), "ac": Decimal("1"),
    "hectare": Decimal("2.4710538146717"), "hectares": Decimal("2.4710538146717"), "ha": Decimal("2.4710538146717"),
    "sqm": Decimal("0.00024710538146717"), "squaremeters": Decimal("0.00024710538146717"),
    "sqft": Decimal("0.0000229568411386593"), "squarefeet": Decimal("0.0000229568411386593"),
}
ALIASES = {
    "plot_id": {"plotid", "plotnumber", "khasrano", "khasranumber", "parcelid", "parcelref", "surveyid"},
    "owner_name": {"ownername", "landholder", "recordedholder", "owner", "proprietorname"},
    "area_acres": {"areaacres", "areainacres", "sizeacres", "areaha", "areahectares", "sizehectares", "areasqm", "areasqmeters", "area", "size", "landarea"},
    "recorded_at": {"recorddate", "recordedat", "surveyedon", "surveydate", "registrationdate"},
    "geometry": {"geometry", "geom", "shape", "boundary"},
    "latitude": {"latitude", "lat"}, "longitude": {"longitude", "lon", "long", "lng"},
    "easting": {"easting", "eastingm", "x"}, "northing": {"northing", "northingm", "y"},
}


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def map_columns(columns: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Return unambiguous source-to-canonical map and explicitly ambiguous fields."""
    candidates_by_field: dict[str, list[str]] = {}
    for column in columns:
        normalized = _key(column)
        candidates = [canonical for canonical, aliases in ALIASES.items() if normalized in aliases]
        if not candidates:
            continue
        candidates_by_field.setdefault(candidates[0], []).append(column)
    mapped: dict[str, str] = {}
    ambiguous: dict[str, str] = {}
    for canonical, source_columns in candidates_by_field.items():
        if len(source_columns) > 1:
            ambiguous.update({column: canonical for column in source_columns})
        else:
            mapped[source_columns[0]] = canonical
    return mapped, ambiguous


def mapping_review_complete(db: Session, job_id: UUID) -> bool:
    """Return true only when each uploaded header has a stored human decision."""
    files = db.scalars(select(UploadedFile).where(UploadedFile.job_id == job_id)).all()
    expected = {(file.id, column) for file in files for column in file.metadata_json.get("columns", [])}
    if not expected:
        return False
    rows = db.scalars(select(SchemaMapping).where(SchemaMapping.job_id == job_id)).all()
    actual = {
        (entry.uploaded_file_id, entry.source_column)
        for entry in rows
        if entry.status in {"accepted_human", "accepted_deterministic", "rejected"}
    }
    return actual == expected


def _area(value: Any, source_column: str, declared_unit: str | None) -> tuple[Decimal | None, str | None]:
    if value is None or str(value).strip() == "":
        return None, "Area is missing"
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        return None, "Area is not numeric"
    if not number.is_finite() or number <= 0:
        return None, "Area must be a positive finite number"
    unit_text = _key(source_column)
    unit = next((name for name in AREA_FACTORS if name in unit_text), None)
    if unit is None and declared_unit:
        unit = _key(declared_unit)
    factor = AREA_FACTORS.get(unit or "")
    if factor is None:
        return None, "Area unit is unknown; review required"
    return (number * factor).quantize(Decimal("0.000001")), None


def _record_date(value: Any) -> tuple[date | None, str | None]:
    if value is None or str(value).strip() == "":
        return None, None
    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    text = str(value).strip()
    formats = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d-%b-%Y", "%d-%B-%Y")
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date(), None
        except ValueError:
            pass
    try:
        return datetime.strptime(text, "%Y/%m/%d").date(), None
    except ValueError:
        pass
    # Slash dates are accepted only when the month/day ordering is unambiguous.
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        first, second, year = map(int, match.groups())
        try:
            if first > 12:
                return date(year, second, first), None
            if second > 12:
                return date(year, first, second), None
        except ValueError:
            return None, "Date value is invalid; review required"
        return None, "Date ordering is ambiguous; review required"
    return None, "Date format is unrecognized; review required"


def _geometry(row: dict[str, Any], mapped: dict[str, str], source_crs: str | None):
    values = {canonical: row.get(source) for source, canonical in mapped.items()}
    raw_geometry = values.get("geometry")
    if isinstance(raw_geometry, dict):
        geom = shape(raw_geometry)
    elif values.get("latitude") is not None and values.get("longitude") is not None:
        geom = shape({"type": "Point", "coordinates": [float(values["longitude"]), float(values["latitude"])]})
        source_crs = source_crs or "EPSG:4326"
    elif values.get("easting") is not None and values.get("northing") is not None:
        if not source_crs:
            return None, None, "Projected coordinates have no declared CRS"
        geom = shape({"type": "Point", "coordinates": [float(values["easting"]), float(values["northing"])]})
    else:
        return None, source_crs, "Geometry is missing"
    try:
        if not geom.is_valid or geom.is_empty:
            return None, source_crs, "Geometry is empty or invalid"
        crs = CRS.from_user_input(source_crs or "EPSG:4326")
        if not crs.equals(CRS.from_epsg(4326)):
            geom = transform_geometry(
                geom,
                Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform,
                interleaved=False,
            )
        if geom.is_empty or not geom.is_valid:
            return None, str(crs), "Geometry is invalid after CRS transformation"
        bounds = geom.bounds
        if bounds[0] < -180 or bounds[2] > 180 or bounds[1] < -90 or bounds[3] > 90:
            return None, str(crs), "Coordinates are outside EPSG:4326 bounds"
        return geom, str(crs), None
    except (ValueError, TypeError, CRSError):
        return None, source_crs, "Geometry or CRS could not be interpreted"


def harmonize_job(db: Session, *, job_id: UUID, workspace_id: UUID, user_id: UUID) -> dict[str, Any]:
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id, ProcessingJob.workspace_id == workspace_id).with_for_update())
    if job is None:
        raise LookupError("Processing job not found")
    if db.scalar(select(HarmonizedLandRecord.id).where(HarmonizedLandRecord.job_id == job_id).limit(1)):
        raise ValueError("This job has already been harmonized")
    if job.status not in {JobStatus.MAPPING, JobStatus.AWAITING_REVIEW}:
        raise ValueError(f"Job cannot be harmonized from status '{job.status.value}'")
    job.status = JobStatus.HARMONIZING
    files = db.scalars(select(UploadedFile).where(UploadedFile.job_id == job_id).order_by(UploadedFile.created_at)).all()
    outputs: list[HarmonizedLandRecord] = []
    findings = 0
    for uploaded in files:
        rows = db.scalars(select(RawLandRecord).where(RawLandRecord.uploaded_file_id == uploaded.id).order_by(RawLandRecord.row_number)).all()
        saved_mappings = db.scalars(
            select(SchemaMapping).where(
                SchemaMapping.job_id == job_id,
                SchemaMapping.uploaded_file_id == uploaded.id,
            )
        ).all()
        if saved_mappings:
            accepted = {
                entry.source_column: entry.canonical_field
                for entry in saved_mappings
                if entry.status in {"accepted_human", "accepted_deterministic"}
                and entry.canonical_field in ALIASES
            }
            mapped, ambiguous = accepted, {}
        else:
            mapped, ambiguous = map_columns(uploaded.metadata_json.get("columns", []))
        mappings: dict[str, UUID] = {}
        source_id = uploaded.source_id
        if saved_mappings:
            mappings = {
                entry.canonical_field: entry.id
                for entry in saved_mappings
                if entry.status in {"accepted_human", "accepted_deterministic"}
                and entry.canonical_field in ALIASES
            }
        else:
            for column in uploaded.metadata_json.get("columns", []):
                canonical = mapped.get(column) or ambiguous.get(column)
                if canonical:
                    decision = "accepted_deterministic" if column in mapped else "review_required"
                    entry = SchemaMapping(job_id=job_id, source_id=source_id, uploaded_file_id=uploaded.id, source_column=column, canonical_field=canonical, confidence=Decimal("1.000") if column in mapped else None, evidence={"method": "exact_normalized_alias", "source_format": uploaded.detected_format}, status=decision)
                    db.add(entry)
                    if column in mapped:
                        mappings[canonical] = entry.id
        db.flush()
        metadata = uploaded.metadata_json
        declared_unit = metadata.get("default_area_unit")
        source_crs = metadata.get("source_crs")
        for raw in rows:
            data = raw.original_data
            values = {canonical: data.get(source) for source, canonical in mapped.items()}
            issues: list[tuple[str, str, FindingSeverity]] = []
            geom, used_crs, geometry_issue = _geometry(data, mapped, source_crs)
            if geometry_issue:
                issues.append(("geometry_invalid_or_missing", geometry_issue, FindingSeverity.WARNING))
            area_column = next((source for source, target in mapped.items() if target == "area_acres"), "")
            area, area_issue = _area(values.get("area_acres"), area_column, declared_unit)
            if area_issue:
                issues.append(("area_invalid_or_unknown_unit", area_issue, FindingSeverity.WARNING))
            record_date, date_issue = _record_date(values.get("recorded_at"))
            if date_issue:
                issues.append(("date_review_required", date_issue, FindingSeverity.INFO))
            plot_id = str(values.get("plot_id")).strip() if values.get("plot_id") is not None else None
            owner = str(values.get("owner_name")).strip() if values.get("owner_name") is not None else None
            if not plot_id:
                issues.append(("plot_id_missing", "Land-record identifier is missing", FindingSeverity.CRITICAL))
            if not owner:
                issues.append(("owner_missing", "Owner name is missing", FindingSeverity.WARNING))
            if ambiguous:
                issues.append(("schema_mapping_ambiguous", "Multiple source columns map to the same canonical field", FindingSeverity.WARNING))
            quality = max(0, 100 - 25 * sum(severity == FindingSeverity.CRITICAL for _, _, severity in issues) - 12 * sum(severity == FindingSeverity.WARNING for _, _, severity in issues) - 5 * sum(severity == FindingSeverity.INFO for _, _, severity in issues))
            status = RecordStatus.NEEDS_REVIEW if issues or ambiguous else RecordStatus.VALID
            record = HarmonizedLandRecord(workspace_id=workspace_id, job_id=job_id, plot_id=plot_id, owner_name=owner or None, area_acres=area, recorded_at=record_date, geometry=from_shape(geom, srid=4326) if geom else None, source_crs=used_crs, normalized_attributes={"source_values": data, "mapping": mapped}, status=status, quality_score=quality)
            db.add(record)
            db.flush()
            db.add(RecordProvenance(harmonized_record_id=record.id, raw_record_id=raw.id, schema_mapping_id=mappings.get("plot_id"), transformation_history=[{"operation": "deterministic_schema_mapping", "mapping": mapped}, {"operation": "area_to_acres", "declared_unit": declared_unit}, {"operation": "geometry_to_epsg4326", "source_crs": used_crs}]))
            for code, message, severity in issues:
                db.add(ValidationResult(job_id=job_id, harmonized_record_id=record.id, raw_record_id=raw.id, code=code, message=message, severity=severity, suggested_action="Review the original source value; no critical value was overwritten", evidence={"source_row": raw.row_number}))
                findings += 1
            outputs.append(record)

    duplicates = 0
    by_plot: dict[str, list[HarmonizedLandRecord]] = {}
    for record in outputs:
        if record.plot_id:
            by_plot.setdefault(record.plot_id.casefold(), []).append(record)
    for same_plot in by_plot.values():
        for index, first in enumerate(same_plot):
            for second in same_plot[index + 1:]:
                a, b = sorted((first, second), key=lambda item: str(item.id))
                conflict = first.owner_name != second.owner_name or first.area_acres != second.area_acres
                db.add(DuplicateRecord(job_id=job_id, record_a_id=a.id, record_b_id=b.id, similarity_score=Decimal("1.000"), method="normalized_plot_id", evidence={"plot_id": first.plot_id, "owner_conflict": first.owner_name != second.owner_name, "area_conflict": first.area_acres != second.area_acres, "conflict": conflict}))
                if conflict:
                    first.status = second.status = RecordStatus.CONFLICT
                    for record in (first, second):
                        db.add(ValidationResult(job_id=job_id, harmonized_record_id=record.id, code="duplicate_plot_conflict", severity=FindingSeverity.CRITICAL, message="Records share a plot identifier but disagree on owner or area", suggested_action="Review source documents; do not auto-select a value", evidence={"plot_id": first.plot_id}))
                        findings += 1
                duplicates += 1
    valid_count = sum(record.status == RecordStatus.VALID for record in outputs)
    score = round(sum(float(record.quality_score or 0) for record in outputs) / len(outputs), 2) if outputs else 0.0
    job.status = JobStatus.COMPLETED_WITH_ERRORS if findings else JobStatus.COMPLETED
    job.finished_at = datetime.now(UTC)
    job.summary = {**(job.summary or {}), "harmonized_records": len(outputs), "valid_records": valid_count, "review_records": len(outputs) - valid_count, "duplicate_pairs": duplicates, "validation_findings": findings, "quality_score": score}
    db.add(AuditLog(workspace_id=workspace_id, actor_id=user_id, action="dataset.harmonized", object_type="processing_job", object_id=job_id, details=job.summary))
    db.commit()
    return {"job_id": str(job_id), **job.summary}
