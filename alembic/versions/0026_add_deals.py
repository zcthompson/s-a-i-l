"""Rep-owned deals, admin-managed pipeline stages, stage history and links.

Creates the tables (AUTOINCREMENT, ER-10/11/12 non-reuse) and seeds the
starter pipeline stages. Downgrade drops the tables and warns when deals
exist, because rep-entered deal data would be lost.
"""

import warnings

import sqlalchemy as sa
from alembic import op

revision = "0026_add_deals"
down_revision = "0025_prevent_record_id_reuse"
branch_labels = None
depends_on = None

DEFAULT_STAGES = (
    ("qualification", "Qualification", "open", 10, 10),
    ("discovery", "Discovery", "open", 20, 25),
    ("proposal", "Proposal", "open", 30, 50),
    ("negotiation", "Negotiation", "open", 40, 75),
    ("closed_won", "Closed Won", "won", 90, 100),
    ("closed_lost", "Closed Lost", "lost", 100, 0),
)
LINKS = (
    ("deal_contacts", "contact_id", "customer_contacts.id"),
    ("deal_tasks", "task_id", "customer_tasks.id"),
    ("deal_activities", "activity_id", "customer_activities.id"),
    ("deal_notes", "note_id", "sales_notes.id"),
    ("deal_technologies", "technology_id", "customer_technologies.id"),
)


def _now():
    return sa.func.current_timestamp()


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("pipeline_stages"):
        stages = op.create_table(
            "pipeline_stages",
            sa.Column("id", sa.Integer, primary_key=True, nullable=False),
            sa.Column("key", sa.String(50), nullable=False, unique=True),
            sa.Column("label", sa.String(100), nullable=False),
            sa.Column("stage_class", sa.String(10), nullable=False),
            sa.Column("position", sa.Integer, nullable=False),
            sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("default_probability", sa.Integer),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=_now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=_now()),
            sqlite_autoincrement=True,
        )
        op.bulk_insert(stages, [
            {"key": k, "label": label, "stage_class": cls, "position": pos, "active": True, "default_probability": prob}
            for k, label, cls, pos, prob in DEFAULT_STAGES
        ])
    if not inspector.has_table("deals"):
        op.create_table(
            "deals",
            sa.Column("id", sa.Integer, primary_key=True, nullable=False),
            sa.Column("customer_id", sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("owner_name", sa.String(255)),
            sa.Column("stage_id", sa.Integer, sa.ForeignKey("pipeline_stages.id"), nullable=False),
            sa.Column("close_date", sa.Date),
            sa.Column("amount_minor", sa.BigInteger),
            sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
            sa.Column("amount_basis", sa.String(10)),
            sa.Column("probability", sa.Integer),
            sa.Column("deal_type", sa.String(20)),
            sa.Column("next_step", sa.Text),
            sa.Column("next_step_date", sa.Date),
            sa.Column("closed_reason", sa.Text),
            sa.Column("closed_at", sa.DateTime),
            sa.Column("source_type", sa.String(30)),
            sa.Column("source_id", sa.Integer),
            sa.Column("source_key", sa.String(255)),
            sa.Column("created_by", sa.String(100), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=_now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=_now()),
            sa.Column("version", sa.Integer, nullable=False, server_default="1"),
            sa.UniqueConstraint("customer_id", "source_key", name="uq_deal_source"),
            sqlite_autoincrement=True,
        )
        op.create_index("ix_deals_customer_id", "deals", ["customer_id"])
        op.create_index("ix_deals_owner_user_id", "deals", ["owner_user_id"])
        op.create_index("ix_deals_stage_id", "deals", ["stage_id"])
    if not inspector.has_table("deal_stage_history"):
        op.create_table(
            "deal_stage_history",
            sa.Column("id", sa.Integer, primary_key=True, nullable=False),
            sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id", ondelete="CASCADE"), nullable=False),
            sa.Column("from_stage_id", sa.Integer, sa.ForeignKey("pipeline_stages.id")),
            sa.Column("to_stage_id", sa.Integer, sa.ForeignKey("pipeline_stages.id"), nullable=False),
            sa.Column("actor", sa.String(100), nullable=False),
            sa.Column("at", sa.DateTime, nullable=False),
            sa.Column("amount_minor", sa.BigInteger),
            sa.Column("currency", sa.String(3)),
            sa.Column("amount_basis", sa.String(10)),
            sa.Column("close_date", sa.Date),
            sa.Column("note", sa.String(255)),
            sqlite_autoincrement=True,
        )
        op.create_index("ix_deal_stage_history_deal_id", "deal_stage_history", ["deal_id"])
    for name, key, target in LINKS:
        if not inspector.has_table(name):
            extra = [sa.Column("role", sa.String(30))] if name == "deal_contacts" else []
            op.create_table(
                name,
                sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id", ondelete="CASCADE"),
                          primary_key=True, nullable=False),
                sa.Column(key, sa.Integer, sa.ForeignKey(target, ondelete="CASCADE"), primary_key=True, nullable=False),
                *extra,
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("deals") and bind.execute(sa.text("SELECT 1 FROM deals LIMIT 1")).first():
        warnings.warn("Dropping populated deals; rep-entered deal data will be lost", stacklevel=2)
    for name, _key, _target in LINKS:
        if inspector.has_table(name):
            op.drop_table(name)
    if inspector.has_table("deal_stage_history"):
        op.drop_index("ix_deal_stage_history_deal_id", table_name="deal_stage_history")
        op.drop_table("deal_stage_history")
    if inspector.has_table("deals"):
        for index in ("ix_deals_stage_id", "ix_deals_owner_user_id", "ix_deals_customer_id"):
            op.drop_index(index, table_name="deals")
        op.drop_table("deals")
    if inspector.has_table("pipeline_stages"):
        op.drop_table("pipeline_stages")
