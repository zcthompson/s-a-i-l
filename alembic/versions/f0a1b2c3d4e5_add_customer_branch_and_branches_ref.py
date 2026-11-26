"""add customers.branch, branches reference table, and relax users.email

Revision ID: f0a1b2c3d4e5
Revises: c7d8e9f0a1b2
Create Date: 2026-10-12

Prod-seed schema support (real-customer import):
  - ``customers.branch`` — the sales branch a customer/rep is home to
    (e.g. "BR20 - Example Customer H"). String, nullable, denormalized on the
    customer the same way ``customers.vertical`` is. Populated from the
    customer seed CSV; not a hard FK to the ``branches`` reference table
    (a new customer may be created against any branch text, and the
    reference list is for the create-customer dropdown, not a constraint).
  - ``branches`` — reference table of selectable branch values, imported
    from the same seed CSV so the create-customer form can offer them as a
    dropdown (mirrors the /api/customers/verticals/ endpoint pattern).
  - ``users.email`` relaxed to NULL — a customer's Owner (sales rep) is
    seeded name-only (pending) until the operator fills in email/contact
    details. SQLite cannot ``ALTER COLUMN ... DROP NOT NULL``, so the
    ``users`` table is rebuilt via Alembic batch operations (charter §3);
    the rebuild preserves every existing row, its ``id`` (the
    ``customer_users`` junction references users.id, so ids stay stable),
    and every populated email value. SQLite UNIQUE treats NULLs as distinct,
    so many name-only pending users (all email NULL) coexist legally.

Idempotent: each step is guarded by an inspector check, so a re-run (and a
fresh DB that already has the columns/tables via create_all) is a no-op.
``alembic check`` stays clean afterwards (no create_all / startup mutation —
charter prohibitions).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. customers.branch (String(100), nullable)
    if inspector.has_table("customers"):
        cust_cols = {c["name"] for c in inspector.get_columns("customers")}
        if "branch" not in cust_cols:
            with op.batch_alter_table("customers", recreate="auto") as batch_op:
                batch_op.add_column(sa.Column("branch", sa.String(100), nullable=True))

    # 2. branches reference table
    if not inspector.has_table("branches"):
        op.create_table(
            "branches",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
            sa.Column("name", sa.String(100), nullable=False, unique=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    # 3. users.email -> nullable (batch rebuild; SQLite cannot drop NOT NULL)
    if inspector.has_table("users"):
        email_cols = {c["name"]: c for c in inspector.get_columns("users")}
        if email_cols and email_cols.get("email") is not None and email_cols["email"]["nullable"] is False:
            with op.batch_alter_table("users", recreate="auto") as batch_op:
                batch_op.alter_column(
                    "email",
                    existing_type=sa.String(255),
                    existing_nullable=False,
                    nullable=True,
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Reverse: drop customers.branch, drop branches table, re-assert NOT NULL
    # on users.email (only if no NULL-email rows exist — preservation-first).
    if inspector.has_table("customers"):
        cust_cols = {c["name"] for c in inspector.get_columns("customers")}
        if "branch" in cust_cols:
            with op.batch_alter_table("customers", recreate="auto") as batch_op:
                batch_op.drop_column("branch")

    if inspector.has_table("branches"):
        op.drop_table("branches")

    if inspector.has_table("users"):
        email_cols = {c["name"]: c for c in inspector.get_columns("users")}
        if email_cols.get("email") is not None and email_cols["email"]["nullable"] is True:
            null_email = bind.execute(
                sa.text("SELECT COUNT(*) FROM users WHERE email IS NULL")
            ).scalar()
            if null_email:
                raise RuntimeError(
                    f"Refusing to downgrade users.email (NOT NULL) while {null_email} "
                    "row(s) have NULL email — populate them first (preservation-first)."
                )
            with op.batch_alter_table("users", recreate="auto") as batch_op:
                batch_op.alter_column(
                    "email",
                    existing_type=sa.String(255),
                    existing_nullable=True,
                    nullable=False,
                )
