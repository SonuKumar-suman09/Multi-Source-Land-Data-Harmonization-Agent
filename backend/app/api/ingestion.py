"""Authenticated dataset upload and ingestion endpoints."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.models.entities import ProcessingJob, User, WorkspaceMembership
from app.schemas.ingestion import (
    IngestedFileResponse,
    IngestionBatchResponse,
    IngestionJobResponse,
)
from app.services.ingestion import (
    DuplicateUpload,
    IngestionError,
    UploadPayload,
    UploadTooLarge,
    UnsupportedFileType,
    ingest_files,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ingestion", tags=["data ingestion"])


def _get_membership(
    db: Session,
    user_id: UUID,
    requested_workspace_id: UUID | None,
) -> WorkspaceMembership:
    query = select(WorkspaceMembership).where(WorkspaceMembership.user_id == user_id)
    if requested_workspace_id is not None:
        query = query.where(WorkspaceMembership.workspace_id == requested_workspace_id)
    else:
        query = query.order_by(WorkspaceMembership.created_at)
    membership = db.scalars(query).first()
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return membership


@router.post("/uploads", response_model=IngestionBatchResponse, status_code=status.HTTP_201_CREATED)
def upload_datasets(
    files: Annotated[list[UploadFile], File(description="CSV, Excel, JSON, GeoJSON, or zipped Shapefile")],
    source_name: Annotated[str, Form(min_length=1, max_length=200)],
    jurisdiction: Annotated[str | None, Form(max_length=200)] = None,
    default_crs: Annotated[str | None, Form(max_length=80)] = None,
    workspace_id: Annotated[UUID | None, Form()] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IngestionBatchResponse:
    membership = _get_membership(db, user.id, workspace_id)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    payloads: list[UploadPayload] = []
    total_bytes = 0

    if not files:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Upload at least one file")
    for upload in files:
        remaining = max_bytes - total_bytes
        if remaining <= 0:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Total upload size may not exceed {settings.max_upload_mb} MB",
            )
        content = upload.file.read(remaining + 1)
        total_bytes += len(content)
        if len(content) > remaining:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Total upload size may not exceed {settings.max_upload_mb} MB",
            )
        payloads.append(
            UploadPayload(
                filename=upload.filename or "",
                media_type=upload.content_type,
                content=content,
            )
        )

    try:
        result = ingest_files(
            db,
            workspace_id=membership.workspace_id,
            user_id=user.id,
            source_name=source_name,
            jurisdiction=jurisdiction,
            default_crs=default_crs,
            files=payloads,
        )
    except DuplicateUpload as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except UploadTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from exc
    except UnsupportedFileType as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc
    except IngestionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint_name == "uq_uploaded_file_workspace_sha256":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A file with identical content was uploaded concurrently",
            ) from None
        logger.exception("Unexpected database integrity error during ingestion")
        raise HTTPException(status_code=500, detail="Dataset ingestion could not be completed") from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Dataset ingestion failed")
        raise HTTPException(status_code=500, detail="Dataset ingestion could not be completed") from exc

    return IngestionBatchResponse(
        job_id=result.job_id,
        workspace_id=result.workspace_id,
        source_id=result.source_id,
        status=result.status,
        total_records=result.total_records,
        files=[IngestedFileResponse(**item.__dict__) for item in result.files],
    )


@router.get("/jobs/{job_id}", response_model=IngestionJobResponse)
def get_ingestion_job(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IngestionJobResponse:
    workspace_ids = select(WorkspaceMembership.workspace_id).where(
        WorkspaceMembership.user_id == user.id
    )
    job = db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.workspace_id.in_(workspace_ids),
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion job not found")
    return IngestionJobResponse(
        job_id=job.id,
        workspace_id=job.workspace_id,
        status=job.status.value,
        summary=job.summary or {},
    )
