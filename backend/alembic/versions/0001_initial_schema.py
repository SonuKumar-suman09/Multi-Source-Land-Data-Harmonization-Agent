"""Create the first tenant, ingestion, lineage, QA, and RAG schema.

Revision ID: 0001_initial_schema
Revises:
"""

from alembic import op

from app.database.base import Base
import app.models.entities  # noqa: F401 - register models for the baseline schema

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # This is the initial local bootstrap only. Once shared, this revision is immutable;
    # follow-up changes must use explicit Alembic operations in new revisions.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=False)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=False)
