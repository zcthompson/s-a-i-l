"""Third-Party Professional Services models (S-A-I-L Sales section).

Structured, customer-scoped registry of external professional-service
engagements (SIs, MSPs, consulting partners):

- Engagements are a customer-associated fact set, exactly like
  ``sales_notes`` and ``customer_technologies``. ``CustomerUser`` remains
  the sole user→customer authority; the ``ps_admin`` global
  role (service-layer value, §4.5) is the only cross-account reader/writer
  for this surface.
- Controlled vocabularies (categories, statuses, billing models, document
  types) are free-form columns with service-layer validation — the exact
  ``CATEGORIES`` mechanism from ``sales_note.py`` (grows without a
  destructive migration).
- Unknown stays unknown: every nullable field stays NULL
  until a user enters a value. No defaults for dates, references, or fees.
  Recording a user-entered figure is not fabrication.
- ``verification_state`` follows the sales_note.py item-18 precedent
  (verified / inferred / unverified).
- Documents (POs, SOWs, ...) are tracked artifacts stored store-first in
  the DB row (customer-knowledge ``file_data`` precedent); no text
  extraction this release.
"""

import sqlalchemy as sa
from sqlalchemy.orm import relationship

from backend.models.use_case import Base, UseCase

# Controlled vocabulary for engagement service categories
# (user baseline technical/virtualization/
# automation + standard IT service-catalog domains). Stored as free-form
# String(50) so the vocabulary can grow without a destructive migration; the
# service layer validates against this list.
SERVICE_CATEGORIES = [
    "technical",
    "virtualization",
    "automation",
    "cloud",
    "infrastructure",
    "network",
    "security",
    "data_analytics",
    "application_development",
    "managed_services",
]

ENGAGEMENT_STATUSES = [
    "planned",
    "active",
    "completed",
    "cancelled",
    "pending",
]

# Billing model: T&M (time & materials) or fixed cost, on a 30-day (monthly)
# billing cycle. ``fee_amount`` is always the monthly (30-day) figure.
BILLING_MODELS = ["tm", "fixed"]

# Tracked document types (POs, SOWs, and other engagement documents).
DOCUMENT_TYPES = [
    "po",
    "sow",
    "contract",
    "change_order",
    "invoice",
    "statement",
    "other",
]

# Reuse the single authoritative verification-state vocabulary
# (sales_note.py item-18 precedent).
VERIFICATION_STATES = ["verified", "inferred", "unverified"]


third_party_service_use_cases = sa.Table(
    "third_party_service_use_cases",
    Base.metadata,
    sa.Column(
        "service_id",
        sa.Integer,
        sa.ForeignKey("third_party_services.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    sa.Column(
        "use_case_id",
        sa.Integer,
        sa.ForeignKey("use_cases.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
)


def _iso(value):
    """ISO-8601 format a (possibly None) date/datetime value."""
    return value.isoformat() if value is not None else None


class ThirdPartyService(Base):
    """Third-party professional-service engagement scoped to a customer."""

    __tablename__ = "third_party_services"
    # IDs are never reissued (ER-12): retained references must not attach to a new row.
    __table_args__ = {"sqlite_autoincrement": True}

    id = sa.Column(sa.Integer, primary_key=True, nullable=False, index=True)
    customer_id = sa.Column(
        sa.Integer,
        sa.ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vendor_name = sa.Column(sa.String(255), nullable=False)
    service_category = sa.Column(sa.String(50), nullable=False)
    engagement_status = sa.Column(
        sa.String(20), nullable=False, default="active"
    )
    description = sa.Column(sa.Text, nullable=False)
    sow_reference = sa.Column(sa.String(255), nullable=True)
    contract_reference = sa.Column(sa.String(255), nullable=True)
    started_on = sa.Column(sa.Date, nullable=True)
    ended_on = sa.Column(sa.Date, nullable=True)
    # T&M or fixed cost on a 30-day (monthly) cycle; NULL until known.
    billing_model = sa.Column(sa.String(20), nullable=True)
    # The monthly (30-day billing period) amount; NULL until known.
    fee_amount = sa.Column(sa.Float, nullable=True)
    verification_state = sa.Column(
        sa.String(20), nullable=False, default="verified"
    )
    notes = sa.Column(sa.Text, nullable=True)
    created_by = sa.Column(sa.String(255), nullable=True)
    created_at = sa.Column(
        sa.DateTime,
        nullable=False,
        server_default=sa.func.current_timestamp(),
    )
    updated_at = sa.Column(
        sa.DateTime,
        nullable=False,
        server_default=sa.func.current_timestamp(),
        onupdate=sa.func.current_timestamp(),
    )

    customer = relationship("Customer", lazy="select")
    documents = relationship(
        "ThirdPartyServiceDocument",
        back_populates="service",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )
    related_use_cases = relationship(
        UseCase,
        secondary=third_party_service_use_cases,
        lazy="select",
    )

    @property
    def related_use_case_ids(self):
        """Ids of the linked use cases (junction)."""
        return [u.id for u in self.related_use_cases]

    def to_dict(self) -> dict:
        """Serialize to a plain dict (route responses + readiness context)."""
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "vendor_name": self.vendor_name,
            "service_category": self.service_category,
            "engagement_status": self.engagement_status,
            "description": self.description,
            "sow_reference": self.sow_reference,
            "contract_reference": self.contract_reference,
            "started_on": _iso(self.started_on),
            "ended_on": _iso(self.ended_on),
            "billing_model": self.billing_model,
            "fee_amount": self.fee_amount,
            "verification_state": self.verification_state,
            "notes": self.notes,
            "created_by": self.created_by,
            "related_use_case_ids": self.related_use_case_ids,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class ThirdPartyServiceDocument(Base):
    """Tracked document (PO/SOW/contract/...) attached to one engagement.

    Store-first: the original file bytes are persisted in the DB row
    (customer-knowledge ``file_data`` precedent). ``file_data`` is never
    serialized by ``to_dict`` (the knowledge model's ``to_dict`` omits the
    blob the same way).
    """

    __tablename__ = "third_party_service_documents"

    id = sa.Column(sa.Integer, primary_key=True, nullable=False, index=True)
    service_id = sa.Column(
        sa.Integer,
        sa.ForeignKey("third_party_services.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalized for direct customer-scoped authorization checks
    # (mirrors customer_knowledge).
    customer_id = sa.Column(
        sa.Integer,
        sa.ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_type = sa.Column(sa.String(30), nullable=False)
    file_name = sa.Column(sa.String(255), nullable=False)
    file_data = sa.Column(sa.LargeBinary, nullable=False)
    title = sa.Column(sa.String(255), nullable=True)
    uploaded_by = sa.Column(sa.String(255), nullable=True)
    created_at = sa.Column(
        sa.DateTime,
        nullable=False,
        server_default=sa.func.current_timestamp(),
    )

    service = relationship("ThirdPartyService", back_populates="documents")

    def to_dict(self) -> dict:
        """Serialize to a plain dict — NEVER includes file_data."""
        return {
            "id": self.id,
            "service_id": self.service_id,
            "customer_id": self.customer_id,
            "document_type": self.document_type,
            "file_name": self.file_name,
            "title": self.title,
            "uploaded_by": self.uploaded_by,
            "created_at": _iso(self.created_at),
        }
