"""Add intelligence_imports.amount_issues (Part 14 import remediation).

An unreadable amount cell on an imported pipeline row no longer rejects the
whole file: the amount is recorded as unknown and the cell is reported as an
amount warning. ``amount_issues`` keeps that warning list (JSON text) on the
batch so a reopened import shows the same warnings. Nullable — batches
imported before this revision read as having no issues.

Idempotent: the column add is guarded by an inspector check (the
0013/0014/0017/0018 convention). ``alembic check`` stays clean.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_add_import_amount_issues"
down_revision: Union[str, None] = "0018_add_customer_aliases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(inspector):
    return {column["name"] for column in inspector.get_columns("intelligence_imports")}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("intelligence_imports") and "amount_issues" not in _columns(inspector):
        with op.batch_alter_table("intelligence_imports") as batch:
            batch.add_column(sa.Column("amount_issues", sa.Text(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("intelligence_imports") and "amount_issues" in _columns(inspector):
        with op.batch_alter_table("intelligence_imports") as batch:
            batch.drop_column("amount_issues")
