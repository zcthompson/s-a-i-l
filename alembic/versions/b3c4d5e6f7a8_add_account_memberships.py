"""add account_memberships + customers.ownership_status (RBAC core)

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-10-15

RBAC directive. ``account_memberships`` holds the per-account role grants
(primary_owner / co_owner / sales_ops / inside_sales + inside-sales section
grants). ``customers.ownership_status`` ('needs_review') marks placeholder
accounts for the admin ownership-review queue.

Data migration (idempotent INSERT ... SELECT ... WHERE NOT EXISTS):
  customer_users role='owner'     -> primary_owner  (source='migration')
  inside_sales_assignments        -> inside_sales   (section_grants NULL)
  sales_ops_assignments           -> sales_ops

Downgrade drops the table and the column (batch op for SQLite).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (target role, source table, user column, extra source filter)
_BACKFILL = (
    ("primary_owner", "customer_users", "user_id", "s.role = 'owner'"),
    ("inside_sales", "inside_sales_assignments", "inside_sales_user_id", "1 = 1"),
    ("sales_ops", "sales_ops_assignments", "user_id", "1 = 1"),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("account_memberships"):
        op.create_table(
            "account_memberships",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("customer_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("section_grants", sa.JSON(), nullable=True),
            sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "user_id", "customer_id", "role",
                name="uq_account_membership_user_customer_role",
            ),
        )
        op.create_index("ix_account_memberships_user_id", "account_memberships", ["user_id"])
        op.create_index("ix_account_memberships_customer_id", "account_memberships", ["customer_id"])

    cols = {c["name"] for c in inspector.get_columns("customers")}
    if "ownership_status" not in cols:
        op.add_column(
            "customers", sa.Column("ownership_status", sa.String(length=20), nullable=True)
        )

    for role, table, user_col, where in _BACKFILL:
        op.execute(sa.text(
            "INSERT INTO account_memberships "
            "(user_id, customer_id, role, section_grants, source, created_at) "
            f"SELECT s.{user_col}, s.customer_id, '{role}', NULL, 'migration', CURRENT_TIMESTAMP "
            f"FROM {table} s WHERE {where} "
            "AND NOT EXISTS (SELECT 1 FROM account_memberships m "
            f"WHERE m.user_id = s.{user_col} AND m.customer_id = s.customer_id "
            f"AND m.role = '{role}')"
        ))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("account_memberships"):
        existing = {i["name"] for i in inspector.get_indexes("account_memberships")}
        for ix in ("ix_account_memberships_user_id", "ix_account_memberships_customer_id"):
            if ix in existing:
                op.drop_index(ix, table_name="account_memberships")
        op.drop_table("account_memberships")

    cols = {c["name"] for c in inspector.get_columns("customers")}
    if "ownership_status" in cols:
        with op.batch_alter_table("customers") as batch:
            batch.drop_column("ownership_status")
