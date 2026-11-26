"""add customer_technologies table (S-A-I-L Technology Inventory)

Revision ID: c5d6e7f8a9b0
Revises: c9d0e1f2a3b4
Create Date: 2026-09-07

Creates the customer_technologies table backing the S-A-I-L Technology
Inventory feature. Per-customer structured
technology records with controlled vocabularies (validated in the service
layer; see backend/models/customer_technology.py) and explicit unknown
handling (NULL = unknown, never fabricated).

Idempotent: skips creation when the table already exists.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "customer_technologies" in inspector.get_table_names():
        return

    op.create_table(
        "customer_technologies",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False, index=True),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("vendor", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("version_edition", sa.String(length=255), nullable=True),
        sa.Column("deployment_model", sa.String(length=50), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("footprint", sa.String(length=255), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("lifecycle_state", sa.String(length=50), nullable=True),
        sa.Column("support_state", sa.String(length=50), nullable=True),
        sa.Column("business_criticality", sa.String(length=50), nullable=True),
        sa.Column("source", sa.String(length=255), nullable=True),
        sa.Column("date_observed", sa.Date(), nullable=True),
        sa.Column(
            "verification_state",
            sa.String(length=20),
            nullable=False,
            server_default="unverified",
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "customer_technologies" in inspector.get_table_names():
        op.drop_table("customer_technologies")
