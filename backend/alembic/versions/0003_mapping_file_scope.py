"""Scope mapping decisions to the uploaded file they describe.

Revision ID: 0003_mapping_file_scope
Revises: 0002_user_display_name
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_mapping_file_scope"
down_revision = "0002_user_display_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "schema_mappings",
        sa.Column("uploaded_file_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_schema_mappings_uploaded_file_id",
        "schema_mappings",
        "uploaded_files",
        ["uploaded_file_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_schema_mappings_uploaded_file_id", "schema_mappings", ["uploaded_file_id"])


def downgrade() -> None:
    op.drop_index("ix_schema_mappings_uploaded_file_id", table_name="schema_mappings")
    op.drop_constraint("fk_schema_mappings_uploaded_file_id", "schema_mappings", type_="foreignkey")
    op.drop_column("schema_mappings", "uploaded_file_id")
