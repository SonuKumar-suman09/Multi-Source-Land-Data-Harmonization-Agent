"""Authenticated endpoint for running deterministic harmonization."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.entities import ProcessingJob, User, WorkspaceMembership
from app.schemas.harmonization import HarmonizationResponse
from app.services.harmonization import harmonize_job

router = APIRouter(prefix="/harmonization", tags=["data harmonization"])


@router.post("/jobs/{job_id}/run", response_model=HarmonizationResponse)
def run_harmonization(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HarmonizationResponse:
    workspace_ids = select(WorkspaceMembership.workspace_id).where(WorkspaceMembership.user_id == user.id)
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id, ProcessingJob.workspace_id.in_(workspace_ids)))
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processing job not found")
    try:
        result = harmonize_job(db, job_id=job.id, workspace_id=job.workspace_id, user_id=user.id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return HarmonizationResponse(**result)
