"""add assessments and ai_predictions tables; link use cases to rounds

Revision ID: a1b2c3d4e5f7
Revises: e8f9a0b1c2d3
Create Date: 2026-08-20 12:00:00.000000

- ``assessments``: one assessment round per customer (simplified lifecycle:
  at most one active round per customer; archived rounds are read-only and
  remain exportable through the established export endpoints).
- ``ai_predictions``: persisted model-generated readiness predictions.
- ``use_cases.assessment_id``: FK to the assessment round a use case
  belongs to.
- Backfill: every existing customer gets one active "Assessment 1" round
  and all of its use cases are linked to it (purely additive, no data loss).

Idempotent against a partially applied revision: already-present (empty)
tables or a pre-added ``assessment_id`` column are detected and skipped, so
``alembic upgrade head`` re-run after an interrupted application completes
cleanly.
"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f7'
down_revision: Union[str, None] = 'e8f9a0b1c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(bind) -> set:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table: str) -> set:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("assessments"):
        return
    if inspector.has_table("ai_predictions"):
        return
    bind = op.get_bind()
    tables = _tables(bind)

    if 'assessments' not in tables:
        op.create_table(
            'assessments',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False),
            sa.Column('created_by', sa.String(length=100), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('archived_at', sa.DateTime(), nullable=True),
        )
    if 'ai_predictions' not in tables:
        op.create_table(
            'ai_predictions',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('use_case_id', sa.Integer(), sa.ForeignKey('use_cases.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id', ondelete='CASCADE'), nullable=True, index=True),
            sa.Column('horizon_days', sa.Integer(), nullable=False),
            sa.Column('predicted_score', sa.Float(), nullable=False),
            sa.Column('score_change', sa.Float(), nullable=True),
            sa.Column('trend', sa.String(length=20), nullable=True),
            sa.Column('confidence', sa.Float(), nullable=True),
            sa.Column('reasoning', sa.Text(), nullable=True),
            sa.Column('model', sa.String(length=100), nullable=True),
            sa.Column('created_by', sa.String(length=100), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    # use_cases.assessment_id — direct ALTER (avoids SQLite batch rebuild,
    # which fails re-applying this table's unnamed FK constraints)
    if 'assessment_id' not in _columns(bind, 'use_cases'):
        op.execute("ALTER TABLE use_cases ADD COLUMN assessment_id INTEGER REFERENCES assessments(id) ON DELETE SET NULL")
        op.create_index('ix_use_cases_assessment_id', 'use_cases', ['assessment_id'])

    # Backfill: one active assessment round per existing customer (skipped
    # if the table already holds data from an interrupted prior run)
    if bind.execute(sa.text('SELECT COUNT(*) FROM assessments')).scalar() == 0:
        customers = bind.execute(sa.text('SELECT id, name FROM customers')).fetchall()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for cust_id, cust_name in customers:
            bind.execute(
                sa.text("INSERT INTO assessments (customer_id, name, status, created_at) VALUES (:cid, :name, 'active', :now)"),
                {'cid': cust_id, 'name': f'{cust_name} — Assessment 1', 'now': now},
            )
            row = bind.execute(sa.text('SELECT id FROM assessments WHERE customer_id = :cid'), {'cid': cust_id}).fetchone()
            if row:
                bind.execute(
                    sa.text('UPDATE use_cases SET assessment_id = :aid WHERE customer_id = :cid AND assessment_id IS NULL'),
                    {'aid': row[0], 'cid': cust_id},
                )


def downgrade() -> None:
    op.drop_index('ix_use_cases_assessment_id', 'use_cases')
    op.execute("ALTER TABLE use_cases DROP COLUMN assessment_id")
    op.drop_table('ai_predictions')
    op.drop_table('assessments')
