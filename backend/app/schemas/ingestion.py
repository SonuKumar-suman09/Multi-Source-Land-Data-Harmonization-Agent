"""Ingestion request results and job summaries."""

from uuid import UUID

from pydantic import BaseModel, Field


class IngestedFileResponse(BaseModel):
    id: UUID
    filename: str
    detected_format: str
    sha256: str
    size_bytes: int
    row_count: int
    columns: list[str]
    metadata: dict[str, object]


class IngestionBatchResponse(BaseModel):
    job_id: UUID
    workspace_id: UUID
    source_id: UUID
    status: str
    total_records: int
    files: list[IngestedFileResponse]


class IngestionJobResponse(BaseModel):
    job_id: UUID
    workspace_id: UUID
    status: str
    summary: dict[str, object] = Field(default_factory=dict)
