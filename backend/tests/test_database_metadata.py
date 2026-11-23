from geoalchemy2 import Geometry
from pgvector.sqlalchemy import Vector
from sqlalchemy import UniqueConstraint

from app.database.base import Base
from app.models.entities import HarmonizedLandRecord, LandDataRule, RecordProvenance, User


def test_initial_schema_contains_all_core_tables() -> None:
    expected = {
        "users",
        "workspaces",
        "workspace_memberships",
        "data_sources",
        "uploaded_files",
        "processing_jobs",
        "raw_land_records",
        "harmonized_land_records",
        "record_provenance",
        "schema_mappings",
        "validation_results",
        "duplicate_records",
        "agent_executions",
        "workflow_states",
        "audit_logs",
        "land_data_rules",
    }

    assert expected <= set(Base.metadata.tables)


def test_parcel_geometry_is_postgis_wgs84() -> None:
    geometry = HarmonizedLandRecord.__table__.c.geometry.type

    assert isinstance(geometry, Geometry)
    assert geometry.srid == 4326


def test_rule_embedding_dimension_matches_configuration() -> None:
    embedding = LandDataRule.__table__.c.embedding.type

    assert isinstance(embedding, Vector)
    assert embedding.dim == 768


def test_provenance_enforces_one_link_per_raw_canonical_pair() -> None:
    constraints = RecordProvenance.__table__.constraints

    assert any(
        isinstance(constraint, UniqueConstraint)
        and {column.name for column in constraint.columns}
        == {"harmonized_record_id", "raw_record_id"}
        for constraint in constraints
    )


def test_user_email_is_unique() -> None:
    constraints = User.__table__.constraints

    assert any(
        isinstance(constraint, UniqueConstraint)
        and [column.name for column in constraint.columns] == ["email"]
        for constraint in constraints
    )
