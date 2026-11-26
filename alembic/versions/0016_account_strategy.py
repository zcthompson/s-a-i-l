"""Add account strategies and published snapshots."""
import sqlalchemy as sa
from alembic import op

revision = "0016_account_strategy"
down_revision = "0015_add_customer_engagement"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("account_strategy"):
        op.create_table("account_strategy",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("customer_id", sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
            *(sa.Column(name, sa.Text) for name in ("objectives", "desired_outcomes", "risks", "plays", "discovery_gaps")),
            sa.Column("version", sa.Integer, nullable=False, server_default="1"),
            sa.Column("created_by", sa.String(100)), sa.Column("updated_by", sa.String(100)),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime, server_default=sa.func.current_timestamp()))
    if "ix_account_strategy_customer_id" not in {i["name"] for i in sa.inspect(bind).get_indexes("account_strategy")}:
        op.create_index("ix_account_strategy_customer_id", "account_strategy", ["customer_id"], unique=True)
    if not inspector.has_table("account_strategy_snapshots"):
        op.create_table("account_strategy_snapshots", sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("customer_id", sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("plan_number", sa.Integer, nullable=False), sa.Column("note", sa.String(200)),
            sa.Column("content", sa.JSON, nullable=False), sa.Column("published_by", sa.String(100)),
            sa.Column("published_at", sa.DateTime, server_default=sa.func.current_timestamp()),
            sa.UniqueConstraint("customer_id", "plan_number", name="uq_account_strategy_snapshot_customer_number"))
    for name, key, target in (("strategy_task_links", "task_id", "customer_tasks.id"),
                              ("strategy_contact_links", "contact_id", "customer_contacts.id"),
                              ("strategy_note_links", "note_id", "sales_notes.id")):
        if not inspector.has_table(name):
            op.create_table(name, sa.Column("strategy_id", sa.Integer, sa.ForeignKey("account_strategy.id", ondelete="CASCADE"), primary_key=True),
                            sa.Column(key, sa.Integer, sa.ForeignKey(target, ondelete="CASCADE"), primary_key=True))


def downgrade():
    for name in ("strategy_note_links", "strategy_contact_links", "strategy_task_links", "account_strategy_snapshots", "account_strategy"):
        if sa.inspect(op.get_bind()).has_table(name):
            op.drop_table(name)
