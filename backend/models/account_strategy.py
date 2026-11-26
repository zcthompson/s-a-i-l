"""Editable account strategies and immutable published snapshots."""
import sqlalchemy as sa

from backend.models.use_case import Base


class AccountStrategy(Base):
    __tablename__ = "account_strategy"
    # IDs are never reissued (ER-12): retained references must not attach to a new row.
    __table_args__ = {"sqlite_autoincrement": True}
    id = sa.Column(sa.Integer, primary_key=True)
    customer_id = sa.Column(sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    objectives = sa.Column(sa.Text)
    desired_outcomes = sa.Column(sa.Text)
    risks = sa.Column(sa.Text)
    plays = sa.Column(sa.Text)
    discovery_gaps = sa.Column(sa.Text)
    version = sa.Column(sa.Integer, nullable=False, server_default="1")
    created_by = sa.Column(sa.String(100))
    updated_by = sa.Column(sa.String(100))
    created_at = sa.Column(sa.DateTime, server_default=sa.func.current_timestamp())
    updated_at = sa.Column(sa.DateTime, server_default=sa.func.current_timestamp())


class AccountStrategySnapshot(Base):
    __tablename__ = "account_strategy_snapshots"
    __table_args__ = (sa.UniqueConstraint("customer_id", "plan_number", name="uq_account_strategy_snapshot_customer_number"),)
    id = sa.Column(sa.Integer, primary_key=True)
    customer_id = sa.Column(sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    plan_number = sa.Column(sa.Integer, nullable=False)
    note = sa.Column(sa.String(200))
    content = sa.Column(sa.JSON, nullable=False)
    published_by = sa.Column(sa.String(100))
    published_at = sa.Column(sa.DateTime, server_default=sa.func.current_timestamp())


def _junction(name, key, target):
    return sa.Table(name, Base.metadata,
        sa.Column("strategy_id", sa.Integer, sa.ForeignKey("account_strategy.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(key, sa.Integer, sa.ForeignKey(target, ondelete="CASCADE"), primary_key=True))


strategy_task_links = _junction("strategy_task_links", "task_id", "customer_tasks.id")
strategy_contact_links = _junction("strategy_contact_links", "contact_id", "customer_contacts.id")
strategy_note_links = _junction("strategy_note_links", "note_id", "sales_notes.id")
