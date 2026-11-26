"""initial schema for use_cases table

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-07-30 19:00:00.000000

Creates all tables that the SQLAlchemy models define, including
FK relationships, indexes, and constraints. Subsequent migrations
should only add completely new tables — no column/alter operations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("customers"):
        return
    if inspector.has_table("users"):
        return
    if inspector.has_table("use_cases"):
        return
    if inspector.has_table("departments"):
        return
    if inspector.has_table("comments"):
        return
    if inspector.has_table("notifications"):
        return
    if inspector.has_table("customer_users"):
        return
    if inspector.has_table("projections"):
        return
    if inspector.has_table("audit_logs"):
        return
    # ── customers ──────────────────────────────────────────────────────
    op.create_table(
        'customers',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index(op.f('ix_customers_id'), 'customers', ['id'], unique=False)
    op.create_index(op.f('ix_customers_name'), 'customers', ['name'], unique=True)

    # ── users ──────────────────────────────────────────────────────────
    # Model: id(pk,ix), username(uq,ix), email(uq,ix), hashed_password,
    #         display_name, department, customer_id, created_at, updated_at,
    #         is_active, is_admin(server_default='0'), approved(server_default='0'),
    #         role(server_default='user')
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('username', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=100), nullable=True),
        sa.Column('department', sa.String(length=100), nullable=True),
        sa.Column('customer_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Integer(), nullable=True),
        sa.Column('is_admin', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('approved', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('role', sa.String(length=20), nullable=False, server_default='user'),
    )
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index('ix_users_customer_id', 'users', ['customer_id'], unique=False)

    # ── departments ────────────────────────────────────────────────────
    # Model: id(pk), name, customer_id(FK->customers.ondelete CASCADE), created_at
    op.create_table(
        'departments',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
    )
    op.create_index(op.f('ix_departments_id'), 'departments', ['id'], unique=False)
    op.create_index(op.f('ix_departments_customer_id'), 'departments', ['customer_id'], unique=False)

    # ── use_cases ──────────────────────────────────────────────────────
    # Model: id(pk,ix), title, description, customer_id(FK->customers.ondelete SET NULL,ix),
    #         department, department_id(FK->departments NO ondelete,ix), status,
    #         created_at, updated_at, goals, challenges, pain_points,
    #         impact_category, impact_description, estimated_savings,
    #         estimated_revenue, timeline_estimate, scores, overall_score,
    #         scored_at, score_history, created_by, updated_by
    op.create_table(
        'use_cases',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('customer_id', sa.Integer(), nullable=True),
        sa.Column('department', sa.String(length=100), nullable=True),
        sa.Column('department_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('goals', sa.JSON(), nullable=True),
        sa.Column('challenges', sa.JSON(), nullable=True),
        sa.Column('pain_points', sa.JSON(), nullable=True),
        sa.Column('impact_category', sa.String(length=50), nullable=True),
        sa.Column('impact_description', sa.Text(), nullable=True),
        sa.Column('estimated_savings', sa.Float(), nullable=True),
        sa.Column('estimated_revenue', sa.Float(), nullable=True),
        sa.Column('timeline_estimate', sa.String(length=50), nullable=True),
        sa.Column('scores', sa.JSON(), nullable=True),
        sa.Column('overall_score', sa.Float(), nullable=True),
        sa.Column('scored_at', sa.DateTime(), nullable=True),
        sa.Column('score_history', sa.JSON(), nullable=True),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.Column('updated_by', sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id']),
    )
    op.create_index(op.f('ix_use_cases_id'), 'use_cases', ['id'], unique=False)
    op.create_index('ix_use_cases_customer_id', 'use_cases', ['customer_id'])
    op.create_index('ix_use_cases_department_id', 'use_cases', ['department_id'])

    # ── comments ───────────────────────────────────────────────────────
    # Model: id(pk), use_case_id(FK->use_cases), user_name, content, created_at, updated_at
    op.create_table(
        'comments',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('use_case_id', sa.Integer(), nullable=False),
        sa.Column('user_name', sa.String(length=100), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['use_case_id'], ['use_cases.id']),
    )
    op.create_index(op.f('ix_comments_id'), 'comments', ['id'], unique=False)
    op.create_index(op.f('ix_comments_use_case_id'), 'comments', ['use_case_id'], unique=False)

    # ── notifications ──────────────────────────────────────────────────
    # Model: id(pk), user_name, type, message, customer_id, read, created_at
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_name', sa.String(length=100), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=True),
        sa.Column('read', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index(op.f('ix_notifications_id'), 'notifications', ['id'], unique=False)
    op.create_index('ix_notifications_customer_id', 'notifications', ['customer_id'])

    # ── customer_users (junction table) ────────────────────────────────
    # Model: id(pk, ix), customer_id(FK->customers.ondelete CASCADE, ix),
    #         user_id(FK->users.ondelete CASCADE, ix), role, granted_by(FK->users.ondelete SET NULL),
    #         granted_at
    # Note: NO explicit UniqueConstraint — SQLAlchemy doesn't create one
    # unless you explicitly add UniqueConstraint or unique=True on column
    op.create_table(
        'customer_users',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False, server_default='member'),
        sa.Column('granted_by', sa.Integer(), nullable=True),
        sa.Column('granted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['granted_by'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_customer_users_id', 'customer_users', ['id'])
    op.create_index('ix_customer_users_customer_id', 'customer_users', ['customer_id'])
    op.create_index('ix_customer_users_user_id', 'customer_users', ['user_id'])

    # ── projections ────────────────────────────────────────────────────
    # Model: id(pk), customer_id(FK->customers.ondelete CASCADE),
    #         customer_name, generated_at, projection_data, status
    op.create_table(
        'projections',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('customer_name', sa.String(length=255), nullable=False),
        sa.Column('generated_at', sa.DateTime(), nullable=False),
        sa.Column('projection_data', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='completed', nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
    )
    op.create_index(op.f('ix_projections_id'), 'projections', ['id'], unique=False)
    op.create_index('ix_projections_customer_id', 'projections', ['customer_id'])
    op.create_index('ix_projections_customer_name', 'projections', ['customer_name'])

    # ── audit_logs ─────────────────────────────────────────────────────
    # Model: id(pk), user_id, username, action, customer_id, target_id,
    #         details, ip_address, created_at
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=100), nullable=False, server_default='anonymous'),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=True),
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_audit_logs_id', 'audit_logs', ['id'])
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('ix_audit_logs_customer_id', 'audit_logs', ['customer_id'])


def downgrade() -> None:
    op.drop_index('ix_audit_logs_customer_id', table_name='audit_logs')
    op.drop_index('ix_audit_logs_action', table_name='audit_logs')
    op.drop_index('ix_audit_logs_id', table_name='audit_logs')
    op.drop_table('audit_logs')

    op.drop_index('ix_projections_customer_name', table_name='projections')
    op.drop_index('ix_projections_customer_id', table_name='projections')
    op.drop_index(op.f('ix_projections_id'), table_name='projections')
    op.drop_table('projections')

    op.drop_index('ix_customer_users_user_id', table_name='customer_users')
    op.drop_index('ix_customer_users_customer_id', table_name='customer_users')
    op.drop_index('ix_customer_users_id', table_name='customer_users')
    op.drop_table('customer_users')

    op.drop_index('ix_notifications_customer_id', table_name='notifications')
    op.drop_index(op.f('ix_notifications_id'), table_name='notifications')
    op.drop_table('notifications')

    op.drop_index(op.f('ix_comments_use_case_id'), table_name='comments')
    op.drop_index(op.f('ix_comments_id'), table_name='comments')
    op.drop_table('comments')

    op.drop_index('ix_use_cases_department_id', table_name='use_cases')
    op.drop_index('ix_use_cases_customer_id', table_name='use_cases')
    op.drop_index(op.f('ix_use_cases_id'), table_name='use_cases')
    op.drop_table('use_cases')

    op.drop_index(op.f('ix_departments_customer_id'), table_name='departments')
    op.drop_index(op.f('ix_departments_id'), table_name='departments')
    op.drop_table('departments')



    op.drop_index('ix_users_customer_id', table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_table('users')

    op.drop_index(op.f('ix_customers_name'), table_name='customers')
    op.drop_index(op.f('ix_customers_id'), table_name='customers')
    op.drop_table('customers')
