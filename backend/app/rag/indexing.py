"""Document chunking and pgvector rule indexing."""

from __future__ import annotations

import re
import hashlib
import uuid
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from langchain_core.embeddings import Embeddings
from sqlalchemy.orm import Session

from app.models.entities import AuditLog, LandDataRule
from app.core.config import settings
from app.rag.embeddings import get_embeddings

MAX_DOCUMENT_BYTES = 1_000_000
CHUNK_CHARACTERS = 1200
CHUNK_OVERLAP = 160


class KnowledgeDocumentError(ValueError):
    """A knowledge document cannot be safely indexed."""


def chunk_document(text: str, *, chunk_size: int = CHUNK_CHARACTERS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    normalized = re.sub(r"\r\n?", "\n", text).strip()
    if not normalized:
        raise KnowledgeDocumentError("Knowledge document is empty")
    if chunk_size < 100 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Chunk size must be at least 100 and overlap must be smaller than chunk size")
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind("\n", start + chunk_size // 2, end)
            if boundary > start:
                end = boundary
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(start + 1, end - overlap)
    return chunks


def decode_document(filename: str, content: bytes) -> str:
    extension = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if extension not in {".txt", ".md", ".json"}:
        raise KnowledgeDocumentError("Supported knowledge documents are UTF-8 TXT, Markdown, or JSON")
    if not content:
        raise KnowledgeDocumentError("Knowledge document is empty")
    if len(content) > MAX_DOCUMENT_BYTES:
        raise KnowledgeDocumentError("Knowledge documents may not exceed 1 MB")
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise KnowledgeDocumentError("Knowledge documents must use UTF-8 encoding") from exc
    if extension == ".json":
        import json

        try:
            decoded = json.dumps(json.loads(decoded), ensure_ascii=False, indent=2)
        except json.JSONDecodeError as exc:
            raise KnowledgeDocumentError("JSON knowledge document is malformed") from exc
    return decoded


def index_document(
    db: Session,
    *,
    workspace_id: UUID,
    user_id: UUID,
    filename: str,
    title: str,
    rule_key: str,
    version: str,
    content: str,
    original_bytes: bytes,
) -> dict[str, Any]:
    chunks = chunk_document(content)
    document_id = uuid.uuid4()
    embeddings: Embeddings = get_embeddings()
    vectors = embeddings.embed_documents(chunks)
    if len(vectors) != len(chunks) or any(len(vector) != settings.embedding_dimensions for vector in vectors):
        raise KnowledgeDocumentError("Embedding provider returned vectors with the wrong dimensions")
    provider_name = "gemini" if embeddings.__class__.__name__ == "GoogleGenerativeAIEmbeddings" else "local"
    safe_name = PurePosixPath(filename.replace("\\", "/")).name
    suffix = PurePosixPath(safe_name).suffix.lower()
    object_key = f"{workspace_id}/{document_id}{suffix}"
    storage_root = Path(__file__).resolve().parents[3] / "data" / "knowledge"
    destination = storage_root.joinpath(*PurePosixPath(object_key).parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        temporary.write_bytes(original_bytes)
        temporary.replace(destination)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise KnowledgeDocumentError("Could not store the original knowledge document") from exc
    source_hash = hashlib.sha256(original_bytes).hexdigest()
    rows = []
    for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True), start=1):
        chunk_key = f"{rule_key}:chunk-{index:03d}"
        rows.append(
            LandDataRule(
                workspace_id=workspace_id,
                rule_key=chunk_key,
                version=version,
                title=title,
                content=chunk,
                source_reference=filename,
                metadata_json={
                    "document_id": str(document_id),
                    "document_rule_key": rule_key,
                    "chunk_index": index,
                    "chunk_count": len(chunks),
                    "embedding_provider": provider_name,
                    "object_key": object_key,
                    "sha256": source_hash,
                },
                embedding=vector,
                active=True,
            )
        )
    db.add_all(rows)
    db.add(
        AuditLog(
            workspace_id=workspace_id,
            actor_id=user_id,
            action="knowledge.document_indexed",
            object_type="knowledge_document",
            object_id=document_id,
            details={"filename": filename, "rule_key": rule_key, "version": version, "chunks": len(chunks), "embedding_provider": provider_name},
        )
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        destination.unlink(missing_ok=True)
        raise
    return {"document_id": document_id, "filename": filename, "title": title, "rule_key": rule_key, "version": version, "chunks": len(chunks), "embedding_provider": provider_name}
