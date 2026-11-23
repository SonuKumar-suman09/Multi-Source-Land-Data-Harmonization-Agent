"""LangGraph workflow action and status responses."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class WorkflowResponse(BaseModel):
    job_id: UUID
    status: str
    stage: str
    events: list[dict[str, Any]] = Field(default_factory=list)
    ingestion: dict[str, Any] = Field(default_factory=dict)
    harmonization: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    already_completed: bool = False


class WorkflowStatusResponse(BaseModel):
    job_id: UUID
    stage: str
    state: dict[str, Any] = Field(default_factory=dict)
