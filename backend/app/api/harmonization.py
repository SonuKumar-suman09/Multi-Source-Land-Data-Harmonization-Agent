"""Authenticated schema review and harmonization endpoints."""

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, create_model
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.models.entities import AuditLog, JobStatus, ProcessingJob, SchemaMapping, UploadedFile, User, WorkspaceMembership
from app.schemas.harmonization import HarmonizationResponse
from app.services.harmonization import ALIASES, harmonize_job, map_columns, mapping_review_complete
import logging

router = APIRouter(prefix="/harmonization", tags=["data harmonization"])
logger = logging.getLogger(__name__)
CANONICAL_FIELDS = sorted(ALIASES)


class MappingDecision(BaseModel):
    uploaded_file_id: UUID
    source_column: str = Field(min_length=1, max_length=255)
    canonical_field: str | None = Field(default=None, max_length=100)


class MappingDecisionsRequest(BaseModel):
    decisions: list[MappingDecision] = Field(min_length=1)


class MappingProposalRequest(BaseModel):
    consent_to_send_headers: bool


def _job_for_user(db: Session, job_id: UUID, user_id: UUID) -> ProcessingJob:
    workspace_ids = select(WorkspaceMembership.workspace_id).where(WorkspaceMembership.user_id == user_id)
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id, ProcessingJob.workspace_id.in_(workspace_ids)))
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    return job


