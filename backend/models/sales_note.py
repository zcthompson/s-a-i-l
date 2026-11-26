"""Sales Notes SQLAlchemy models (S-A-I-L).

Structured per-customer sales notes (CHANGELOG 0.0.80 items 16-18):
discovery information, account observations, meeting notes, technical
discussions, risks, initiatives, objections, competitive information,
follow-up items, and potential opportunities.

- ``content`` holds the ORIGINAL note text; AI-generated interpretation must
  never overwrite it (derived observations get verification_state="inferred"
  and a traceable source — item 18).
- ``verification_state`` default is "verified" — a human-authored note with
  author/source is a first-hand record. AI-generated notes must explicitly
  use "inferred"/"unverified" so generated text never silently becomes
  authoritative customer data (charter §4).
- Related technologies and use cases (initiatives) go through junction
  tables; cross-customer junctions are rejected in the service layer
  (customer isolation before any downstream consumption).
- Unknown attributes (author, source, note_date) stay NULL — never fabricated.
"""

import sqlalchemy as sa
from sqlalchemy.orm import relationship

from backend.models.customer_technology import CustomerTechnology
from backend.models.use_case import Base, UseCase

# Controlled vocabulary for note categories (CHANGELOG 0.0.80 item 16).
# Stored as free-form String(50) so the vocabulary can grow without a
# destructive migration; the service layer validates against this list.
CATEGORIES = [
    "discovery",
    "account_observation",
    "meeting",
    "technical_discussion",
    "risk",
    "initiative",
    "objection",
    "competitive",
    "follow_up",
    "opportunity",
    "other",
]

VERIFICATION_STATES = ["verified", "inferred", "unverified"]

sales_note_technologies = sa.Table(
    "sales_note_technologies",
    Base.metadata,
    sa.Column(
        "note_id",
        sa.Integer,
        sa.ForeignKey("sales_notes.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    sa.Column(
        "technology_id",
        sa.Integer,
        sa.ForeignKey("customer_technologies.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
)

sales_note_use_cases = sa.Table(
    "sales_note_use_cases",
    Base.metadata,
    sa.Column(
        "note_id",
        sa.Integer,
        sa.ForeignKey("sales_notes.id", ondelete="CASCADE"),
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


class SalesNote(Base):
    """Structured sales note scoped to a customer (S-A-I-L)."""

    __tablename__ = "sales_notes"
    # IDs are never reissued (ER-12): retained references must not attach to a new row.
    __table_args__ = {"sqlite_autoincrement": True}

    id = sa.Column(sa.Integer, primary_key=True, nullable=False, index=True)
    customer_id = sa.Column(
        sa.Integer,
        sa.ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author = sa.Column(sa.String(255), nullable=True)
    source = sa.Column(sa.String(255), nullable=True)
    note_date = sa.Column(sa.Date, nullable=True)
    category = sa.Column(sa.String(50), nullable=False)
    title = sa.Column(sa.String(255), nullable=False)
    content = sa.Column(sa.Text, nullable=False)
    verification_state = sa.Column(
        sa.String(20), nullable=False, default="verified"
    )
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

    related_technologies = relationship(
        CustomerTechnology,
        secondary=sales_note_technologies,
        lazy="select",
    )
    related_use_cases = relationship(
        UseCase,
        secondary=sales_note_use_cases,
        lazy="select",
    )

    @property
    def related_technology_ids(self):
        """Ids of the linked Technology Inventory items (junction)."""
        return [t.id for t in self.related_technologies]

    @property
    def related_use_case_ids(self):
        """Ids of the linked use cases / initiatives (junction)."""
        return [u.id for u in self.related_use_cases]

    def to_dict(self) -> dict:
        """Serialize to a plain dict (route responses + intelligence context)."""
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "author": self.author,
            "source": self.source,
            "note_date": _iso(self.note_date),
            "category": self.category,
            "title": self.title,
            "content": self.content,
            "verification_state": self.verification_state,
            "related_technology_ids": self.related_technology_ids,
            "related_use_case_ids": self.related_use_case_ids,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }
