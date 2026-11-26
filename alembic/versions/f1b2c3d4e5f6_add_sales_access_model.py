"""add sales access model: users.sales_role + sales hierarchy/assignment tables

Revision ID: f1b2c3d4e5f6
Revises: f0a1b2c3d4e5
Create Date: 2026-10-12

shift to global customer management, phase 2 (sales access model).
STRICTLY ADDITIVE — nothing existing changes behavior:

  - ``users.sales_role`` (String(20), nullable): orthogonal to ``is_admin``.
    A sales-manager NEVER sets is_admin=1; is_admin
    remains the exclusive system-admin authority.
  - ``sales_reporting`` (rep_user_id UNIQUE -> manager_user_id): the sales
    reporting hierarchy. Manager scope = customers owned by (transitive)
    reports. Relationships use stable user IDs, not branch/display-name
    similarity.
  - ``inside_sales_assignments`` (inside_sales_user_id + customer_id UNIQUE,
    optional rep_user_id): customer-specific inside-sales assignments.

Idempotent: each step is guarded by an inspector check, so a re-run (and a
fresh DB that already has the columns/tables via create_all) is a no-op.
``alembic check`` stays clean afterwards.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1b2c3d4e5f6"
down_revision: Union[str, None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. users.sales_role (String(20), nullable)
    if inspector.has_table("users"):
        cols = {c["name"] for c in inspector.get_columns("users")}
        if "sales_role" not in cols:
            with op.batch_alter_table("users", recreate="auto") as batch_op:
                batch_op.add_column(sa.Column("sales_role", sa.String(20), nullable=True))

    # 2. sales_reporting (rep -> manager hierarchy)
    if not inspector.has_table("sales_reporting"):
        op.create_table(
            "sales_reporting",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
            sa.Column("rep_user_id", sa.Integer(), nullable=False),
            sa.Column("manager_user_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["rep_user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["manager_user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("rep_user_id", name="uq_sales_reporting_rep"),
        )

    # 3. inside_sales_assignments (customer-specific inside-sales)
    if not inspector.has_table("inside_sales_assignments"):
        op.create_table(
            "inside_sales_assignments",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
            sa.Column("inside_sales_user_id", sa.Integer(), nullable=False),
            sa.Column("customer_id", sa.Integer(), nullable=False),
            sa.Column("rep_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["inside_sales_user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["rep_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("inside_sales_user_id", "customer_id", name="uq_inside_sales_assignment"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("inside_sales_assignments"):
        op.drop_table("inside_sales_assignments")
    if inspector.has_table("sales_reporting"):
        op.drop_table("sales_reporting")
    if inspector.has_table("users"):
        cols = {c["name"] for c in inspector.get_columns("users")}
        if "sales_role" in cols:
            with op.batch_alter_table("users", recreate="auto") as batch_op:
                batch_op.drop_column("sales_role")
