"""Technology Inventory SQLAlchemy models (S-A-I-L).

Structured, relational per-customer technology records (charter: structured
relational data, not prose or unstructured JSON). Unknown attributes are
stored as NULL — they are never fabricated (charter §4: "unknown
information stays unknown"). ``verification_state`` distinguishes verified
customer facts from inferred / unverified observations; ``confidence``
(0.0-1.0) applies to inferred items.
"""

import sqlalchemy as sa

from backend.models.use_case import Base

# ── Controlled vocabularies ────────────────────────────────────────────────
# Stored as free-form String columns so the vocabulary can grow in a later
# release without a destructive migration; the service layer validates
# against these lists (single source of truth in this module).
CATEGORIES = [
    "software",
    "hardware",
    "infrastructure",
    "cloud_platform",
    "virtualization",
    "networking",
    "storage",
    "security",
    "data_platform",
    "ai_technology",
    "operating_system",
    "management_tool",
    "automation_tool",
    "other",
]

DEPLOYMENT_MODELS = [
    "on_premise",
    "private_cloud",
    "public_cloud",
    "hybrid",
    "saas",
    "virtual_machine",
    "container",
    "bare_metal",
    "unknown",
]

LIFECYCLE_STATES = [
    "current",
    "previous_generation",
    "eol_announced",
    "eol",
    "unknown",
]

SUPPORT_STATES = [
    "under_support",
    "support_expiring",
    "no_support",
    "unknown",
]

BUSINESS_CRITICALITIES = ["critical", "high", "medium", "low"]

VERIFICATION_STATES = ["verified", "inferred", "unverified"]


def _iso(value):
    """ISO-8601 format a (possibly None) date/datetime for to_dict output."""
    return value.isoformat() if value is not None else None


class CustomerTechnology(Base):
    """Structured technology inventory item for a customer (S-A-I-L).

    One row per technology/product the customer runs (or is evaluating).
    The category is a controlled vocabulary value; the deployment model,
    lifecycle state, and support state describe where the technology lives
    and where it is in its lifecycle. ``source`` records provenance (e.g.
    "discovery call", "assessment", "customer document") and
    ``date_observed`` records when the fact was captured.
    """

    __tablename__ = "customer_technologies"
    # IDs are never reissued (ER-12): retained references must not attach to a new row.
    __table_args__ = {"sqlite_autoincrement": True}

    id = sa.Column(sa.Integer, primary_key=True, nullable=False, index=True)
    customer_id = sa.Column(
        sa.Integer,
        sa.ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Product / platform / service name (required; everything else nullable).
    name = sa.Column(sa.String(255), nullable=False)
    vendor = sa.Column(sa.String(255), nullable=True)
    category = sa.Column(sa.String(50), nullable=False)
    version_edition = sa.Column(sa.String(255), nullable=True)
    deployment_model = sa.Column(sa.String(50), nullable=True)
    quantity = sa.Column(sa.Integer, nullable=True)
    footprint = sa.Column(sa.String(255), nullable=True)  # e.g. "12 VMs", "2 sites"
    purpose = sa.Column(sa.Text, nullable=True)
    lifecycle_state = sa.Column(sa.String(50), nullable=True)
    support_state = sa.Column(sa.String(50), nullable=True)
    business_criticality = sa.Column(sa.String(50), nullable=True)
    source = sa.Column(sa.String(255), nullable=True)
    date_observed = sa.Column(sa.Date, nullable=True)
    end_of_support_date = sa.Column(sa.Date, nullable=True)
    eol_source = sa.Column(sa.String(255), nullable=True)
    verification_state = sa.Column(
        sa.String(20), nullable=False, default="unverified"
    )
    confidence = sa.Column(sa.Float, nullable=True)  # 0.0-1.0 for inferred items
    notes = sa.Column(sa.Text, nullable=True)
    created_at = sa.Column(
        sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()
    )
    updated_at = sa.Column(
        sa.DateTime,
        nullable=False,
        server_default=sa.func.current_timestamp(),
        onupdate=sa.func.current_timestamp(),
    )

    def to_dict(self) -> dict:
        """Serialize to a plain dict (for intelligence-context assembly)."""
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "name": self.name,
            "vendor": self.vendor,
            "category": self.category,
            "version_edition": self.version_edition,
            "deployment_model": self.deployment_model,
            "quantity": self.quantity,
            "footprint": self.footprint,
            "purpose": self.purpose,
            "lifecycle_state": self.lifecycle_state,
            "support_state": self.support_state,
            "business_criticality": self.business_criticality,
            "source": self.source,
            "date_observed": _iso(self.date_observed),
            "end_of_support_date": _iso(self.end_of_support_date),
            "eol_source": self.eol_source,
            "verification_state": self.verification_state,
            "confidence": self.confidence,
            "notes": self.notes,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }
