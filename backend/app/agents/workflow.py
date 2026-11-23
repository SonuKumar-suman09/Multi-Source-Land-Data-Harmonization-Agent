"""Checkpointed LangGraph coordinator for ingestion, harmonization, and QA."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any, TypedDict
from uuid import UUID

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import SessionLocal
from app.models.entities import (
    AgentExecution,
    AuditLog,
    HarmonizedLandRecord,
    JobStatus,
    ProcessingJob,
    RawLandRecord,
    UploadedFile,
    WorkflowState,
)
from app.services.harmonization import harmonize_job
from app.services.quality_assurance import run_quality_assurance

logger = logging.getLogger(__name__)
CHECKPOINT_VERSION = "langgraph-postgres-v1"
_CHECKPOINTER_SETUP_LOCK = threading.Lock()
_CHECKPOINTER_SETUP_COMPLETE = False


class LandWorkflowState(TypedDict, total=False):
    job_id: str
    workspace_id: str
    user_id: str
    thread_id: str
    task_id: str | None
    stage: str
    ingestion: dict[str, Any]
    harmonization: dict[str, Any]
    quality: dict[str, Any]
    events: list[dict[str, Any]]
    error: str | None


def _thread_id(job_id: UUID) -> str:
    return f"land-harmonization:{job_id}"


def _record_checkpoint_state(state: LandWorkflowState) -> None:
    with SessionLocal.begin() as db:
        workflow = db.scalar(select(WorkflowState).where(WorkflowState.job_id == UUID(state["job_id"])))
        if workflow is None:
            workflow = WorkflowState(
                job_id=UUID(state["job_id"]),
                graph_thread_id=state["thread_id"],
                checkpoint_version=CHECKPOINT_VERSION,
                state_summary={},
            )
            db.add(workflow)
        workflow.checkpoint_version = CHECKPOINT_VERSION
        workflow.state_summary = {
            **(workflow.state_summary or {}),
            "stage": state.get("stage", "unknown"),
            "events": state.get("events", []),
            "ingestion": state.get("ingestion"),
            "harmonization": state.get("harmonization"),
            "quality": state.get("quality"),
            "error": state.get("error"),
            "updated_at": datetime.now(UTC).isoformat(),
        }


def _ingestion_node(state: LandWorkflowState) -> dict[str, Any]:
    with SessionLocal() as db:
        job = db.scalar(
            select(ProcessingJob).where(
                ProcessingJob.id == UUID(state["job_id"]),
                ProcessingJob.workspace_id == UUID(state["workspace_id"]),
            )
        )
        if job is None:
            raise LookupError("Processing job not found")
        has_file = db.scalar(select(UploadedFile.id).where(UploadedFile.job_id == job.id).limit(1))
        has_row = db.scalar(select(RawLandRecord.id).where(RawLandRecord.job_id == job.id).limit(1))
        if has_file is None or has_row is None:
            raise ValueError("The job has no successfully ingested source rows")
        report = {
            "job_id": str(job.id),
            "files": int((job.summary or {}).get("file_count", 0)),
            "raw_records": int((job.summary or {}).get("total_records", 0)),
            "source_name": (job.config or {}).get("source_name"),
            "status": "verified",
        }
    updated = {
        **state,
        "stage": "ingestion_verified",
        "ingestion": report,
        "events": [*state.get("events", []), {"node": "ingestion", "status": "completed"}],
    }
    _record_checkpoint_state(updated)
    return {key: updated[key] for key in ("stage", "ingestion", "events")}


def _harmonization_node(state: LandWorkflowState) -> dict[str, Any]:
    job_id = UUID(state["job_id"])
    workspace_id = UUID(state["workspace_id"])
    user_id = UUID(state["user_id"])
    with SessionLocal() as db:
        existing_count = db.scalar(
            select(HarmonizedLandRecord.id).where(HarmonizedLandRecord.job_id == job_id).limit(1)
        )
        if existing_count:
            job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id))
            result = {
                "job_id": str(job_id),
                **(job.summary or {}),
                "already_harmonized": True,
            }
        else:
            result = harmonize_job(db, job_id=job_id, workspace_id=workspace_id, user_id=user_id)
    updated = {
        **state,
        "stage": "harmonization_completed",
        "harmonization": result,
        "events": [*state.get("events", []), {"node": "harmonization", "status": "completed"}],
    }
    _record_checkpoint_state(updated)
    return {key: updated[key] for key in ("stage", "harmonization", "events")}


def _quality_node(state: LandWorkflowState) -> dict[str, Any]:
    with SessionLocal() as db:
        result = run_quality_assurance(
            db,
            job_id=UUID(state["job_id"]),
            workspace_id=UUID(state["workspace_id"]),
            user_id=UUID(state["user_id"]),
        )
    updated = {
        **state,
        "stage": "quality_completed",
        "quality": result,
        "events": [*state.get("events", []), {"node": "quality_assurance", "status": "completed"}],
    }
    _record_checkpoint_state(updated)
    return {key: updated[key] for key in ("stage", "quality", "events")}


def _finalize_node(state: LandWorkflowState) -> dict[str, Any]:
    updated = {
        **state,
        "stage": "completed",
        "events": [*state.get("events", []), {"node": "orchestrator", "status": "completed"}],
    }
    _record_checkpoint_state(updated)
    return {key: updated[key] for key in ("stage", "events")}


def build_land_workflow(checkpointer: PostgresSaver):
    """Create a retry-aware sequential graph over tested deterministic agents."""
    builder = StateGraph(LandWorkflowState)
    retry = RetryPolicy(max_attempts=3, initial_interval=0.5, retry_on=OperationalError)
    builder.add_node("ingestion", _ingestion_node, retry_policy=retry)
    builder.add_node("harmonization", _harmonization_node, retry_policy=retry)
    builder.add_node("quality_assurance", _quality_node, retry_policy=retry)
    builder.add_node("finalize", _finalize_node)
    builder.add_edge(START, "ingestion")
    builder.add_edge("ingestion", "harmonization")
    builder.add_edge("harmonization", "quality_assurance")
    builder.add_edge("quality_assurance", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


def _plain_postgres_url() -> str:
    url = make_url(settings.database_url)
    if url.drivername == "postgresql+psycopg":
        url = url.set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


def _ensure_checkpointer_setup(checkpointer: PostgresSaver) -> None:
    """Run checkpointer DDL once per process instead of on every workflow call."""
    global _CHECKPOINTER_SETUP_COMPLETE
    if _CHECKPOINTER_SETUP_COMPLETE:
        return
    with _CHECKPOINTER_SETUP_LOCK:
        if not _CHECKPOINTER_SETUP_COMPLETE:
            checkpointer.setup()
            _CHECKPOINTER_SETUP_COMPLETE = True


def run_land_workflow(
    *, job_id: UUID, workspace_id: UUID, user_id: UUID, execution_id: UUID | None = None,
    resume_running: bool = False,
) -> dict[str, Any]:
    """Run the durable job graph and write an audit/execution summary."""
    thread_id = _thread_id(job_id)
    with SessionLocal.begin() as db:
        job = db.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.workspace_id == workspace_id)
            .with_for_update()
        )
        if job is None:
            raise LookupError("Processing job not found")
        workflow = db.scalar(select(WorkflowState).where(WorkflowState.job_id == job_id))
        if workflow and workflow.state_summary.get("stage") == "completed":
            saved = workflow.state_summary
            result = {
                "job_id": str(job_id), "status": "completed",
                "stage": "completed", "events": saved.get("events", []),
                "task_id": saved.get("task_id"),
                "ingestion": saved.get("ingestion", {}),
                "harmonization": saved.get("harmonization", {}),
                "quality": saved.get("quality", {}), "already_completed": True,
            }
            if execution_id is not None:
                execution = db.get(AgentExecution, execution_id)
                if execution:
                    execution.status = "completed"
                    execution.finished_at = datetime.now(UTC)
                    execution.output_summary = result
            return result
        if execution_id is not None:
            execution = db.get(AgentExecution, execution_id, with_for_update=True)
            if execution is None:
                raise LookupError("Workflow execution record not found")
            if execution.status == "running" and not resume_running:
                return {
                    "job_id": str(job_id), "status": "running",
                    "stage": (workflow.state_summary or {}).get("stage", "running"),
                    "task_id": str(execution_id), "already_completed": False,
                }
            if execution.status == "running" and resume_running:
                execution.attempt += 1
            if execution.status == "failed":
                execution.attempt += 1
            execution.status = "running"
            execution.started_at = datetime.now(UTC)
            execution.error_code = None
            execution.error_message = None
        else:
            execution = AgentExecution(
                job_id=job_id, agent_name="workflow_orchestrator", status="running",
                attempt=1, input_summary={"thread_id": thread_id}, started_at=datetime.now(UTC),
            )
            db.add(execution)
            db.flush()
            execution_id = execution.id
        if workflow is None:
            workflow = WorkflowState(
                job_id=job_id, graph_thread_id=thread_id,
                checkpoint_version=CHECKPOINT_VERSION, state_summary={"stage": "queued", "events": []},
            )
            db.add(workflow)
        else:
            workflow.state_summary = {**workflow.state_summary, "stage": "running"}
        db.add(AuditLog(
            workspace_id=workspace_id, actor_id=user_id, action="workflow.started",
            object_type="processing_job", object_id=job_id, details={"thread_id": thread_id},
        ))

    initial_state: LandWorkflowState = {
        "job_id": str(job_id), "workspace_id": str(workspace_id),
        "user_id": str(user_id), "thread_id": thread_id,
        "task_id": str(execution_id) if execution_id is not None else None,
        "stage": "started", "events": [{"node": "orchestrator", "status": "started"}],
    }
    try:
        with PostgresSaver.from_conn_string(_plain_postgres_url()) as checkpointer:
            _ensure_checkpointer_setup(checkpointer)
            graph = build_land_workflow(checkpointer)
            output = graph.invoke(initial_state, {"configurable": {"thread_id": thread_id}})
        result = {
            "job_id": str(job_id), "status": "completed", "stage": output["stage"],
            "task_id": output.get("task_id"),
            "events": output.get("events", []),
            "ingestion": output.get("ingestion", {}),
            "harmonization": output.get("harmonization", {}),
            "quality": output.get("quality", {}), "already_completed": False,
        }
        with SessionLocal.begin() as db:
            execution = db.get(AgentExecution, execution_id)
            execution.status = "completed"
            execution.finished_at = datetime.now(UTC)
            execution.output_summary = result
            workflow = db.scalar(select(WorkflowState).where(WorkflowState.job_id == job_id))
            workflow.state_summary = {**workflow.state_summary, "stage": "completed", "result": result}
            db.add(AuditLog(
                workspace_id=workspace_id, actor_id=user_id, action="workflow.completed",
                object_type="processing_job", object_id=job_id,
                details={"thread_id": thread_id, "quality_score": result["quality"].get("quality_score")},
            ))
        return result
    except Exception as exc:
        logger.exception("Land-data workflow failed for job %s", job_id)
        safe_error = type(exc).__name__
        with SessionLocal.begin() as db:
            execution = db.get(AgentExecution, execution_id)
            execution.status = "failed"
            execution.error_code = safe_error
            execution.error_message = safe_error
            execution.finished_at = datetime.now(UTC)
            workflow = db.scalar(select(WorkflowState).where(WorkflowState.job_id == job_id))
            if workflow:
                workflow.state_summary = {**workflow.state_summary, "stage": "failed", "error": safe_error}
            db.add(AuditLog(
                workspace_id=workspace_id, actor_id=user_id, action="workflow.failed",
                object_type="processing_job", object_id=job_id, details={"error_type": safe_error},
            ))
        raise
