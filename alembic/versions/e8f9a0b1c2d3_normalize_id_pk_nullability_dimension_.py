"""normalize id PK nullability on dimension_configs and score_history

Revision ID: e8f9a0b1c2d3
Revises: a9f3c7e51b02
Create Date: 2026-08-19 19:20:00.000000

Some environments (notably the validated seed DB) carry these tables
from out-of-band creation with the bare rowid-alias form
``id INTEGER PRIMARY KEY``. SQLAlchemy's SQLite inspector reports that
column as nullable, so ``alembic check`` diffs it against the model
(nullable=False). This migration rebuilds both tables (batch mode,
data-preserving) with ``id INTEGER NOT NULL PRIMARY KEY`` and is
idempotent on databases already created from bf4d3068b073.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e8f9a0b1c2d3'
down_revision: Union[str, Sequence[str], None] = 'a9f3c7e51b02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _id_is_nullable(table: str) -> bool:
    """True if the table's id column is missing an explicit NOT NULL."""
    if op.get_bind().dialect.name != "sqlite":
        return next((column["nullable"] for column in sa.inspect(op.get_bind()).get_columns(table) if column["name"] == "id"), False)
    rows = op.get_bind().exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    for row in rows:
        if row[1] == "id":
            return row[3] == 0  # PRAGMA notnull flag
    return False


def upgrade() -> None:
    for table in ("dimension_configs", "score_history"):
        if _id_is_nullable(table):
            with op.batch_alter_table(table) as batch:
                batch.alter_column("id", nullable=False)


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return  # PostgreSQL primary keys are always non-nullable.
    for table in ("dimension_configs", "score_history"):
        with op.batch_alter_table(table) as batch:
            batch.alter_column("id", nullable=True)
