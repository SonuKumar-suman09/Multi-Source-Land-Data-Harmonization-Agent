"""Workspace-scoped semantic retrieval from PostgreSQL pgvector."""

from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.entities import LandDataRule
from app.core.config import settings
from app.rag.embeddings import get_embeddings


def retrieve_rules(db: Session, *, workspace_id: UUID, query: str, limit: int = 5) -> list[dict[str, Any]]:
    vector = get_embeddings().embed_query(query)
    if len(vector) != settings.embedding_dimensions:
        raise ValueError("Embedding provider returned a query vector with the wrong dimensions")
    distance = LandDataRule.embedding.cosine_distance(vector).label("distance")
    rows = db.execute(
        select(LandDataRule, distance)
        .where(
            LandDataRule.active.is_(True),
            LandDataRule.embedding.is_not(None),
            or_(LandDataRule.workspace_id == workspace_id, LandDataRule.workspace_id.is_(None)),
        )
        .order_by(distance)
        .limit(max(1, min(limit, 20)))
    ).all()
    return [
        {
            "id": rule.id,
            "rule_key": rule.rule_key,
            "document_rule_key": (rule.metadata_json or {}).get("document_rule_key", rule.rule_key),
            "title": rule.title,
            "content": rule.content,
            "source_reference": rule.source_reference,
            "version": rule.version,
            "similarity": round(1.0 - float(distance_value), 6),
            "metadata": rule.metadata_json or {},
        }
        for rule, distance_value in rows
    ]
