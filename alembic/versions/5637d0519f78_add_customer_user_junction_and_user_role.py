"""add customer-user junction table and user role field

Revision ID: 5637d0519f78
Revises: e5f6a7b8c9d0
Create Date: 2026-08-09

NOTE: customer_users junction table and users.role were already
created in the initial schema (a1b2c3d4e5f6). This migration is
a no-op.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5637d0519f78'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
