"""add customer environment knowledge base table

Revision ID: a1b2c3d4e5f6_add_customer_knowledge_table
Revises: d5e6f7a8b9c0
Create Date: 2026-09-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6_add_customer_knowledge_table"
down_revision: Union[str, None] = "f6g7h8i9j0k1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("customer_knowledge"):
        return
    op.create_table(
        "customer_knowledge",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False, index=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("knowledge_type", sa.String(50), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_data", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(), nullable=True),
        sa.Column("ingestion_status", sa.String(50), nullable=True),
        sa.Column("classification", sa.String(50), nullable=True),
        sa.Column("category", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    # Table was created directly in DB; safe to drop if it exists
    op.drop_table("customer_knowledge")
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    ccols = {r["name"] for r in inspector.get_columns("customers")}
    if "tech_profile" in ccols:
        op.drop_column("customers", "tech_profile")
