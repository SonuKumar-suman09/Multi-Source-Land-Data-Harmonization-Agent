"""Authenticated endpoint for canonical land-record quality checks."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.entities import ProcessingJob, User, WorkspaceMembership
from app.schemas.quality import QualityReportResponse
from app.services.quality_assurance import run_quality_assurance

router = APIRouter(prefix="/quality", tags=["data quality"])


@router.post("/jobs/{job_id}/run", response_model=QualityReportResponse)
def run_job_quality_assurance(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QualityReportResponse:
    workspace_ids = select(WorkspaceMembership.workspace_id).where(WorkspaceMembership.user_id == user.id)
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id, ProcessingJob.workspace_id.in_(workspace_ids)))
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    try:
        result = run_quality_assurance(db, job_id=job.id, workspace_id=job.workspace_id, user_id=user.id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return QualityReportResponse(**result)
