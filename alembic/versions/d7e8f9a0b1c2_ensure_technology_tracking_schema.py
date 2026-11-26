"""ensure technology tracking schema is complete and consistent

Revision ID: d7e8f9a0b1c2
Revises: d5e6f7a8b9c0
Create Date: 2026-09-06

Completes the technology tracking schema for databases that missed earlier
tech-tracking migrations (dev databases that were stamped ahead of their
actual schema). Idempotent: every column is added only if absent, so this is
safe to apply to both consistent and diverged databases. Adds:
  - customers.tech_profile (JSON) — informational technology landscape
    (does NOT participate in CustomerUser authorization/visibility/filtering)
  - use_cases.tech_stack / devices / software (JSON) and use_cases.vendor
    (VARCHAR 255) — re-ensured for databases that lack them
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── customers.tech_profile ───────────────────────────────────────────────
    ccols = {r["name"] for r in inspector.get_columns("customers")}
    if "tech_profile" not in ccols:
        op.add_column(
            "customers",
            sa.Column("tech_profile", sa.JSON(), nullable=True,
                      comment="Customer technology profile (informational only)"),
        )

    # ── use_cases tech columns (re-ensured; added by f6g7h8i9j0k1) ───────────
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

    # Drop only the column this migration owns (customers.tech_profile).
    ccols = {r["name"] for r in inspector.get_columns("customers")}
    if "tech_profile" in ccols:
        op.drop_column("customers", "tech_profile")
    # use_cases tech columns are owned by f6g7h8i9j0k1 — not dropped here.
