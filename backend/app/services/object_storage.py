"""Storage adapter for immutable original uploads (local disk or MinIO)."""

from __future__ import annotations

import io
import logging
from pathlib import Path, PurePosixPath

from minio import Minio

from app.core.config import settings

logger = logging.getLogger(__name__)


def local_storage_root() -> Path:
    project_root = Path(__file__).resolve().parents[3]
    configured = Path(settings.upload_dir)
    return configured if configured.is_absolute() else project_root / configured


def _safe_object_key(object_key: str) -> str:
    path = PurePosixPath(object_key)
    if "\\" in object_key or path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Unsafe object key")
    return path.as_posix()


def _minio_client() -> Minio:
    access_key = settings.minio_access_key.get_secret_value() if settings.minio_access_key else ""
    secret = settings.minio_secret_key.get_secret_value() if settings.minio_secret_key else ""
    if not settings.minio_endpoint or not access_key or not secret:
        raise RuntimeError("MinIO storage needs MINIO_ENDPOINT, MINIO_ACCESS_KEY, and MINIO_SECRET_KEY")
    return Minio(
        settings.minio_endpoint,
        access_key=access_key,
        secret_key=secret,
        secure=settings.minio_secure,
    )


def store_original(object_key: str, content: bytes, content_type: str | None = None) -> Path | None:
    """Store exact source bytes and return a disk path only for local storage."""
    safe_key = _safe_object_key(object_key)
    if settings.storage_backend == "local":
        destination = local_storage_root().joinpath(*PurePosixPath(safe_key).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            temporary.write_bytes(content)
            temporary.replace(destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return destination

    client = _minio_client()
    bucket = settings.minio_bucket
    if not client.bucket_exists(bucket):
        try:
            client.make_bucket(bucket)
        except Exception:
            # Another API worker may have created the bucket concurrently.
            if not client.bucket_exists(bucket):
                raise
    client.put_object(
        bucket,
        safe_key,
        io.BytesIO(content),
        len(content),
        content_type=content_type or "application/octet-stream",
    )
    return None


def delete_original(object_key: str) -> None:
    """Remove an object written by a batch whose database transaction failed."""
    safe_key = _safe_object_key(object_key)
    if settings.storage_backend == "local":
        local_storage_root().joinpath(*PurePosixPath(safe_key).parts).unlink(missing_ok=True)
        return
    _minio_client().remove_object(settings.minio_bucket, safe_key)
