"""Workspace dashboard aggregates backed by persisted project records."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RecentJob(BaseModel):
    id: UUID
    source_name: str
    status: str
    created_at: datetime
    total_records: int = 0
    quality_score: float | None = None


class DashboardSummary(BaseModel):
    dataset_count: int
    uploaded_file_count: int
    raw_record_count: int
    harmonized_record_count: int
    valid_record_count: int
    invalid_record_count: int
    review_record_count: int
    conflict_record_count: int
    duplicate_pair_count: int
    average_quality_score: float | None = None
    job_status_counts: dict[str, int] = Field(default_factory=dict)
    recent_jobs: list[RecentJob] = Field(default_factory=list)
    generated_at: datetime

