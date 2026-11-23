"""Harmonization action response."""

from uuid import UUID

from pydantic import BaseModel


class HarmonizationResponse(BaseModel):
    job_id: UUID
    harmonized_records: int
    valid_records: int
    review_records: int
    duplicate_pairs: int
    validation_findings: int
    quality_score: float
