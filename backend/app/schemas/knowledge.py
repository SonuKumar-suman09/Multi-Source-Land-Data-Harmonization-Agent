"""Knowledge base document and retrieval API schemas."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class KnowledgeDocumentResponse(BaseModel):
    document_id: UUID
    filename: str
    title: str
    rule_key: str
    version: str
    chunks: int
    embedding_provider: str


class KnowledgeDocumentListItem(BaseModel):
    document_id: UUID
    filename: str
    title: str
    rule_key: str
    version: str
    chunks: int
    embedding_provider: str
    created_at: str


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2000)
    limit: int = Field(default=5, ge=1, le=20)


class KnowledgeSearchResult(BaseModel):
    id: UUID
    rule_key: str
    document_rule_key: str
    title: str
    content: str
    source_reference: str | None
    version: str
    similarity: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchResponse(BaseModel):
    query: str
    provider: str
    results: list[KnowledgeSearchResult]
