"""add readiness insights

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("readiness_insights"):
        return
    op.create_table(
        "readiness_insights",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("insight_data", sa.JSON(), nullable=False),
        sa.Column("data_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("generated_by", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id"),
    )
    op.create_index(op.f("ix_readiness_insights_id"), "readiness_insights", ["id"], unique=False)
    op.create_index(op.f("ix_readiness_insights_customer_id"), "readiness_insights", ["customer_id"], unique=True)
    op.create_index(op.f("ix_readiness_insights_data_fingerprint"), "readiness_insights", ["data_fingerprint"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_readiness_insights_data_fingerprint"), table_name="readiness_insights")
    op.drop_index(op.f("ix_readiness_insights_customer_id"), table_name="readiness_insights")
    op.drop_index(op.f("ix_readiness_insights_id"), table_name="readiness_insights")
    op.drop_table("readiness_insights")
