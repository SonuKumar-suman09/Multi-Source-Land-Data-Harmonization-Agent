"""Authenticated document indexing and semantic rule search."""

import logging
import re
from pathlib import PurePosixPath
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.models.entities import LandDataRule, User, WorkspaceMembership
from app.rag.embeddings import EmbeddingConfigurationError
from app.rag.indexing import KnowledgeDocumentError, decode_document, index_document
from app.rag.retrieval import retrieve_rules
from app.schemas.knowledge import (
    KnowledgeDocumentListItem,
    KnowledgeDocumentResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/knowledge", tags=["RAG knowledge base"])
RULE_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,159}$")
MAX_DOCUMENT_BYTES = 1_000_000


def _membership(db: Session, user_id: UUID, requested_workspace_id: UUID | None) -> WorkspaceMembership:
    query = select(WorkspaceMembership).where(WorkspaceMembership.user_id == user_id)
    if requested_workspace_id is not None:
        query = query.where(WorkspaceMembership.workspace_id == requested_workspace_id)
    else:
        query = query.order_by(WorkspaceMembership.created_at)
    membership = db.scalars(query).first()
    if membership is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return membership


@router.post("/documents", response_model=KnowledgeDocumentResponse, status_code=201)
def upload_knowledge_document(
    file: Annotated[UploadFile, File(description="UTF-8 Markdown, TXT, or JSON; 1 MB maximum")],
    title: Annotated[str, Form(min_length=1, max_length=500)],
    rule_key: Annotated[str, Form(min_length=1, max_length=160)],
    version: Annotated[str, Form(min_length=1, max_length=80)] = "1",
    workspace_id: Annotated[UUID | None, Form()] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeDocumentResponse:
    membership = _membership(db, user.id, workspace_id)
    filename = PurePosixPath((file.filename or "").replace("\\", "/")).name
    content_bytes = file.file.read(MAX_DOCUMENT_BYTES + 1)
    if len(content_bytes) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="Knowledge documents may not exceed 1 MB")
    if not RULE_KEY_PATTERN.fullmatch(rule_key):
        raise HTTPException(status_code=422, detail="rule_key must use lowercase letters, digits, dot, underscore, or hyphen")
    try:
        content = decode_document(filename, content_bytes)
        result = index_document(
            db,
            workspace_id=membership.workspace_id,
            user_id=user.id,
            filename=filename,
            title=title.strip(),
            rule_key=rule_key,
            version=version,
            content=content,
            original_bytes=content_bytes,
        )
    except KnowledgeDocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EmbeddingConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A document with this rule key and version is already indexed") from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Knowledge document indexing failed")
        raise HTTPException(status_code=502, detail="Knowledge document indexing failed") from exc
    return KnowledgeDocumentResponse(**result)


@router.get("/documents", response_model=list[KnowledgeDocumentListItem])
def list_knowledge_documents(
    workspace_id: UUID | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[KnowledgeDocumentListItem]:
    membership = _membership(db, user.id, workspace_id)
    rules = db.scalars(
        select(LandDataRule)
        .where(LandDataRule.workspace_id == membership.workspace_id)
        .order_by(LandDataRule.created_at, LandDataRule.id)
    ).all()
    documents: dict[str, dict[str, Any]] = {}
    for rule in rules:
        metadata = rule.metadata_json or {}
        document_id = metadata.get("document_id")
        if not document_id:
            continue
        entry = documents.setdefault(
            document_id,
            {
                "document_id": document_id,
                "filename": rule.source_reference or "",
                "title": rule.title,
                "rule_key": metadata.get("document_rule_key", rule.rule_key),
                "version": rule.version,
                "chunks": int(metadata.get("chunk_count", 1)),
                "embedding_provider": metadata.get("embedding_provider", "unknown"),
                "created_at": rule.created_at.isoformat() if rule.created_at else "",
            },
        )
    return [KnowledgeDocumentListItem(**item) for item in documents.values()]


@router.post("/search", response_model=KnowledgeSearchResponse)
def search_knowledge(
    request: KnowledgeSearchRequest,
    workspace_id: UUID | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeSearchResponse:
    membership = _membership(db, user.id, workspace_id)
    try:
        results = retrieve_rules(db, workspace_id=membership.workspace_id, query=request.query, limit=request.limit)
    except EmbeddingConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Knowledge retrieval failed")
        raise HTTPException(status_code=502, detail="Knowledge search failed") from exc
    return KnowledgeSearchResponse(query=request.query, provider=settings.rag_embedding_provider, results=results)
