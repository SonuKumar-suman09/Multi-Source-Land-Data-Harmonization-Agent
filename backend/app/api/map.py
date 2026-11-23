"""Workspace-scoped GeoJSON features for the parcel map."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.entities import (
    HarmonizedLandRecord,
    RecordStatus,
    User,
    WorkspaceMembership,
)
from app.schemas.map import ParcelFeatureCollection

router = APIRouter(prefix="/map", tags=["GIS map"])


@router.get("/parcels")
def get_parcel_features(
    status: RecordStatus | None = None,
    search: str | None = Query(default=None, max_length=120),
    min_lon: float | None = Query(default=None, ge=-180, le=180),
    min_lat: float | None = Query(default=None, ge=-90, le=90),
    max_lon: float | None = Query(default=None, ge=-180, le=180),
    max_lat: float | None = Query(default=None, ge=-90, le=90),
    limit: int = Query(default=2000, ge=1, le=10000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ParcelFeatureCollection:
    """Return valid stored geometries as a filtered GeoJSON FeatureCollection."""
    bbox_values = (min_lon, min_lat, max_lon, max_lat)
    if any(value is not None for value in bbox_values):
        if any(value is None for value in bbox_values):
            raise HTTPException(status_code=422, detail="Provide all four map bounds")
        if min_lon >= max_lon or min_lat >= max_lat:
            raise HTTPException(status_code=422, detail="Map bounds must have positive width and height")

    workspace_ids = select(WorkspaceMembership.workspace_id).where(
        WorkspaceMembership.user_id == user.id
    )
    query = (
        select(
            HarmonizedLandRecord.id,
            HarmonizedLandRecord.job_id,
            HarmonizedLandRecord.plot_id,
            HarmonizedLandRecord.owner_name,
            HarmonizedLandRecord.area_acres,
            HarmonizedLandRecord.recorded_at,
            HarmonizedLandRecord.status,
            HarmonizedLandRecord.quality_score,
            func.ST_AsGeoJSON(HarmonizedLandRecord.geometry, 6).label("geometry_json"),
        )
        .where(
            HarmonizedLandRecord.workspace_id.in_(workspace_ids),
            HarmonizedLandRecord.geometry.is_not(None),
            func.ST_IsValid(HarmonizedLandRecord.geometry),
        )
        .order_by(HarmonizedLandRecord.plot_id.asc().nullslast(), HarmonizedLandRecord.id)
        .limit(limit)
    )
    if status is not None:
        query = query.where(HarmonizedLandRecord.status == status)
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(
            HarmonizedLandRecord.plot_id.ilike(term)
            | HarmonizedLandRecord.owner_name.ilike(term)
        )
    if all(value is not None for value in bbox_values):
        query = query.where(
            func.ST_Intersects(
                HarmonizedLandRecord.geometry,
                func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326),
            )
        )

    features = []
    for row in db.execute(query):
        features.append(
            {
                "type": "Feature",
                "id": str(row.id),
                "geometry": json.loads(row.geometry_json),
                "properties": {
                    "id": str(row.id),
                    "job_id": str(row.job_id),
                    "plot_id": row.plot_id,
                    "owner_name": row.owner_name,
                    "area_acres": float(row.area_acres) if row.area_acres is not None else None,
                    "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
                    "status": row.status.value,
                    "quality_score": float(row.quality_score) if row.quality_score is not None else None,
                },
            }
        )

    return ParcelFeatureCollection(features=features, count=len(features))
