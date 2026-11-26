"""Add customer sales-structure fields (sales_area, primary_subsidiary).

The operator's 2026-10-26 updated-structure re-seed (updated_structure_accounts.xlsx)
carries a per-customer Sales Area # and Primary Subsidiary; the customer model
already represents the per-customer branch home (``customers.branch``) but had
no home for the other two structure attributes. Additive + nullable — existing
rows stay unknown (NULL), and the re-seed fills them.

Idempotent: each step is guarded by an inspector check (the established
migration convention — see f0a1b2c3d4e5), so a re-run — including the
``stamp <rev>`` + ``upgrade head`` recovery path exercised by
``test_migration_backfill_idempotent_and_roundtrip`` — is a no-op when the
columns already exist. ``alembic check`` stays clean afterwards.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_add_customer_sales_structure"
down_revision: Union[str, None] = "0012_add_rep_intelligence_imports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("customers"):
        cust_cols = {c["name"] for c in inspector.get_columns("customers")}
        if "sales_area" not in cust_cols:
            with op.batch_alter_table("customers", recreate="auto") as batch_op:
                batch_op.add_column(sa.Column("sales_area", sa.String(20), nullable=True))
        if "primary_subsidiary" not in cust_cols:
            with op.batch_alter_table("customers", recreate="auto") as batch_op:
                batch_op.add_column(sa.Column("primary_subsidiary", sa.String(255), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("customers"):
        cust_cols = {c["name"] for c in inspector.get_columns("customers")}
        if "sales_area" in cust_cols or "primary_subsidiary" in cust_cols:
            with op.batch_alter_table("customers", recreate="auto") as batch_op:
                if "primary_subsidiary" in cust_cols:
                    batch_op.drop_column("primary_subsidiary")
                if "sales_area" in cust_cols:
                    batch_op.drop_column("sales_area")
