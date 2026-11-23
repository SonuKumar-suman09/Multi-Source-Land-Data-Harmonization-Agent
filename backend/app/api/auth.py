"""Account registration and JWT login endpoints."""

import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.entities import AuditLog, User, UserRole, Workspace, WorkspaceMembership
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["authentication"])


def _issue_token(user: User) -> TokenResponse:
    token, expires_in = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email = str(payload.email).strip().lower()
    exists = db.scalar(select(User.id).where(User.email == email))
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")

    user = User(email=email, password_hash=hash_password(payload.password), role=UserRole.ANALYST)
    db.add(user)
    db.flush()

    workspace_id = uuid.uuid4()
    local_part = email.split("@", maxsplit=1)[0]
    safe_prefix = re.sub(r"[^a-z0-9]+", "-", local_part.lower()).strip("-")[:40] or "analyst"
    workspace = Workspace(
        id=workspace_id,
        name=f"{local_part}'s workspace",
        slug=f"{safe_prefix}-{workspace_id.hex[:12]}",
    )
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMembership(workspace_id=workspace_id, user_id=user.id, role=UserRole.ADMIN))
    db.add(
        AuditLog(
            workspace_id=workspace_id,
            actor_id=user.id,
            action="user.registered",
            object_type="user",
            object_id=user.id,
            details={"email": email},
        )
    )
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == "uq_users_email":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists",
            ) from None
        logger.exception("Account registration violated a database integrity constraint")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Account registration could not be completed",
        ) from exc
    except Exception:
        db.rollback()
        logger.exception("Account registration transaction failed")
        raise
    return _issue_token(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email = str(payload.email).strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is inactive")
    return _issue_token(user)


@router.get("/me", response_model=UserResponse)
def read_current_user(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(user)
