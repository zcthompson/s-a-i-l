"""Technology dependency models (S-A-I-L).

Persistent technology-to-technology relationships per customer
(PLAN_FEATURE_ENHANCMENTS.md — "technology dependency relationships").

A dependency row says one technology item in a customer's inventory
relates to another (source -> target) under a controlled
``relationship_type`` (e.g. "runs_on", "manages", "consumes_storage").
It is authoritative customer data, not a visualization artifact:

- canonical orientation — the service enforces one row per
  (source, target, relationship_type); the mirrored direction of the
  same logical relationship is rejected, so a relationship is never
  stored twice (the graph projection dedups at the source);
- provenance + epistemics — ``source``/``date_observed`` record how the
  relationship was established; ``verification_state`` distinguishes
  verified facts from inferred/unverified observations, with
  ``confidence`` (0.0-1.0) for inferred rows (charter §4: inference is
  explicitly represented, never silently becomes fact);
- business value beyond the graph — migration/displacement analysis
  ("what runs on the EOL vSphere?") consumes the same rows.
"""

import sqlalchemy as sa
from sqlalchemy.orm import relationship

from backend.models.use_case import Base

# ── Controlled vocabulary ─────────────────────────────────────────────────
# Free-form String column (same convention as customer_technology.py) so the
# vocabulary can grow without a destructive migration; the service layer
# validates against this list (single source of truth in this module).
# Types are directional: source -> target reads as
# "source <relationship> target" (e.g. "vCenter manages vSphere").
DEPENDENCY_TYPES = [
    "runs_on",              # source runs on target (platform/host)
    "hosts",                # source hosts target (inverse of runs_on)
    "manages",              # source manages/controls target
    "consumes_storage",     # source consumes storage provided by target
    "provides_storage",     # source provides storage consumed by target
    "consumes_compute",     # source consumes compute provided by target
    "provides_compute",     # source provides compute consumed by target
    "integrates_with",      # source integrates with target (loose coupling)
    "automates",            # source automates operations on target
    "protects",             # source protects/backups target
    "depends_on",           # generic directional dependency
    "associated_with",      # undirected association (no meaningful direction)
]


def _iso(value):
    """ISO-8601 format a (possibly None) date/datetime for to_dict output."""
    return value.isoformat() if value is not None else None


class TechnologyDependency(Base):
    """One technology-to-technology relationship for a customer (S-A-I-L).

    ``source_id`` / ``target_id`` reference ``customer_technologies`` rows
    of the SAME customer (enforced in the service layer; cross-customer
    links are rejected). ``relationship_type`` is the controlled
    vocabulary value. Unknown attributes stay NULL — never fabricated.
    """

    __tablename__ = "technology_dependencies"

    id = sa.Column(sa.Integer, primary_key=True, nullable=False, index=True)
    customer_id = sa.Column(
        sa.Integer,
        sa.ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id = sa.Column(
        sa.Integer,
        sa.ForeignKey("customer_technologies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_id = sa.Column(
        sa.Integer,
        sa.ForeignKey("customer_technologies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relationship_type = sa.Column(sa.String(50), nullable=False)
    verification_state = sa.Column(
        sa.String(20), nullable=False, default="verified"
    )
    confidence = sa.Column(sa.Float, nullable=True)  # 0.0-1.0 for inferred rows
    source_provenance = sa.Column(sa.String(255), nullable=True)  # e.g. "discovery call"
    date_observed = sa.Column(sa.Date, nullable=True)
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

    # Canonical orientation: one row per (source, target, relationship_type).
    # The mirror direction of the same logical relationship is rejected in
    # the service layer, so a relationship is never stored twice.
    __table_args__ = (
        sa.UniqueConstraint(
            "source_id", "target_id", "relationship_type",
            name="uq_technology_dependencies_src_tgt_type",
        ),
        {"sqlite_autoincrement": True},
    )

    source = relationship(
        "CustomerTechnology",
        foreign_keys=[source_id],
        lazy="joined",
        uselist=False,
    )
    target = relationship(
        "CustomerTechnology",
        foreign_keys=[target_id],
        lazy="joined",
        uselist=False,
    )

    def to_dict(self) -> dict:
        """Serialize to a plain dict (graph projection + UI consume this)."""
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "source_id": self.source_id,
            "source_name": self.source.name if self.source else None,
            "source_vendor": self.source.vendor if self.source else None,
            "target_id": self.target_id,
            "target_name": self.target.name if self.target else None,
            "target_vendor": self.target.vendor if self.target else None,
            "relationship_type": self.relationship_type,
            "verification_state": self.verification_state,
            "confidence": self.confidence,
            "source_provenance": self.source_provenance,
            "date_observed": _iso(self.date_observed),
            "notes": self.notes,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }
