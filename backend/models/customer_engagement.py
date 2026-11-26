"""Recorded customer interactions, follow-up tasks, and durable delivery windows."""

import sqlalchemy as sa

from backend.models.use_case import Base

ACTIVITY_TYPES = ("call", "meeting", "email", "demo", "qbr")
TASK_STATUSES = ("open", "in_progress", "completed", "cancelled")
PROMOTION_TYPES = ("note", "renewal_attention", "contact_coverage", "eol_attention")


def _junction(name, parent, key, target):
    return sa.Table(
        name, Base.metadata,
        sa.Column(parent, sa.Integer, sa.ForeignKey(
            "customer_activities.id" if parent == "activity_id" else "customer_tasks.id",
            ondelete="CASCADE"), primary_key=True, nullable=False),
        sa.Column(key, sa.Integer, sa.ForeignKey(target, ondelete="CASCADE"),
                  primary_key=True, nullable=False),
    )


activity_contacts = _junction("activity_contacts", "activity_id", "contact_id", "customer_contacts.id")
task_evidence_notes = _junction("task_evidence_notes", "task_id", "note_id", "sales_notes.id")
task_evidence_activities = _junction("task_evidence_activities", "task_id", "activity_id", "customer_activities.id")


class CustomerActivity(Base):
    __tablename__ = "customer_activities"
    # IDs are never reissued (ER-12): retained references must not attach to a new row.
    __table_args__ = {"sqlite_autoincrement": True}

    id = sa.Column(sa.Integer, primary_key=True)
    customer_id = sa.Column(sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    type = sa.Column(sa.String(30), nullable=False)
    occurred_at = sa.Column(sa.DateTime)
    occurred_date = sa.Column(sa.Date)
    actor = sa.Column(sa.String(100), nullable=False)
    source = sa.Column(sa.String(255))
    outcome = sa.Column(sa.Text)
    created_by = sa.Column(sa.String(100), nullable=False)
    created_at = sa.Column(sa.DateTime, nullable=False, server_default=sa.func.current_timestamp())
    updated_at = sa.Column(sa.DateTime, nullable=False, server_default=sa.func.current_timestamp(),
                           onupdate=sa.func.current_timestamp())


class CustomerTask(Base):
    __tablename__ = "customer_tasks"
    __table_args__ = (sa.UniqueConstraint("customer_id", "source_key", name="uq_customer_task_source"), {"sqlite_autoincrement": True})

    id = sa.Column(sa.Integer, primary_key=True)
    customer_id = sa.Column(sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    title = sa.Column(sa.String(255), nullable=False)
    detail = sa.Column(sa.Text)
    assignee = sa.Column(sa.String(100))
    due_at = sa.Column(sa.DateTime)
    due_date = sa.Column(sa.Date)
    status = sa.Column(sa.String(20), nullable=False, default="open", server_default="open")
    completed_by = sa.Column(sa.String(100))
    completed_at = sa.Column(sa.DateTime)
    source_type = sa.Column(sa.String(20))
    source_id = sa.Column(sa.Integer)
    source_key = sa.Column(sa.String(255))
    created_by = sa.Column(sa.String(100), nullable=False)
    created_at = sa.Column(sa.DateTime, nullable=False, server_default=sa.func.current_timestamp())
    updated_at = sa.Column(sa.DateTime, nullable=False, server_default=sa.func.current_timestamp(),
                           onupdate=sa.func.current_timestamp())
    version = sa.Column(sa.Integer, nullable=False, default=1, server_default="1")


class TaskNotificationWindow(Base):
    __tablename__ = "task_notification_windows"
    __table_args__ = (sa.UniqueConstraint("task_id", "window", "user_name", name="uq_task_notification_window"),)

    id = sa.Column(sa.Integer, primary_key=True)
    task_id = sa.Column(sa.Integer, sa.ForeignKey("customer_tasks.id", ondelete="CASCADE"), nullable=False)
    window = sa.Column(sa.String(20), nullable=False)
    user_name = sa.Column(sa.String(100), nullable=False)
    created_at = sa.Column(sa.DateTime, nullable=False, server_default=sa.func.current_timestamp())
