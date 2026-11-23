"""Authenticated API for durable job orchestration."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.workflow import run_land_workflow
from app.api.deps import get_current_user, get_db
from app.models.entities import ProcessingJob, User, WorkflowState, WorkspaceMembership
from app.schemas.workflow import WorkflowResponse, WorkflowStatusResponse
from app.tasks.workflows import WorkflowQueueUnavailable, enqueue_land_workflow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workflows", tags=["agent workflows"])


def _workspace_job(db: Session, job_id: UUID, user_id: UUID) -> ProcessingJob:
    workspace_ids = select(WorkspaceMembership.workspace_id).where(WorkspaceMembership.user_id == user_id)
    job = db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.workspace_id.in_(workspace_ids),
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    return job


@router.post("/jobs/{job_id}/run", response_model=WorkflowResponse)
def run_workflow(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowResponse:
    job = _workspace_job(db, job_id, user.id)
    job_workspace_id = job.workspace_id
    actor_id = user.id
    # The request session's read transaction must not block LangGraph's first-time
    # PostgresSaver concurrent-index setup on the same database.
    db.rollback()
    try:
        result = run_land_workflow(job_id=job_id, workspace_id=job_workspace_id, user_id=actor_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Workflow execution failed for job %s", job_id)
        raise HTTPException(status_code=500, detail="Workflow execution failed; see agent execution history") from exc
    return WorkflowResponse(**result)


@router.post("/jobs/{job_id}/enqueue", response_model=WorkflowResponse, status_code=202)
def enqueue_workflow(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowResponse:
    job = _workspace_job(db, job_id, user.id)
    workspace_id = job.workspace_id
    actor_id = user.id
    db.rollback()
    try:
        result = enqueue_land_workflow(job_id=job_id, workspace_id=workspace_id, user_id=actor_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorkflowQueueUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return WorkflowResponse(
        job_id=job_id,
        status=result.get("stage", "queued"),
        stage=result.get("stage", "queued"),
        task_id=result.get("task_id"),
        already_completed=result.get("already_completed", False),
    )


@router.get("/jobs/{job_id}", response_model=WorkflowStatusResponse)
def get_workflow_status(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowStatusResponse:
    _workspace_job(db, job_id, user.id)
    workflow = db.scalar(select(WorkflowState).where(WorkflowState.job_id == job_id))
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow has not been started")
    state: dict[str, Any] = workflow.state_summary or {}
    return WorkflowStatusResponse(job_id=job_id, stage=state.get("stage", "unknown"), state=state)
