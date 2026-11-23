"""Validated GeoJSON response models for the parcel map API."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.models.entities import RecordStatus


class ParcelMapProperties(BaseModel):
    id: UUID
    job_id: UUID
    plot_id: str | None
    owner_name: str | None
    area_acres: float | None
    recorded_at: str | None
    status: RecordStatus
    quality_score: float | None


class ParcelMapFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: UUID
    geometry: dict[str, Any]
    properties: ParcelMapProperties


class ParcelFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[ParcelMapFeature]
    count: int

