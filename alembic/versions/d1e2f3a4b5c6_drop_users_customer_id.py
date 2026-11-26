"""drop legacy users.customer_id

The single-customer assignment column on ``users`` is retired.
``customer_users`` (the junction table) is the sole authority for
customer access, and the live database contains zero rows with this
column populated (verified 2026-08-21: 0/33 users).  All backend
writes, API exposure, and the junction/legacy union helper were
removed in the same change set.

Revision ID: d1e2f3a4b5c6
Revises: b1c2d3e4f5a6
Create Date: 2026-08-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existence guards keep the migration idempotent across databases
    # where the index/column were already removed (alembic 1.18 does not
    # expose if_exists for these operations on SQLite).
    inspector = sa.inspect(op.get_bind())
    if 'ix_users_customer_id' in {i['name'] for i in inspector.get_indexes('users')}:
        op.drop_index('ix_users_customer_id', table_name='users')
    if 'customer_id' in {c['name'] for c in inspector.get_columns('users')}:
        op.drop_column('users', 'customer_id')


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if 'customer_id' not in {c['name'] for c in inspector.get_columns('users')}:
        op.add_column('users', sa.Column('customer_id', sa.Integer(), nullable=True))
    if 'ix_users_customer_id' not in {i['name'] for i in inspector.get_indexes('users')}:
        op.create_index('ix_users_customer_id', 'users', ['customer_id'], unique=False)
