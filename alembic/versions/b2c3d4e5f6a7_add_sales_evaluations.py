"""Add sales_evaluations table.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6_add_customer_knowledge_table
Create Date: 2026-09-05
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6_add_customer_knowledge_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("sales_evaluations"):
        op.create_table(
            "sales_evaluations",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False, index=True),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("evaluation_name", sa.String(255), nullable=False),
            sa.Column("readiness_overall", sa.Float(), nullable=True),
            sa.Column("readiness_dimensions", sa.JSON(), nullable=True),
            sa.Column("environment_score", sa.Float(), nullable=True),
            sa.Column("environment_factors", sa.JSON(), nullable=True),
            sa.Column("growth_opportunities", sa.JSON(), nullable=True),
            sa.Column("risk_factors", sa.JSON(), nullable=True),
            sa.Column("sales_approach", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        )


def downgrade() -> None:
    op.drop_table("sales_evaluations")
