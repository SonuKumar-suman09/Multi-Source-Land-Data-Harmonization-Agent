"""Workspace-authorized JSON, CSV, and PDF processing reports."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from html import escape
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.entities import (
    AgentExecution,
    AuditLog,
    DataSource,
    DuplicateRecord,
    FindingSeverity,
    HarmonizedLandRecord,
    ProcessingJob,
    RawLandRecord,
    RecordProvenance,
    RecordStatus,
    UploadedFile,
    User,
    ValidationResult,
    WorkspaceMembership,
)
from app.schemas.reports import (
    ProcessingReport,
    ReportAgentExecution,
    ReportAuditEvent,
    ReportFinding,
    ReportSourceFile,
)

router = APIRouter(prefix="/reports", tags=["reports and audit"])


def _get_job(db: Session, job_id: UUID, user_id: UUID) -> ProcessingJob:
    workspace_ids = select(WorkspaceMembership.workspace_id).where(
        WorkspaceMembership.user_id == user_id
    )
    job = db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.workspace_id.in_(workspace_ids),
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    return job


def _build_report(db: Session, job: ProcessingJob) -> ProcessingReport:
    # Membership controls authorization; using the workspace ID for report data
    # also supports jobs whose requester account has since been removed.
    record_statuses = db.execute(
        select(HarmonizedLandRecord.status, func.count())
        .where(HarmonizedLandRecord.job_id == job.id)
        .group_by(HarmonizedLandRecord.status)
    ).all()
    record_counts = {status.value: int(count) for status, count in record_statuses}
    raw_count = db.scalar(
        select(func.count()).select_from(RawLandRecord).where(RawLandRecord.job_id == job.id)
    ) or 0
    harmonized_count = db.scalar(
        select(func.count()).select_from(HarmonizedLandRecord).where(HarmonizedLandRecord.job_id == job.id)
    ) or 0
    duplicate_count = db.scalar(
        select(func.count()).select_from(DuplicateRecord).where(DuplicateRecord.job_id == job.id)
    ) or 0
    severity_rows = db.execute(
        select(ValidationResult.severity, func.count())
        .where(ValidationResult.job_id == job.id)
        .group_by(ValidationResult.severity)
    ).all()
    severity_counts = {severity.value: int(count) for severity, count in severity_rows}

    files = db.scalars(
        select(UploadedFile).where(UploadedFile.job_id == job.id).order_by(UploadedFile.created_at)
    ).all()
    executions = db.scalars(
        select(AgentExecution).where(AgentExecution.job_id == job.id).order_by(AgentExecution.created_at)
    ).all()
    audit_rows = db.execute(
        select(AuditLog, User.email)
        .outerjoin(User, AuditLog.actor_id == User.id)
        .where(
            AuditLog.workspace_id == job.workspace_id,
            AuditLog.object_type == "processing_job",
            AuditLog.object_id == job.id,
        )
        .order_by(AuditLog.created_at)
    ).all()
    findings = db.scalars(
        select(ValidationResult)
        .where(ValidationResult.job_id == job.id)
        .order_by(ValidationResult.severity, ValidationResult.created_at)
        .limit(500)
    ).all()

    start_times = [execution.started_at for execution in executions if execution.started_at]
    finish_times = [execution.finished_at for execution in executions if execution.finished_at]
    started_at = min(start_times) if start_times else job.started_at
    finished_at = job.finished_at or (max(finish_times) if finish_times else None)
    processing_ms = (
        round((finished_at - started_at).total_seconds() * 1000, 2)
        if started_at and finished_at and finished_at >= started_at
        else None
    )
    quality_score = (job.summary or {}).get("quality_score")
    source_name = (job.config or {}).get("source_name")
    if not source_name:
        source = db.scalar(
            select(DataSource)
            .join(UploadedFile, UploadedFile.source_id == DataSource.id)
            .where(UploadedFile.job_id == job.id)
            .order_by(UploadedFile.created_at)
            .limit(1)
        )
        source_name = source.name if source else "Land data import"

    return ProcessingReport(
        job_id=job.id,
        source_name=source_name,
        status=job.status.value,
        created_at=job.created_at,
        finished_at=finished_at,
        processing_time_ms=processing_ms,
        total_records=int(raw_count),
        harmonized_records=int(harmonized_count),
        valid_records=record_counts.get(RecordStatus.VALID.value, 0),
        invalid_records=record_counts.get(RecordStatus.INVALID.value, 0),
        review_records=record_counts.get(RecordStatus.NEEDS_REVIEW.value, 0),
        conflict_records=record_counts.get(RecordStatus.CONFLICT.value, 0),
        duplicate_pairs=int(duplicate_count),
        quality_score=float(quality_score) if quality_score is not None else None,
        severity_counts={severity.value: int(severity_counts.get(severity.value, 0)) for severity in FindingSeverity},
        source_files=[
            ReportSourceFile(
                id=file.id,
                filename=file.original_filename,
                format=file.detected_format,
                size_bytes=file.size_bytes,
                uploaded_at=file.created_at,
            )
            for file in files
        ],
        agent_executions=[
            ReportAgentExecution(
                id=execution.id,
                agent_name=execution.agent_name,
                status=execution.status,
                attempt=execution.attempt,
                started_at=execution.started_at,
                finished_at=execution.finished_at,
                duration_ms=(execution.input_summary or {}).get("duration_ms"),
                error_code=execution.error_code,
                output_summary=execution.output_summary or {},
            )
            for execution in executions
        ],
        audit_events=[
            ReportAuditEvent(
                id=audit.id,
                action=audit.action,
                actor_email=actor_email,
                created_at=audit.created_at,
                details=audit.details or {},
            )
            for audit, actor_email in audit_rows
        ],
        findings=[
            ReportFinding(
                record_id=finding.harmonized_record_id,
                code=finding.code,
                severity=finding.severity.value,
                message=finding.message,
                suggested_action=finding.suggested_action,
            )
            for finding in findings
        ],
    )


@router.get("/jobs/{job_id}", response_model=ProcessingReport)
def get_processing_report(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProcessingReport:
    return _build_report(db, _get_job(db, job_id, user.id))


def _csv_safe(value: Any) -> str:
    """Escape spreadsheet formulas in user-provided text fields."""
    text_value = "" if value is None else str(value)
    if text_value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text_value
    return text_value


@router.get("/jobs/{job_id}/csv")
def download_job_csv(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    job = _get_job(db, job_id, user.id)
    query = (
        select(
            HarmonizedLandRecord,
            RawLandRecord,
            UploadedFile.original_filename,
            RecordProvenance.transformation_history,
            func.ST_AsGeoJSON(HarmonizedLandRecord.geometry, 6).label("geometry_json"),
        )
        .outerjoin(RecordProvenance, RecordProvenance.harmonized_record_id == HarmonizedLandRecord.id)
        .outerjoin(RawLandRecord, RawLandRecord.id == RecordProvenance.raw_record_id)
        .outerjoin(UploadedFile, UploadedFile.id == RawLandRecord.uploaded_file_id)
        .where(HarmonizedLandRecord.job_id == job.id)
        .order_by(HarmonizedLandRecord.plot_id.asc().nullslast(), UploadedFile.original_filename)
    )
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow([
        "harmonized_record_id", "source_file", "source_row_number", "raw_record_id",
        "plot_id", "owner_name", "area_acres", "recorded_at", "status", "quality_score",
        "geometry_geojson", "source_data_json", "transformation_history_json",
    ])
    for record, raw, filename, history, geometry_json in db.execute(query):
        writer.writerow([
            str(record.id), _csv_safe(filename), raw.row_number if raw else "",
            str(raw.id) if raw else "", _csv_safe(record.plot_id), _csv_safe(record.owner_name),
            str(record.area_acres) if record.area_acres is not None else "",
            record.recorded_at.isoformat() if record.recorded_at else "", record.status.value,
            str(record.quality_score) if record.quality_score is not None else "",
            geometry_json or "", json.dumps(raw.original_data, ensure_ascii=False, default=str) if raw else "",
            json.dumps(history or [], ensure_ascii=False, default=str),
        ])
    filename = f"land-report-{job.id}.csv"
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _pdf_bytes(report: ProcessingReport) -> bytes:
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=landscape(letter),
        rightMargin=0.48 * inch,
        leftMargin=0.48 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        title=f"Land data processing report {report.job_id}",
        author="Multi-Source Land-Data Harmonization Agent",
    )
    styles = getSampleStyleSheet()
    story: list[Any] = [
        Paragraph("Land Data Processing Report", styles["Title"]),
        Paragraph(f"Source: {escape(report.source_name)} · Job: {report.job_id}", styles["Normal"]),
        Paragraph(f"Status: {escape(report.status)} · Generated: {datetime.now(UTC).isoformat(timespec='seconds')}", styles["Normal"]),
        Spacer(1, 0.2 * inch),
    ]

    summary_rows = [
        ["Source records", "Harmonized", "Valid", "Invalid", "Review", "Conflicts", "Duplicates", "Quality"],
        [report.total_records, report.harmonized_records, report.valid_records, report.invalid_records,
         report.review_records, report.conflict_records, report.duplicate_pairs,
         f"{report.quality_score:.2f}%" if report.quality_score is not None else "—"],
    ]
    summary_table = Table(summary_rows, repeatRows=1)
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7f0eb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#315346")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d9e4dd")),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([Paragraph("Processing summary", styles["Heading2"]), summary_table, Spacer(1, 0.18 * inch)])
    story.append(Paragraph(
        f"Processing time: {report.processing_time_ms:.0f} ms" if report.processing_time_ms is not None else "Processing time: not available",
        styles["Normal"],
    ))

    if report.source_files:
        rows = [["Source file", "Format", "Size (bytes)", "Uploaded"]]
        rows.extend([[escape(item.filename), item.format or "—", item.size_bytes, item.uploaded_at.isoformat(timespec="seconds")] for item in report.source_files])
        source_table = Table(rows, colWidths=[3.5 * inch, 1.3 * inch, 1.2 * inch, 2.5 * inch], repeatRows=1)
        source_table.setStyle(_pdf_table_style())
        story.extend([Spacer(1, 0.16 * inch), Paragraph("Source files", styles["Heading2"]), source_table])

    if report.agent_executions:
        rows = [["Agent", "Status", "Attempt", "Duration (ms)", "Error"]]
        rows.extend([
            [escape(item.agent_name), escape(item.status), item.attempt,
             f"{item.duration_ms:.0f}" if item.duration_ms is not None else "—",
             escape(item.error_code or "—")]
            for item in report.agent_executions
        ])
        agent_table = Table(rows, colWidths=[2.6 * inch, 1.2 * inch, 0.8 * inch, 1.5 * inch, 2.8 * inch], repeatRows=1)
        agent_table.setStyle(_pdf_table_style())
        story.extend([Spacer(1, 0.16 * inch), Paragraph("Agent execution", styles["Heading2"]), agent_table])

    if report.audit_events:
        rows = [["Event", "Actor", "Recorded at"]]
        rows.extend([[escape(item.action), escape(item.actor_email or "System"), item.created_at.isoformat(timespec="seconds")] for item in report.audit_events])
        audit_table = Table(rows, colWidths=[3.0 * inch, 2.5 * inch, 3.4 * inch], repeatRows=1)
        audit_table.setStyle(_pdf_table_style())
        story.extend([Spacer(1, 0.16 * inch), Paragraph("Audit history", styles["Heading2"]), audit_table])

    if report.findings:
        rows = [["Severity", "Rule", "Record", "Finding"]]
        rows.extend([
            [escape(item.severity), escape(item.code), str(item.record_id or "—"), Paragraph(escape(item.message), styles["BodyText"])]
            for item in report.findings[:100]
        ])
        finding_table = Table(rows, colWidths=[1.0 * inch, 1.65 * inch, 2.0 * inch, 4.25 * inch], repeatRows=1)
        finding_table.setStyle(_pdf_table_style())
        story.extend([Spacer(1, 0.16 * inch), Paragraph("Validation findings (first 100)", styles["Heading2"]), finding_table])

    story.append(Spacer(1, 0.12 * inch))
    story.append(Paragraph("This report summarizes recorded processing results. Review flagged source values before making land decisions.", styles["Italic"]))
    document.build(story)
    return output.getvalue()


def _pdf_table_style() -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7f0eb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#315346")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dce6df")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7faf8")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ])


@router.get("/jobs/{job_id}/pdf")
def download_job_pdf(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    report = _build_report(db, _get_job(db, job_id, user.id))
    return Response(
        content=_pdf_bytes(report),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="land-report-{job_id}.pdf"'},
    )
