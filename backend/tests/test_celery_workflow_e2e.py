"""Optional end-to-end check; run with a local Redis broker and Celery worker."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.database.session import SessionLocal
from app.main import app
from app.models.entities import (
    AgentExecution,
    AuditLog,
    DataSource,
    ProcessingJob,
    User,
    WorkflowState,
    Workspace,
    WorkspaceMembership,
)
from app.services.ingestion import _storage_root

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_CELERY_E2E") != "1",
    reason="Set RUN_CELERY_E2E=1 and start Redis plus a Celery worker to run this test.",
)

client = TestClient(app)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_enqueued_job_finishes_in_celery_worker() -> None:
    email = f"phase10-{uuid4().hex}@example.com"
    password = "correct-horse-battery-staple"
    user_id: UUID | None = None
    workspace_id: UUID | None = None
    job_id: UUID | None = None

    try:
        registration = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password},
        )
        assert registration.status_code == 201, registration.text
        user_id = UUID(registration.json()["user"]["id"])
        token = registration.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        with SessionLocal() as db:
            workspace_id = db.scalar(
                select(WorkspaceMembership.workspace_id).where(
                    WorkspaceMembership.user_id == user_id
                )
            )
        assert workspace_id is not None

        fixture = PROJECT_ROOT / "data" / "sample" / "source_a.csv"
        upload = client.post(
            "/api/v1/ingestion/uploads",
            headers=headers,
            data={"source_name": "Phase 10 synthetic worker check"},
            files=[("files", (fixture.name, fixture.read_bytes(), "text/csv"))],
        )
        assert upload.status_code == 201, upload.text
        job_id = UUID(upload.json()["job_id"])

        queued = client.post(f"/api/v1/workflows/jobs/{job_id}/enqueue", headers=headers)
        assert queued.status_code == 202, queued.text
        task_id = queued.json()["task_id"]
        assert queued.json()["stage"] == "queued"
        assert task_id

        deadline = time.monotonic() + 90
        current_stage = "queued"
        while time.monotonic() < deadline:
            status = client.get(f"/api/v1/workflows/jobs/{job_id}", headers=headers)
            assert status.status_code == 200, status.text
            current_stage = status.json()["stage"]
            if current_stage in {"completed", "failed"}:
                break
            time.sleep(0.5)

        assert current_stage == "completed", f"Celery workflow ended in stage {current_stage!r}"
        with SessionLocal() as db:
            execution = db.get(AgentExecution, UUID(task_id))
            assert execution is not None
            assert execution.status == "completed"

        repeated = client.post(f"/api/v1/workflows/jobs/{job_id}/enqueue", headers=headers)
        assert repeated.status_code == 202, repeated.text
        assert repeated.json()["task_id"] == task_id
        assert repeated.json()["stage"] == "completed"
        assert repeated.json()["already_completed"] is True
    finally:
        if user_id is not None and workspace_id is not None:
            with SessionLocal.begin() as db:
                db.execute(delete(AuditLog).where(AuditLog.workspace_id == workspace_id))
                if job_id is not None:
                    db.execute(delete(WorkflowState).where(WorkflowState.job_id == job_id))
                    db.execute(delete(AgentExecution).where(AgentExecution.job_id == job_id))
                    db.execute(delete(ProcessingJob).where(ProcessingJob.id == job_id))
                db.execute(delete(DataSource).where(DataSource.workspace_id == workspace_id))
                db.execute(
                    delete(WorkspaceMembership).where(
                        WorkspaceMembership.workspace_id == workspace_id
                    )
                )
                db.execute(delete(Workspace).where(Workspace.id == workspace_id))
                db.execute(delete(User).where(User.id == user_id))
            shutil.rmtree(_storage_root() / str(workspace_id), ignore_errors=True)
