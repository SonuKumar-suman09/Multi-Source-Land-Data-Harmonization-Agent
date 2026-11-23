"""Add editable display names to user profiles.

Revision ID: 0002_user_display_name
Revises: 0001_initial_schema
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_user_display_name"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "display_name")
