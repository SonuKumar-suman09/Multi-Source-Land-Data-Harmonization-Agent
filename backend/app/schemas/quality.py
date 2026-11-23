"""Quality assurance report response."""

from uuid import UUID

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
    already_completed: bool
