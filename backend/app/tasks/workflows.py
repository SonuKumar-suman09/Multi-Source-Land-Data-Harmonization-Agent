"""Queue submission and execution for checkpointed LangGraph workflows."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from celery.exceptions import CeleryError
from kombu.exceptions import OperationalError as BrokerOperationalError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError as DatabaseOperationalError

from app.agents.workflow import run_land_workflow
from app.core.config import settings
from app.database.session import SessionLocal
from app.models.entities import AgentExecution, AuditLog, JobStatus, ProcessingJob, WorkflowState
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


class WorkflowQueueUnavailable(RuntimeError):
    """Redis could not accept the workflow task."""


@celery_app.task(bind=True, name="land_harmonizer.run_workflow", max_retries=3)
def run_workflow_task(
    self,
    job_id: str,
    workspace_id: str,
    user_id: str,
    execution_id: str,
) -> dict[str, Any]:
    try:
        return run_land_workflow(
            job_id=UUID(job_id),
            workspace_id=UUID(workspace_id),
            user_id=UUID(user_id),
            execution_id=UUID(execution_id),
            resume_running=bool((self.request.delivery_info or {}).get("redelivered")),
        )
    except DatabaseOperationalError as exc:
        retry_number = int(self.request.retries)
        countdown = min(5 * (2**retry_number), 60)
        logger.warning("Retrying workflow task %s after database connectivity error", execution_id)
        raise self.retry(exc=exc, countdown=countdown)


def enqueue_land_workflow(
    *, job_id: UUID, workspace_id: UUID, user_id: UUID, queue_name: str | None = None
) -> dict[str, Any]:
    """Persist a queued execution before publishing it so status survives API restarts."""
    execution_id = uuid.uuid4()
    task_id = str(execution_id)
    thread_id = f"land-harmonization:{job_id}"
    with SessionLocal.begin() as db:
        job = db.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.workspace_id == workspace_id)
            .with_for_update()
        )
        if job is None:
            raise LookupError("Processing job not found")
        workflow = db.scalar(select(WorkflowState).where(WorkflowState.job_id == job_id).with_for_update())
        state = (workflow.state_summary if workflow else {}) or {}
        if state.get("stage") == "completed":
            return {"job_id": str(job_id), "task_id": state.get("task_id"), "stage": "completed", "already_completed": True}
        current_task_id = state.get("task_id")
        if state.get("stage") in {"queued", "running", "ingestion_verified", "harmonization_completed", "quality_completed"}:
            if current_task_id:
                return {"job_id": str(job_id), "task_id": current_task_id, "stage": state["stage"], "already_completed": False}
            raise ValueError("A workflow is already running for this job")
        if job.status not in {JobStatus.MAPPING, JobStatus.AWAITING_REVIEW, JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_ERRORS}:
            raise ValueError(f"Job cannot be queued from status '{job.status.value}'")

        execution = AgentExecution(
            id=execution_id,
            job_id=job_id,
            agent_name="workflow_orchestrator",
            status="queued",
            attempt=1,
            input_summary={"thread_id": thread_id, "queue": queue_name or settings.celery_queue},
        )
        db.add(execution)
        queued_summary = {
            **state,
            "stage": "queued",
            "task_id": task_id,
            "thread_id": thread_id,
            "queued_at": datetime.now(UTC).isoformat(),
            "events": [*state.get("events", []), {"node": "orchestrator", "status": "queued"}],
        }
        if workflow is None:
            workflow = WorkflowState(
                job_id=job_id,
                graph_thread_id=thread_id,
                checkpoint_version="langgraph-postgres-v1",
                state_summary=queued_summary,
            )
            db.add(workflow)
        else:
            workflow.state_summary = queued_summary
        db.add(AuditLog(
            workspace_id=workspace_id,
            actor_id=user_id,
            action="workflow.queued",
            object_type="processing_job",
            object_id=job_id,
            details={"task_id": task_id, "queue": queue_name or settings.celery_queue},
        ))

    try:
        run_workflow_task.apply_async(
            args=[str(job_id), str(workspace_id), str(user_id), task_id],
            task_id=task_id,
            queue=queue_name or settings.celery_queue,
        )
    except (CeleryError, BrokerOperationalError, OSError, DatabaseOperationalError) as exc:
        logger.exception("Could not publish workflow task %s", task_id)
        with SessionLocal.begin() as db:
            execution = db.get(AgentExecution, execution_id)
            if execution:
                execution.status = "failed"
                execution.error_code = "task_publish_failed"
                execution.error_message = "Redis broker could not accept the task"
                execution.finished_at = datetime.now(UTC)
            workflow = db.scalar(select(WorkflowState).where(WorkflowState.job_id == job_id))
            if workflow:
                workflow.state_summary = {**workflow.state_summary, "stage": "failed", "error": "task_publish_failed"}
            db.add(AuditLog(
                workspace_id=workspace_id,
                actor_id=user_id,
                action="workflow.queue_failed",
                object_type="processing_job",
                object_id=job_id,
                details={"task_id": task_id, "error_type": type(exc).__name__},
            ))
        raise WorkflowQueueUnavailable("Redis could not accept the workflow task") from exc
    return {"job_id": str(job_id), "task_id": task_id, "stage": "queued", "already_completed": False}
