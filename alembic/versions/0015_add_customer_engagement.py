"""Add recorded customer activities, follow-up tasks, and delivery deduplication."""

import sqlalchemy as sa
from alembic import op

revision = "0015_add_customer_engagement"
down_revision = "0014_add_customer_contacts"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    inspector = sa.inspect(bind)
    if not inspector.has_table("customer_activities"):
        op.create_table(
            "customer_activities",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("customer_id", sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("type", sa.String(30), nullable=False),
            sa.Column("occurred_at", sa.DateTime),
            sa.Column("occurred_date", sa.Date),
            sa.Column("actor", sa.String(100), nullable=False),
            sa.Column("source", sa.String(255)),
            sa.Column("outcome", sa.Text),
            sa.Column("created_by", sa.String(100), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        )
    if not inspector.has_table("customer_tasks"):
        op.create_table(
            "customer_tasks",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("customer_id", sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("detail", sa.Text),
            sa.Column("assignee", sa.String(100)),
            sa.Column("due_at", sa.DateTime),
            sa.Column("due_date", sa.Date),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("completed_by", sa.String(100)),
            sa.Column("completed_at", sa.DateTime),
            sa.Column("source_type", sa.String(20)),
            sa.Column("source_id", sa.Integer),
            sa.Column("source_key", sa.String(255)),
            sa.Column("created_by", sa.String(100), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("version", sa.Integer, nullable=False, server_default="1"),
            sa.UniqueConstraint("customer_id", "source_key", name="uq_customer_task_source"),
        )
    for name, parent, target, key, related in (
        ("activity_contacts", "activity_id", "customer_activities.id", "contact_id", "customer_contacts.id"),
        ("task_evidence_notes", "task_id", "customer_tasks.id", "note_id", "sales_notes.id"),
        ("task_evidence_activities", "task_id", "customer_tasks.id", "activity_id", "customer_activities.id"),
    ):
        if not inspector.has_table(name):
            op.create_table(
                name,
                sa.Column(parent, sa.Integer, sa.ForeignKey(target, ondelete="CASCADE"), primary_key=True, nullable=False),
                sa.Column(key, sa.Integer, sa.ForeignKey(related, ondelete="CASCADE"), primary_key=True, nullable=False),
            )
    if not inspector.has_table("task_notification_windows"):
        op.create_table(
            "task_notification_windows",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("task_id", sa.Integer, sa.ForeignKey("customer_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("window", sa.String(20), nullable=False),
            sa.Column("user_name", sa.String(100), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
            sa.UniqueConstraint("task_id", "window", "user_name", name="uq_task_notification_window"),
        )
    for name in ("customer_activities", "customer_tasks"):
        index = f"ix_{name}_customer_id"
        if index not in {item["name"] for item in sa.inspect(bind).get_indexes(name)}:
            op.create_index(index, name, ["customer_id"])


def downgrade():
    bind = op.get_bind()
    for name in ("task_notification_windows", "task_evidence_activities", "task_evidence_notes",
                 "activity_contacts", "customer_tasks", "customer_activities"):
        if sa.inspect(bind).has_table(name):
            op.drop_table(name)
