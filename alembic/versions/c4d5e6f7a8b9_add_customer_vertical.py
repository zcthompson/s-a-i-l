"""add customers.vertical

WP19: customers gain an optional industry ``vertical`` (one of
``backend.verticals.VERTICALS``). Additive, nullable — no data impact on
existing rows.

Revision ID: c4d5e6f7a8b9
Revises: d1e2f3a4b5c6
Create Date: 2026-08-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existence guard keeps the migration idempotent across databases where
    # the column was already added (alembic 1.18 has no if_not_exists for
    # add_column on SQLite).
    inspector = sa.inspect(op.get_bind())
    if 'vertical' not in {c['name'] for c in inspector.get_columns('customers')}:
        op.add_column('customers', sa.Column('vertical', sa.String(length=100), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if 'vertical' in {c['name'] for c in inspector.get_columns('customers')}:
        op.drop_column('customers', 'vertical')
