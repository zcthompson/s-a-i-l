"""ensure customer_knowledge schema parity

Revision ID: c9d0e1f2a3b4
Revises: d7e8f9a0b1c2
Create Date: 2026-09-07

The a1b2c3d4e5f6 create-table migration skips the table when it already
exists (early-return on inspector.has_table). Databases where the
customer_knowledge table was created while the model still lacked the
ingestion_status / classification / category columns (e.g. via an app-startup
create_all on an older model) never gain those columns on
``alembic upgrade head`` — the model then SELECTs them and every
customer-knowledge query fails with
``sqlite3.OperationalError: no such column: customer_knowledge.ingestion_status``.

This migration idempotently adds the missing columns (same pattern as
d7e8f9a0b1c2_ensure_technology_tracking_schema) so any such DB reaches
model parity on upgrade.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("customer_knowledge"):
        return
    cols = {c["name"] for c in inspector.get_columns("customer_knowledge")}
    if "ingestion_status" not in cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("ingestion_status", sa.String(50), nullable=True),
        )
    if "classification" not in cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("classification", sa.String(50), nullable=True),
        )
    if "category" not in cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("category", sa.String(50), nullable=True),
        )


def downgrade() -> None:
    # Destructive on SQLite (data loss for existing rows); leave columns in
    # place. The columns are nullable and unused by pre-c9d0e1f2a3b4 code.
    pass