@router.get("/jobs/{job_id}/schema")
def get_schema_review(job_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = _job_for_user(db, job_id, user.id)
    files = db.scalars(select(UploadedFile).where(UploadedFile.job_id == job.id).order_by(UploadedFile.created_at)).all()
    if not files:
        raise HTTPException(status_code=404, detail="No uploaded files found")
    saved = db.scalars(select(SchemaMapping).where(SchemaMapping.job_id == job.id)).all()
    by_key = {(str(item.uploaded_file_id), item.source_column): item for item in saved}
    result = []
    for file in files:
        columns = file.metadata_json.get("columns", [])
        deterministic, ambiguous = map_columns(columns)
        rows = []
        for column in columns:
            entry = by_key.get((str(file.id), column))
            suggested = deterministic.get(column) or ambiguous.get(column)
            rows.append({"source_column": column, "suggested_field": suggested, "canonical_field": entry.canonical_field if entry and entry.status in {"accepted_human", "accepted_deterministic"} else deterministic.get(column), "mapping_status": entry.status if entry else ("review_required" if column in ambiguous else ("suggested" if suggested else "unmapped"))})
        result.append({"uploaded_file_id": str(file.id), "filename": file.original_filename, "columns": rows})
    return {"job_id": str(job.id), "status": job.status.value, "canonical_fields": CANONICAL_FIELDS, "files": result}


@router.post("/jobs/{job_id}/mapping-proposals")
def propose_mappings(job_id: UUID, payload: MappingProposalRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not payload.consent_to_send_headers:
        raise HTTPException(status_code=400, detail="Explicit consent is required before sending column headers to Gemini")
    job = _job_for_user(db, job_id, user.id)
    files = db.scalars(select(UploadedFile).where(UploadedFile.job_id == job.id)).all()
    headers = [{"file_index": index, "columns": item.metadata_json.get("columns", [])} for index, item in enumerate(files)]
    key = settings.gemini_api_key.get_secret_value().strip() if settings.gemini_api_key else ""
    if not key:
        raise HTTPException(status_code=503, detail="Gemini is not configured. Set GEMINI_API_KEY, or choose mappings manually.")
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        suggestion = create_model("HeaderMappingSuggestion", file_index=(int, ...), source_column=(str, ...), canonical_field=(str, ...), confidence=(float, ...), reason=(str, ...))
        response_model = create_model("HeaderMappingSuggestions", mappings=(list[suggestion], ...))
        llm = ChatGoogleGenerativeAI(model=settings.gemini_chat_model, google_api_key=key, temperature=0)
        structured = llm.with_structured_output(response_model, method="json_schema")
        prompt = (
            "Map only source column headers to canonical land-data fields. Return one mapping per header. "
            "Use canonical_field from this list: " + ", ".join(CANONICAL_FIELDS) + ". "
            "If uncertain, set canonical_field to unmapped and confidence to 0. "
            "Input contains header names only; do not infer values or invent records. Return the original file_index and source_column. Headers: " + str(headers)
        )
        output = structured.invoke(prompt)
        suggestions = [item.model_dump() for item in output.mappings]
        allowed = set(CANONICAL_FIELDS) | {"unmapped"}
        for item in suggestions:
            index = item.get("file_index")
            if (
                item.get("canonical_field") not in allowed
                or not isinstance(index, int)
                or index < 0
                or index >= len(headers)
                or item.get("source_column") not in headers[index]["columns"]
                or not 0 <= float(item.get("confidence", -1)) <= 1
            ):
                raise ValueError("Gemini returned a mapping outside the uploaded header set")
        return {"job_id": str(job.id), "model": settings.gemini_chat_model, "scope": "column headers only; no cell values or owner names", "mappings": suggestions}
    except Exception as exc:
        db.rollback()
        logger.exception("Gemini schema proposal failed for job %s", job.id)
        raise HTTPException(status_code=502, detail="Gemini could not suggest mappings. Continue with manual mapping.") from exc


@router.put("/jobs/{job_id}/mapping-decisions")
def save_mapping_decisions(job_id: UUID, payload: MappingDecisionsRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = _job_for_user(db, job_id, user.id)
    if job.status not in {JobStatus.QUEUED, JobStatus.MAPPING, JobStatus.AWAITING_REVIEW}:
        raise HTTPException(status_code=409, detail="Mapping decisions can only be changed before processing starts")
    files = db.scalars(select(UploadedFile).where(UploadedFile.job_id == job.id)).all()
    expected = {(file.id, column) for file in files for column in file.metadata_json.get("columns", [])}
    actual = [(item.uploaded_file_id, item.source_column) for item in payload.decisions]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise HTTPException(status_code=422, detail="Provide exactly one mapping decision for every column in every uploaded file")
    file_by_id = {file.id: file for file in files}
    per_file_targets: set[tuple[UUID, str]] = set()
    for decision in payload.decisions:
        field = decision.canonical_field
        if field is not None and field not in CANONICAL_FIELDS:
            raise HTTPException(status_code=422, detail=f"Unknown canonical field: {field}")
        if field is not None:
            key = (decision.uploaded_file_id, field)
            if key in per_file_targets:
                raise HTTPException(status_code=422, detail=f"Only one source column per file may map to {field}")
            per_file_targets.add(key)
    saved = db.scalars(select(SchemaMapping).where(SchemaMapping.job_id == job.id)).all()
    existing = {(item.uploaded_file_id, item.source_column): item for item in saved}
    for decision in payload.decisions:
        file = file_by_id[decision.uploaded_file_id]
        canonical = decision.canonical_field or "unmapped"
        mapping = existing.get((file.id, decision.source_column))
        deterministic, _ = map_columns(file.metadata_json.get("columns", []))
        is_deterministic = deterministic.get(decision.source_column) == decision.canonical_field
        values = dict(job_id=job.id, source_id=file.source_id, uploaded_file_id=file.id, source_column=decision.source_column, canonical_field=canonical, confidence=Decimal("1.000") if is_deterministic else None, evidence={"method": "deterministic_alias" if is_deterministic else "human_review"}, status="accepted_deterministic" if is_deterministic else ("accepted_human" if decision.canonical_field else "rejected"), decided_by=user.id, decided_at=func.now())
        if mapping:
            for name, value in values.items():
                setattr(mapping, name, value)
        else:
            db.add(SchemaMapping(**values))
    db.add(AuditLog(workspace_id=job.workspace_id, actor_id=user.id, action="schema.mapping_reviewed", object_type="processing_job", object_id=job.id, details={"column_count": len(actual)}))
    db.commit()
    return {"job_id": str(job.id), "saved_columns": len(actual), "status": "reviewed"}


@router.post("/jobs/{job_id}/run", response_model=HarmonizationResponse)
def run_harmonization(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HarmonizationResponse:
    job = _job_for_user(db, job_id, user.id)
    if not mapping_review_complete(db, job.id):
        raise HTTPException(status_code=409, detail="Review and save every source-column mapping before processing")
    try:
        result = harmonize_job(db, job_id=job.id, workspace_id=job.workspace_id, user_id=user.id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return HarmonizationResponse(**result)
