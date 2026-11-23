"""Integration checks for auth routes against the configured local PostgreSQL DB."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.database.session import SessionLocal
from app.main import app
from app.models.entities import AuditLog, User, Workspace, WorkspaceMembership

client = TestClient(app)


def test_auth_register_login_and_protected_profile() -> None:
    email = f"phase4-{uuid4().hex}@example.com"
    password = "correct-horse-battery-staple"
    user_id = None

    try:
        registration = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password},
        )
        assert registration.status_code == 201, registration.text
        registered = registration.json()
        assert registered["user"]["email"] == email
        assert registered["token_type"] == "bearer"
        assert "password_hash" not in registered["user"]
        user_id = registered["user"]["id"]

        duplicate = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password},
        )
        assert duplicate.status_code == 409

        wrong_password = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong-password"},
        )
        assert wrong_password.status_code == 401

        login = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]

        unauthorized = client.get("/api/v1/auth/me")
        assert unauthorized.status_code == 401
        protected_dashboard = client.get("/api/v1/dashboard/summary")
        assert protected_dashboard.status_code == 401
        protected_map = client.get("/api/v1/map/parcels")
        assert protected_map.status_code == 401
        protected_report = client.get(f"/api/v1/reports/jobs/{uuid4()}")
        assert protected_report.status_code == 401

        invalid_token = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer not-a-valid-token"},
        )
        assert invalid_token.status_code == 401

        profile = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert profile.status_code == 200, profile.text
        assert profile.json()["id"] == user_id
        assert profile.json()["role"] == "analyst"

        dashboard = client.get(
            "/api/v1/dashboard/summary",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert dashboard.status_code == 200, dashboard.text
        assert dashboard.json()["dataset_count"] == 0
        assert dashboard.json()["raw_record_count"] == 0
        assert dashboard.json()["recent_jobs"] == []
        parcel_map = client.get(
            "/api/v1/map/parcels",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert parcel_map.status_code == 200, parcel_map.text
        assert parcel_map.json() == {"type": "FeatureCollection", "features": [], "count": 0}
    finally:
        if user_id is not None:
            with SessionLocal.begin() as db:
                workspace_ids = db.scalars(
                    select(WorkspaceMembership.workspace_id).where(
                        WorkspaceMembership.user_id == user_id
                    )
                ).all()
                if workspace_ids:
                    db.execute(delete(AuditLog).where(AuditLog.workspace_id.in_(workspace_ids)))
                    db.execute(
                        delete(WorkspaceMembership).where(
                            WorkspaceMembership.workspace_id.in_(workspace_ids)
                        )
                    )
                    db.execute(delete(Workspace).where(Workspace.id.in_(workspace_ids)))
                db.execute(delete(User).where(User.id == user_id))


def test_health_probes() -> None:
    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").json() == {
        "status": "ready",
        "database": "connected",
        "redis": "connected",
    }
