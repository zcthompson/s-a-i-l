"""Account membership model — the RBAC directive's per-account role grants.

``CustomerUser`` stays the junction of record for the legacy
owner/member/auditor roles; this table ADDS the directive's role set
(primary_owner / co_owner / sales_ops / inside_sales) and the per-section
grants for inside sales. A user may hold several roles on one account, so the
unique constraint is on (user, customer, role).
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)

from backend.models.use_case import Base

MEMBERSHIP_ROLES = ("primary_owner", "co_owner", "sales_ops", "inside_sales")
ACCOUNT_SECTIONS = (
    "overview", "contacts", "opportunities", "notes",
    "intel_uploads", "activities", "competitors", "forecasts", "tasks", "strategy",
)
SECTION_LEVELS = ("read", "contribute")
MEMBERSHIP_SOURCES = ("manual", "import", "migration")


class AccountMembership(Base):
    __tablename__ = "account_memberships"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "customer_id", "role",
            name="uq_account_membership_user_customer_role",
        ),
    )

    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id = Column(
        Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role = Column(String(20), nullable=False)
    # {section: "read"|"contribute"} for inside_sales; None = every section "read".
    section_grants = Column(JSON, nullable=True)
    source = Column(String(20), nullable=False, default="manual", server_default="manual")
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "customer_id": self.customer_id,
            "role": self.role,
            "section_grants": self.section_grants,
            "source": self.source,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
