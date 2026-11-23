"""Report export safety and workspace authorization tests."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.reports import _csv_safe
from app.database.session import SessionLocal
from app.main import app
from app.models.entities import (
    AuditLog,
    ProcessingJob,
    User,
    Workspace,
    WorkspaceMembership,
)

client = TestClient(app)


@pytest.mark.parametrize("value", ["=1+1", "+cmd", "-cmd", "@SUM(A1:A2)", "\tformula", "\rformula"])
def test_csv_export_escapes_spreadsheet_formulas(value: str) -> None:
    assert _csv_safe(value) == "'" + value


def test_csv_export_preserves_safe_values_and_empty_cells() -> None:
    assert _csv_safe("Plot K-101") == "Plot K-101"
    assert _csv_safe(None) == ""


def test_report_downloads_hide_jobs_outside_the_users_workspace() -> None:
    owner_email = f"report-owner-{uuid4().hex}@example.com"
    other_email = f"report-other-{uuid4().hex}@example.com"
    password = "correct-horse-battery-staple"
    workspace_ids: list[UUID] = []
    user_ids: list[UUID] = []
    job_id: UUID | None = None

    try:
        owner = client.post("/api/v1/auth/register", json={"email": owner_email, "password": password})
        if owner.status_code == 201:
            user_ids.append(UUID(owner.json()["user"]["id"]))
        other = client.post("/api/v1/auth/register", json={"email": other_email, "password": password})
        if other.status_code == 201:
            user_ids.append(UUID(other.json()["user"]["id"]))
        assert owner.status_code == 201, owner.text
        assert other.status_code == 201, other.text
        owner_id = UUID(owner.json()["user"]["id"])
        other_id = UUID(other.json()["user"]["id"])
        headers = {"Authorization": f"Bearer {owner.json()['access_token']}"}

        with SessionLocal.begin() as db:
            memberships = db.scalars(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.user_id.in_([owner_id, other_id])
                )
            ).all()
            other_workspace_id = next(item.workspace_id for item in memberships if item.user_id == other_id)
            workspace_ids.extend(item.workspace_id for item in memberships)
            job = ProcessingJob(workspace_id=other_workspace_id, requested_by=other_id)
            db.add(job)
            db.flush()
            job_id = job.id

        assert job_id is not None
        for suffix in ("", "/csv", "/pdf"):
            response = client.get(f"/api/v1/reports/jobs/{job_id}{suffix}", headers=headers)
            assert response.status_code == 404
    finally:
        if workspace_ids or user_ids:
            with SessionLocal.begin() as db:
                if user_ids:
                    workspace_ids.extend(
                        item
                        for item in db.scalars(
                            select(WorkspaceMembership.workspace_id).where(
                                WorkspaceMembership.user_id.in_(user_ids)
                            )
                        ).all()
                        if item not in workspace_ids
                    )
                if workspace_ids:
                    db.execute(delete(AuditLog).where(AuditLog.workspace_id.in_(workspace_ids)))
                    db.execute(delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id.in_(workspace_ids)))
                    db.execute(delete(ProcessingJob).where(ProcessingJob.workspace_id.in_(workspace_ids)))
                    db.execute(delete(Workspace).where(Workspace.id.in_(workspace_ids)))
                if user_ids:
                    db.execute(delete(User).where(User.id.in_(user_ids)))
