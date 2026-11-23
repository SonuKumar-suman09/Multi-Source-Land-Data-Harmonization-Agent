"""Authenticated workspace dashboard metrics from persisted land data."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.entities import (
    DuplicateRecord,
    HarmonizedLandRecord,
    ProcessingJob,
    RawLandRecord,
    RecordStatus,
    UploadedFile,
    User,
    WorkspaceMembership,
)
from app.schemas.dashboard import DashboardSummary, RecentJob

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> DashboardSummary:
    workspace_ids = select(WorkspaceMembership.workspace_id).where(
        WorkspaceMembership.user_id == user.id
    )
    job_scope = select(ProcessingJob.id).where(ProcessingJob.workspace_id.in_(workspace_ids))

    dataset_count = db.scalar(
        select(func.count()).select_from(ProcessingJob).where(
            ProcessingJob.workspace_id.in_(workspace_ids)
        )
    ) or 0
    uploaded_file_count = db.scalar(
        select(func.count()).select_from(UploadedFile).where(
            UploadedFile.workspace_id.in_(workspace_ids)
        )
    ) or 0
    raw_record_count = db.scalar(
        select(func.count()).select_from(RawLandRecord).where(
            RawLandRecord.workspace_id.in_(workspace_ids)
        )
    ) or 0
    harmonized_record_count = db.scalar(
        select(func.count()).select_from(HarmonizedLandRecord).where(
            HarmonizedLandRecord.workspace_id.in_(workspace_ids)
        )
    ) or 0

    status_rows = db.execute(
        select(HarmonizedLandRecord.status, func.count())
        .where(HarmonizedLandRecord.workspace_id.in_(workspace_ids))
        .group_by(HarmonizedLandRecord.status)
    ).all()
    record_counts = {status.value: int(count) for status, count in status_rows}

    duplicate_pair_count = db.scalar(
        select(func.count()).select_from(DuplicateRecord).where(
            DuplicateRecord.job_id.in_(job_scope)
        )
    ) or 0
    average_quality = db.scalar(
        select(func.avg(HarmonizedLandRecord.quality_score)).where(
            HarmonizedLandRecord.workspace_id.in_(workspace_ids),
            HarmonizedLandRecord.quality_score.is_not(None),
        )
    )

    recent_rows = db.scalars(
        select(ProcessingJob)
        .where(ProcessingJob.workspace_id.in_(workspace_ids))
        .order_by(ProcessingJob.created_at.desc())
        .limit(6)
    ).all()
    recent_jobs = [
        RecentJob(
            id=job.id,
            source_name=(job.config or {}).get("source_name", "Land data import"),
            status=job.status.value,
            created_at=job.created_at,
            total_records=int((job.summary or {}).get("total_records", 0)),
            quality_score=(
                float((job.summary or {})["quality_score"])
                if (job.summary or {}).get("quality_score") is not None
                else None
            ),
        )
        for job in recent_rows
    ]

    return DashboardSummary(
        dataset_count=int(dataset_count),
        uploaded_file_count=int(uploaded_file_count),
        raw_record_count=int(raw_record_count),
        harmonized_record_count=int(harmonized_record_count),
        valid_record_count=record_counts.get(RecordStatus.VALID.value, 0),
        invalid_record_count=record_counts.get(RecordStatus.INVALID.value, 0),
        review_record_count=record_counts.get(RecordStatus.NEEDS_REVIEW.value, 0),
        conflict_record_count=record_counts.get(RecordStatus.CONFLICT.value, 0),
        duplicate_pair_count=int(duplicate_pair_count),
        average_quality_score=float(average_quality) if average_quality is not None else None,
        job_status_counts={status.value: int(count) for status, count in db.execute(
            select(ProcessingJob.status, func.count())
            .where(ProcessingJob.workspace_id.in_(workspace_ids))
            .group_by(ProcessingJob.status)
        ).all()},
        recent_jobs=recent_jobs,
        generated_at=datetime.now(UTC),
    )

