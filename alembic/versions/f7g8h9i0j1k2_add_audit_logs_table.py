"""add audit_logs table

Revision ID: f7g8h9i0j1k2
Revises: 5637d0519f78
Create Date: 2026-08-12 12:00:00.000000

NOTE: audit_logs was already created in the initial schema (a1b2c3d4e5f6).
This migration is a no-op.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f7g8h9i0j1k2'
down_revision: Union[str, None] = '5637d0519f78'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
