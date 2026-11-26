"""E6 rep-owned deals (decision D2 option B) and admin-managed pipeline stages.

Deals are a distinct entity: separate from imported vendor pipeline rows and
from derived attention cards. Amounts are integer minor units with an
explicit currency and basis, never summed with vendor pipeline. Probability
is only what a rep records (D5: a stage default is a suggestion). The owner
is a user FK plus a display-name snapshot (D4); ownership grants no access.
"""

import sqlalchemy as sa

from backend.models.use_case import Base

STAGE_CLASSES = ("open", "won", "lost")
AMOUNT_BASES = ("one_time", "acv", "tcv", "mrr")
DEAL_TYPES = ("new", "expansion", "renewal", "services")
CONTACT_ROLES = ("decision_maker", "economic_buyer", "champion", "influencer", "technical", "user", "other")

DEFAULT_STAGES = (
    # key, label, class, position, suggested probability
    ("qualification", "Qualification", "open", 10, 10),
    ("discovery", "Discovery", "open", 20, 25),
    ("proposal", "Proposal", "open", 30, 50),
    ("negotiation", "Negotiation", "open", 40, 75),
    ("closed_won", "Closed Won", "won", 90, 100),
    ("closed_lost", "Closed Lost", "lost", 100, 0),
)


class PipelineStage(Base):
    __tablename__ = "pipeline_stages"
    __table_args__ = {"sqlite_autoincrement": True}

    id = sa.Column(sa.Integer, primary_key=True)
    key = sa.Column(sa.String(50), nullable=False, unique=True)
    label = sa.Column(sa.String(100), nullable=False)
    stage_class = sa.Column(sa.String(10), nullable=False)
    position = sa.Column(sa.Integer, nullable=False)
    active = sa.Column(sa.Boolean, nullable=False, default=True, server_default=sa.true())
    # D5: a suggestion shown to reps, never stored on a deal implicitly.
    default_probability = sa.Column(sa.Integer)
    created_at = sa.Column(sa.DateTime, nullable=False, server_default=sa.func.current_timestamp())
    updated_at = sa.Column(sa.DateTime, nullable=False, server_default=sa.func.current_timestamp(),
                           onupdate=sa.func.current_timestamp())


class Deal(Base):
    __tablename__ = "deals"
    __table_args__ = (sa.UniqueConstraint("customer_id", "source_key", name="uq_deal_source"),
                      {"sqlite_autoincrement": True})

    id = sa.Column(sa.Integer, primary_key=True)
    customer_id = sa.Column(sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    name = sa.Column(sa.String(255), nullable=False)
    owner_user_id = sa.Column(sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    owner_name = sa.Column(sa.String(255))
    stage_id = sa.Column(sa.Integer, sa.ForeignKey("pipeline_stages.id"), nullable=False, index=True)
    close_date = sa.Column(sa.Date)
    amount_minor = sa.Column(sa.BigInteger)
    currency = sa.Column(sa.String(3), nullable=False, default="USD", server_default="USD")
    amount_basis = sa.Column(sa.String(10))
    probability = sa.Column(sa.Integer)
    deal_type = sa.Column(sa.String(20))
    next_step = sa.Column(sa.Text)
    next_step_date = sa.Column(sa.Date)
    closed_reason = sa.Column(sa.Text)
    closed_at = sa.Column(sa.DateTime)
    source_type = sa.Column(sa.String(30))
    source_id = sa.Column(sa.Integer)
    source_key = sa.Column(sa.String(255))
    created_by = sa.Column(sa.String(100), nullable=False)
    created_at = sa.Column(sa.DateTime, nullable=False, server_default=sa.func.current_timestamp())
    updated_at = sa.Column(sa.DateTime, nullable=False, server_default=sa.func.current_timestamp(),
                           onupdate=sa.func.current_timestamp())
    version = sa.Column(sa.Integer, nullable=False, default=1, server_default="1")


class DealStageHistory(Base):
    __tablename__ = "deal_stage_history"
    __table_args__ = {"sqlite_autoincrement": True}

    id = sa.Column(sa.Integer, primary_key=True)
    deal_id = sa.Column(sa.Integer, sa.ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True)
    from_stage_id = sa.Column(sa.Integer, sa.ForeignKey("pipeline_stages.id"))
    to_stage_id = sa.Column(sa.Integer, sa.ForeignKey("pipeline_stages.id"), nullable=False)
    actor = sa.Column(sa.String(100), nullable=False)
    at = sa.Column(sa.DateTime, nullable=False)
    # Snapshot of the deal's money and date at the transition.
    amount_minor = sa.Column(sa.BigInteger)
    currency = sa.Column(sa.String(3))
    amount_basis = sa.Column(sa.String(10))
    close_date = sa.Column(sa.Date)
    note = sa.Column(sa.String(255))


def _link(name, key, target, extra=()):
    return sa.Table(
        name, Base.metadata,
        sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id", ondelete="CASCADE"),
                  primary_key=True, nullable=False),
        sa.Column(key, sa.Integer, sa.ForeignKey(target, ondelete="CASCADE"), primary_key=True, nullable=False),
        *extra,
    )


deal_contacts = _link("deal_contacts", "contact_id", "customer_contacts.id", (sa.Column("role", sa.String(30)),))
deal_tasks = _link("deal_tasks", "task_id", "customer_tasks.id")
deal_activities = _link("deal_activities", "activity_id", "customer_activities.id")
deal_notes = _link("deal_notes", "note_id", "sales_notes.id")
deal_technologies = _link("deal_technologies", "technology_id", "customer_technologies.id")

# Retained vendor identity is evidence, never a copied commercial amount.
# No import FK: deleting an import must not delete rep-entered deal evidence.
deal_vendor_evidence = sa.Table(
    "deal_vendor_evidence", Base.metadata,
    sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("import_id", sa.Integer, primary_key=True),
    sa.Column("opportunity_number", sa.String(255), primary_key=True),
)
