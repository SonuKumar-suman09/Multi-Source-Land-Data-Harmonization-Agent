"""Repeat-safe validation of harmonized records using Pandera and PostGIS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pandas as pd
import pandera.pandas as pa
from pandera.errors import SchemaErrors
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.entities import (
    AgentExecution,
    AuditLog,
    DuplicateRecord,
    FindingSeverity,
    HarmonizedLandRecord,
    JobStatus,
    ProcessingJob,
    RecordStatus,
    ValidationResult,
)
from app.rag.retrieval import retrieve_rules


@dataclass(frozen=True)
class Finding:
    record_id: UUID
    code: str
    severity: FindingSeverity
    message: str
    evidence: dict[str, Any]
    action: str


CANONICAL_SCHEMA = pa.DataFrameSchema(
    {
        "plot_id": pa.Column(str, nullable=True, checks=pa.Check(lambda value: isinstance(value, str) and bool(value.strip()), element_wise=True, error="identifier must not be blank")),
        "owner_name": pa.Column(str, nullable=True, checks=pa.Check(lambda value: isinstance(value, str) and bool(value.strip()), element_wise=True, error="owner name must not be blank")),
        "area_acres": pa.Column(float, nullable=True, checks=pa.Check.greater_than(0)),
        "quality_score": pa.Column(float, nullable=True, checks=pa.Check.in_range(0, 100)),
    },
    strict=True,
    coerce=True,
)


def _schema_findings(records: list[HarmonizedLandRecord]) -> list[Finding]:
    frame = pd.DataFrame(
        [
            {
                "plot_id": record.plot_id,
                "owner_name": record.owner_name,
                "area_acres": float(record.area_acres) if record.area_acres is not None else None,
                "quality_score": float(record.quality_score) if record.quality_score is not None else None,
            }
            for record in records
        ],
        index=[str(record.id) for record in records],
    )
    try:
        CANONICAL_SCHEMA.validate(frame, lazy=True)
        return []
    except SchemaErrors as exc:
        issues: list[Finding] = []
        for failure in exc.failure_cases.to_dict(orient="records"):
            record_id = _parse_record_id(failure.get("index"))
            if record_id is None:
                continue
            column = failure.get("column")
            severity = FindingSeverity.CRITICAL if column in {"plot_id", "area_acres"} else FindingSeverity.WARNING
            issues.append(
                Finding(
                    record_id=record_id,
                    code=f"qa_schema_{column or 'record'}",
                    severity=severity,
                    message=f"Canonical field '{column or 'record'}' failed validation: {failure.get('check', 'schema check')}",
                    evidence={"failure_case": str(failure.get("failure_case")), "check": str(failure.get("check"))},
                    action="Review the original record and correct the source or mapping; no source value was changed.",
                )
            )
        return issues


def _parse_record_id(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _postgis_findings(db: Session, job_id: UUID) -> tuple[list[Finding], int]:
    invalid_rows = db.execute(
        text(
            """SELECT id, ST_IsValid(geometry) AS valid, ST_IsEmpty(geometry) AS empty,
                      ST_SRID(geometry) AS srid
               FROM harmonized_land_records
               WHERE job_id = :job_id AND geometry IS NOT NULL
                 AND (NOT ST_IsValid(geometry) OR ST_IsEmpty(geometry) OR ST_SRID(geometry) <> 4326)"""
        ),
        {"job_id": job_id},
    ).mappings().all()
    findings = [
        Finding(
            record_id=row["id"], code="qa_geometry_invalid", severity=FindingSeverity.CRITICAL,
            message="Geometry is invalid, empty, or not stored in EPSG:4326",
            evidence={"is_valid": row["valid"], "is_empty": row["empty"], "srid": row["srid"]},
            action="Inspect the source geometry and declared CRS; do not repair parcel boundaries automatically.",
        )
        for row in invalid_rows
    ]
    overlaps = db.execute(
        text(
            """SELECT a.id AS first_id, b.id AS second_id,
                      ST_Area(ST_CollectionExtract(ST_Intersection(a.geometry, b.geometry), 3)::geography) AS overlap_sqm
               FROM harmonized_land_records AS a
               JOIN harmonized_land_records AS b ON a.id < b.id
               WHERE a.job_id = :job_id AND b.job_id = :job_id
                 AND a.geometry IS NOT NULL AND b.geometry IS NOT NULL
                 AND a.plot_id IS DISTINCT FROM b.plot_id
                 AND GeometryType(a.geometry) IN ('POLYGON', 'MULTIPOLYGON')
                 AND GeometryType(b.geometry) IN ('POLYGON', 'MULTIPOLYGON')
                 AND ST_IsValid(a.geometry) AND ST_IsValid(b.geometry)
                 AND ST_Intersects(a.geometry, b.geometry)
                 AND ST_Area(ST_CollectionExtract(ST_Intersection(a.geometry, b.geometry), 3)::geography) > 1.0"""
        ),
        {"job_id": job_id},
    ).mappings().all()
    for pair in overlaps:
        for record_id in (pair["first_id"], pair["second_id"]):
            findings.append(
                Finding(
                    record_id=record_id, code="qa_spatial_overlap", severity=FindingSeverity.WARNING,
                    message="Parcel polygon overlaps another parcel with a different identifier by more than one square metre",
                    evidence={"other_record_id": str(pair["second_id"] if record_id == pair["first_id"] else pair["first_id"]), "overlap_sqm": round(float(pair["overlap_sqm"]), 3)},
                    action="Review both source boundaries and jurisdiction rules before accepting either geometry.",
                )
            )
    return findings, len(overlaps)


def run_quality_assurance(db: Session, *, job_id: UUID, workspace_id: UUID, user_id: UUID) -> dict[str, Any]:
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id, ProcessingJob.workspace_id == workspace_id).with_for_update())
    if job is None:
        raise LookupError("Processing job not found")
    previous = db.scalar(
        select(AgentExecution).where(
            AgentExecution.job_id == job_id,
            AgentExecution.agent_name == "quality_assurance",
            AgentExecution.status == "completed",
        ).order_by(AgentExecution.created_at.desc())
    )
    if previous and previous.output_summary:
        return {"job_id": str(job_id), **previous.output_summary, "already_completed": True}
    if job.status not in {JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_ERRORS, JobStatus.VALIDATING}:
        raise ValueError("Harmonize this job before running quality assurance")
    records = db.scalars(select(HarmonizedLandRecord).where(HarmonizedLandRecord.job_id == job_id).order_by(HarmonizedLandRecord.id)).all()
    if not records:
        raise ValueError("This job has no harmonized records to validate")
    rule_context = retrieve_rules(
        db,
        workspace_id=workspace_id,
        query="Land-record validation policy for plot identifiers, ownership, positive area, geometry CRS, and parcel overlaps",
        limit=5,
    )
    rule_references = [
        {
            "rule_key": rule["document_rule_key"],
            "title": rule["title"],
            "source_reference": rule["source_reference"],
            "similarity": rule["similarity"],
        }
        for rule in rule_context
    ]

    started = datetime.now(UTC)
    execution = AgentExecution(
        job_id=job_id, agent_name="quality_assurance", status="running", attempt=1,
        input_summary={"record_count": len(records), "checks": ["pandera_schema", "land_rules", "postgis_geometry", "parcel_overlap"], "retrieved_rules": rule_references},
        started_at=started,
    )
    db.add(execution)
    job.status = JobStatus.VALIDATING
    db.flush()

    findings = _schema_findings(records)
    existing_codes: dict[UUID, set[str]] = {record.id: set() for record in records}
    prior_findings = db.scalars(select(ValidationResult).where(ValidationResult.job_id == job_id)).all()
    for finding in prior_findings:
        if finding.harmonized_record_id in existing_codes:
            existing_codes[finding.harmonized_record_id].add(finding.code)

    known_record_ids = {record.id for record in records}
    for record in records:
        if not record.plot_id or not record.plot_id.strip():
            findings.append(Finding(record.id, "qa_plot_id_required", FindingSeverity.CRITICAL, "Plot identifier is required", {}, "Confirm the parcel identifier against the source record."))
        if record.area_acres is None or record.area_acres <= 0:
            findings.append(Finding(record.id, "qa_area_positive", FindingSeverity.CRITICAL, "Area must be a positive numeric value in acres", {"area_acres": str(record.area_acres) if record.area_acres is not None else None}, "Confirm the numeric value and source unit."))
        if not record.owner_name or not record.owner_name.strip():
            findings.append(Finding(record.id, "qa_owner_present", FindingSeverity.WARNING, "Owner name is missing", {}, "Check the original ownership source; do not infer an owner."))
        if record.geometry is None:
            findings.append(Finding(record.id, "qa_geometry_present", FindingSeverity.WARNING, "No valid normalized geometry is available", {"source_crs": record.source_crs}, "Review source coordinates and CRS metadata."))

    spatial_findings, overlap_count = _postgis_findings(db, job_id)
    findings.extend(spatial_findings)
    duplicate_rows = db.scalars(select(DuplicateRecord).where(DuplicateRecord.job_id == job_id)).all()
    for candidate in duplicate_rows:
        conflict = bool((candidate.evidence or {}).get("conflict"))
        severity = FindingSeverity.CRITICAL if conflict else FindingSeverity.INFO
        for record_id in (candidate.record_a_id, candidate.record_b_id):
            if record_id in known_record_ids:
                findings.append(Finding(record_id, "qa_duplicate_conflict" if conflict else "qa_duplicate_candidate", severity,
                                        "Duplicate plot identifier has conflicting owner or area values" if conflict else "Duplicate plot identifier candidate requires confirmation",
                                        {"duplicate_pair_id": str(candidate.id), "method": candidate.method, **(candidate.evidence or {})},
                                        "Compare source documents and preserve both original values until a reviewer decides."))

    unique_findings: dict[tuple[UUID, str, str], Finding] = {}
    for finding in findings:
        if finding.record_id in known_record_ids and finding.code not in existing_codes[finding.record_id]:
            discriminator = str(
                finding.evidence.get("duplicate_pair_id")
                or finding.evidence.get("other_record_id")
                or ""
            )
            unique_findings[(finding.record_id, finding.code, discriminator)] = finding
    findings = list(unique_findings.values())
    issue_counts = {severity.value: 0 for severity in FindingSeverity}
    by_record: dict[UUID, list[Finding]] = {record.id: [] for record in records}
    for finding in findings:
        issue_counts[finding.severity.value] += 1
        by_record[finding.record_id].append(finding)
        db.add(
            ValidationResult(
                job_id=job_id, harmonized_record_id=finding.record_id,
                code=finding.code, severity=finding.severity, message=finding.message,
                suggested_action=finding.action, evidence=finding.evidence,
            )
        )

    for record in records:
        record_findings = by_record[record.id]
        critical = sum(item.severity == FindingSeverity.CRITICAL for item in record_findings)
        warning = sum(item.severity == FindingSeverity.WARNING for item in record_findings)
        info = sum(item.severity == FindingSeverity.INFO for item in record_findings)
        record.quality_score = max(0, 100 - critical * 25 - warning * 10 - info * 3)
        if record.status == RecordStatus.CONFLICT:
            continue
        if critical:
            record.status = RecordStatus.INVALID
        elif warning:
            record.status = RecordStatus.NEEDS_REVIEW
        else:
            record.status = RecordStatus.VALID

    valid = sum(record.status == RecordStatus.VALID for record in records)
    invalid = sum(record.status == RecordStatus.INVALID for record in records)
    conflicts = sum(record.status == RecordStatus.CONFLICT for record in records)
    review = sum(record.status == RecordStatus.NEEDS_REVIEW for record in records)
    average_score = round(sum(float(record.quality_score or 0) for record in records) / len(records), 2)
    summary = {
        "records_checked": len(records), "valid_records": valid, "invalid_records": invalid,
        "review_records": review, "conflict_records": conflicts,
        "critical_errors": issue_counts[FindingSeverity.CRITICAL.value],
        "warnings": issue_counts[FindingSeverity.WARNING.value],
        "informational_issues": issue_counts[FindingSeverity.INFO.value],
        "overlapping_pairs": overlap_count, "quality_score": average_score,
        "retrieved_rules": rule_references,
    }
    finished = datetime.now(UTC)
    execution.status = "completed"
    execution.finished_at = finished
    execution.output_summary = summary
    execution.input_summary = {
        **execution.input_summary,
        "duration_ms": round((finished - started).total_seconds() * 1000, 2),
    }
    job.status = JobStatus.COMPLETED_WITH_ERRORS if invalid or review or conflicts else JobStatus.COMPLETED
    job.finished_at = finished
    job.summary = {**(job.summary or {}), **summary}
    db.add(AuditLog(workspace_id=workspace_id, actor_id=user_id, action="dataset.quality_assured", object_type="processing_job", object_id=job_id, details=summary))
    db.commit()
    return {"job_id": str(job_id), **summary, "already_completed": False}
