"""Downloadable processing report response types."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ReportSourceFile(BaseModel):
    id: UUID
    filename: str
    format: str | None = None
    size_bytes: int
    uploaded_at: datetime


class ReportAgentExecution(BaseModel):
    id: UUID
    agent_name: str
    status: str
    attempt: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: float | None = None
    error_code: str | None = None
    output_summary: dict[str, Any] = Field(default_factory=dict)


class ReportAuditEvent(BaseModel):
    id: UUID
    action: str
    actor_email: str | None = None
    created_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)


class ReportFinding(BaseModel):
    record_id: UUID | None = None
    code: str
    severity: str
    message: str
    suggested_action: str | None = None


class ProcessingReport(BaseModel):
    job_id: UUID
    source_name: str
    status: str
    created_at: datetime
    finished_at: datetime | None = None
    processing_time_ms: float | None = None
    total_records: int
    harmonized_records: int
    valid_records: int
    invalid_records: int
    review_records: int
    conflict_records: int
    duplicate_pairs: int
    quality_score: float | None = None
    severity_counts: dict[str, int] = Field(default_factory=dict)
    source_files: list[ReportSourceFile] = Field(default_factory=list)
    agent_executions: list[ReportAgentExecution] = Field(default_factory=list)
    audit_events: list[ReportAuditEvent] = Field(default_factory=list)
    findings: list[ReportFinding] = Field(default_factory=list)
