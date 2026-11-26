"""Customer alias tags (Part 14, A1).

An alias is an alternate name for a customer account — the flexibility
mechanism for vendor / NS / pipeline naming that differs from the S-A-I-L
account name, so intelligence imports can map to the existing account
instead of creating a conflicting duplicate.

``alias_norm`` carries the matching normalization (NFKC + casefold +
whitespace collapse, ``customer_alias_service.normalize_alias`` — gap #6;
the intelligence imports use the same function) and is UNIQUE
portfolio-wide, so one alias always resolves to one customer and import
matching is deterministic by construction. Migration 0030 recomputed
stored norms when the normalization became Unicode-aware (it was
lower + collapse at 0018). A2's write
rules additionally forbid an alias equal to ANY customer name (own or
other), so name-first-then-alias import matching is always deterministic
and an alias never shadows a name.
"""

from datetime import UTC, datetime

import sqlalchemy as sa

from backend.models.use_case import Base


class CustomerAlias(Base):
    __tablename__ = "customer_aliases"
    __table_args__ = (
        sa.UniqueConstraint("alias_norm", name="uq_customer_aliases_alias_norm"),
    )

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    customer_id = sa.Column(
        sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    alias = sa.Column(sa.String(255), nullable=False)
    alias_norm = sa.Column(sa.String(255), nullable=False)
    created_by = sa.Column(sa.String(100), nullable=True)
    created_at = sa.Column(sa.DateTime, nullable=False, default=lambda: datetime.now(UTC))

    def to_dict(self):
        return {
            "id": self.id,
            "alias": self.alias,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at is not None else None,
        }
