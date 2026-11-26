"""add sales_ops_assignments (per-account sales-ops contributor access)

Revision ID: a2b3c4d5e6f7
Revises: f1b2c3d4e5f6
Create Date: 2026-10-14

S-A-I-L 0.2.10. ``sales_ops_assignments`` (user_id + customer_id UNIQUE):
customer-specific sales-ops assignments. A sales_ops user is read-only on an
assigned account plus may write sales notes and contribute knowledge.

Idempotent: guarded by inspector checks. Downgrade drops the table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "f1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("sales_ops_assignments"):
        op.create_table(
            "sales_ops_assignments",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("customer_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("user_id", "customer_id", name="uq_sales_ops_assignment"),
        )
        op.create_index(
            "ix_sales_ops_assignments_customer_id",
            "sales_ops_assignments",
            ["customer_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("sales_ops_assignments"):
        existing = {i["name"] for i in inspector.get_indexes("sales_ops_assignments")}
        if "ix_sales_ops_assignments_customer_id" in existing:
            op.drop_index("ix_sales_ops_assignments_customer_id", table_name="sales_ops_assignments")
        op.drop_table("sales_ops_assignments")
