"""add sales_notes + junction tables (S-A-I-L Sales Notes)

Revision ID: e7f8g9h0a1b2
Revises: c5d6e7f8a9b0
Create Date: 2026-09-07

Creates the sales_notes table plus the sales_note_technologies /
sales_note_use_cases junction tables backing the S-A-I-L Sales Notes feature. Notes are per-customer
structured records; junctions link notes to the customer's Technology
Inventory items and use cases (initiatives). Idempotent: each table is
created only if absent.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8g9h0a1b2"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "sales_notes" not in tables:
        op.create_table(
            "sales_notes",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False, index=True),
            sa.Column(
                "customer_id",
                sa.Integer(),
                sa.ForeignKey("customers.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("author", sa.String(length=255), nullable=True),
            sa.Column("source", sa.String(length=255), nullable=True),
            sa.Column("note_date", sa.Date(), nullable=True),
            sa.Column("category", sa.String(length=50), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column(
                "verification_state",
                sa.String(length=20),
                nullable=False,
                server_default="verified",
            ),
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

    if "sales_note_technologies" not in tables:
        op.create_table(
            "sales_note_technologies",
            sa.Column(
                "note_id",
                sa.Integer(),
                sa.ForeignKey("sales_notes.id", ondelete="CASCADE"),
                primary_key=True,
                nullable=False,
            ),
            sa.Column(
                "technology_id",
                sa.Integer(),
                sa.ForeignKey("customer_technologies.id", ondelete="CASCADE"),
                primary_key=True,
                nullable=False,
            ),
        )

    if "sales_note_use_cases" not in tables:
        op.create_table(
            "sales_note_use_cases",
            sa.Column(
                "note_id",
                sa.Integer(),
                sa.ForeignKey("sales_notes.id", ondelete="CASCADE"),
                primary_key=True,
                nullable=False,
            ),
            sa.Column(
                "use_case_id",
                sa.Integer(),
                sa.ForeignKey("use_cases.id", ondelete="CASCADE"),
                primary_key=True,
                nullable=False,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "sales_note_use_cases" in tables:
        op.drop_table("sales_note_use_cases")
    if "sales_note_technologies" in tables:
        op.drop_table("sales_note_technologies")
    if "sales_notes" in tables:
        op.drop_table("sales_notes")
