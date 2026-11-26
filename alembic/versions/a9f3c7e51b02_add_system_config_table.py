"""add system_config table

Revision ID: a9f3c7e51b02
Revises: 87bff5e2a7ed
Create Date: 2026-08-19

Adds the persistent system configuration table used by the admin
configuration routes (inference, assessment, project, and integration
settings). Matches backend.models.collaboration.SystemConfig.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a9f3c7e51b02"
down_revision: Union[str, Sequence[str], None] = "87bff5e2a7ed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the system_config table (matches the SystemConfig model)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("system_config"):
        return
    op.create_table(
        "system_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value_type", sa.String(length=20), nullable=False),
        sa.Column("string_value", sa.Text(), nullable=True),
        sa.Column("integer_value", sa.Integer(), nullable=True),
        sa.Column("float_value", sa.Float(), nullable=True),
        sa.Column("boolean_value", sa.Integer(), nullable=True),
        sa.Column("json_value", sa.JSON(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # Indexes matching the model's index=True columns
    op.create_index(op.f("ix_system_config_id"), "system_config", ["id"], unique=False)
    op.create_index(op.f("ix_system_config_category"), "system_config", ["category"], unique=False)
    op.create_index(op.f("ix_system_config_key"), "system_config", ["key"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_system_config_key"), table_name="system_config")
    op.drop_index(op.f("ix_system_config_category"), table_name="system_config")
    op.drop_index(op.f("ix_system_config_id"), table_name="system_config")
    op.drop_table("system_config")
