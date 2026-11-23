"""Password hashing and signed access-token helpers."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

password_hash = PasswordHash.recommended()
JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def create_access_token(user_id: UUID) -> tuple[str, int]:
    if len(settings.jwt_secret_key) < 32 or settings.jwt_secret_key.startswith("replace_"):
        raise RuntimeError(
            "JWT_SECRET_KEY is not configured. Set a random secret of at least 32 characters in .env."
        )

    lifetime_seconds = settings.jwt_access_token_minutes * 60
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "jti": str(uuid4()),
        "iat": now,
        "exp": now + timedelta(seconds=lifetime_seconds),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=JWT_ALGORITHM), lifetime_seconds


def decode_access_token(token: str) -> tuple[UUID, UUID, datetime]:
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[JWT_ALGORITHM])
    subject = payload.get("sub")
    token_id = payload.get("jti")
    expires_at = payload.get("exp")
    if not isinstance(subject, str) or not isinstance(token_id, str) or not isinstance(expires_at, (int, float)):
        raise jwt.InvalidTokenError("Token claims are incomplete")
    return UUID(subject), UUID(token_id), datetime.fromtimestamp(expires_at, UTC)
