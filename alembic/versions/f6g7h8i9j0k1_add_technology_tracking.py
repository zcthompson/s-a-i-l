"""add technology tracking fields to use cases

Revision ID: f6g7h8i9j0k1
Revises: a1b2c3d4e5f6
Create Date: 2026-09-05

Adds the technology tracking columns to the use_cases table. The matching
customers.tech_profile column is added by d7e8f9a0b1c2 (which also re-ensures
these use_cases columns for databases that missed them).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6g7h8i9j0k1"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── use_cases table: add technology tracking columns ─────────────────────
    ucols = {r["name"] for r in inspector.get_columns("use_cases")}
    if "tech_stack" not in ucols:
        op.add_column(
            "use_cases",
            sa.Column("tech_stack", sa.JSON(), nullable=True,
                       comment="Structured technology stack information"),
        )
    if "devices" not in ucols:
        op.add_column(
            "use_cases",
            sa.Column("devices", sa.JSON(), nullable=True,
                       comment="Device inventory and association data"),
        )
    if "software" not in ucols:
        op.add_column(
            "use_cases",
            sa.Column("software", sa.JSON(), nullable=True,
                       comment="Software licenses and tools tracking"),
        )
    if "vendor" not in ucols:
        op.add_column(
            "use_cases",
            sa.Column("vendor", sa.String(length=255), nullable=True,
                       comment="Vendor or partner name"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Remove columns from use_cases (reverse order)
    ucols = {r["name"] for r in inspector.get_columns("use_cases")}
    for col in ["vendor", "software", "devices", "tech_stack"]:
        if col in ucols:
            op.drop_column("use_cases", col)
