"""ensure sales_evaluations persona schema parity

Revision ID: b7c8d9e0f1a2
Revises: e7f8g9h0a1b2
Create Date: 2026-09-07

Persona-driven Sales Evaluations add three columns to the existing sales_evaluations table:

- persona (String(50))      — the audience context (persona id) under which
  the evaluation was generated (NULL = generic / legacy rows)
- source_context (JSON)     — provenance: which sources + indicators the
  engine consumed (counts, ids of EOL/at-risk items, freshness)
- persona_sections (JSON)   — the persona-tailored section set

The original create-table migration for sales_evaluations predates these
columns, so any existing database must gain them idempotently (same
pattern as c9d0e1f2a3b4_ensure_customer_knowledge_schema and
d7e8f9a0b1c2_ensure_technology_tracking_schema).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "e7f8g9h0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("sales_evaluations"):
        return
    cols = {c["name"] for c in inspector.get_columns("sales_evaluations")}
    if "persona" not in cols:
        op.add_column(
            "sales_evaluations",
            sa.Column("persona", sa.String(50), nullable=True),
        )
    if "source_context" not in cols:
        op.add_column(
            "sales_evaluations",
            sa.Column("source_context", sa.JSON, nullable=True),
        )
    if "persona_sections" not in cols:
        op.add_column(
            "sales_evaluations",
            sa.Column("persona_sections", sa.JSON, nullable=True),
        )
    # Re-inspect after the DDL above (the pre-DDL `cols` snapshot would miss a
    # just-added column) and create the index idempotently — the model
    # declares index=True on persona, so `alembic check` expects the index.
    index_names = {ix["name"] for ix in sa.inspect(bind).get_indexes("sales_evaluations")}
    if "ix_sales_evaluations_persona" not in index_names:
        op.create_index(
            "ix_sales_evaluations_persona", "sales_evaluations", ["persona"]
        )


def downgrade() -> None:
    # Destructive on SQLite (data loss for existing rows); leave columns in
    # place. The columns are nullable and unused by pre-P5 code.
    pass
