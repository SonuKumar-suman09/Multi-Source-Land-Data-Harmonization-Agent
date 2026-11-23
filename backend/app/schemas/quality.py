"""Quality assurance report response."""

from uuid import UUID
from typing import Any

from pydantic import BaseModel


class QualityReportResponse(BaseModel):
    job_id: UUID
    records_checked: int
    valid_records: int
    invalid_records: int
    review_records: int
    conflict_records: int
    critical_errors: int
    warnings: int
    informational_issues: int
    overlapping_pairs: int
    quality_score: float
    retrieved_rules: list[dict[str, Any]]
    already_completed: bool
