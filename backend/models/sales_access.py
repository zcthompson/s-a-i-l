"""Sales access model — additive roles, reporting hierarchy, and inside-sales
assignments for the shift to global customer management (phase 2).

Design principles:
  * STRICTLY ADDITIVE. Every column/table is nullable / optional, so existing
    deployments (is_admin system admins, ps_admin, and the CustomerUser
    owner/member/auditor junction) behave EXACTLY as before until callers
    opt in by using the central resolver (backend/services/sales_access.py).
  * ``users.sales_role`` is orthogonal to ``is_admin``. A sales-manager NEVER
    sets is_admin=1; the flag stays exclusively the
    system-admin authority.
  * Relationships use stable user/customer IDs — never
    branch strings or display-name similarity.
  * ``CustomerUser`` remains the source of "explicitly granted customer
    access"; these tables add the *hierarchy / scope* layer on top.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)

from backend.models.use_case import Base


class SalesReporting(Base):
    """Rep → direct-manager reporting relationship (sales hierarchy).

    ``manager_user_id`` is the manager a rep reports to. Manager customer
    scope = customers owned by their (transitive) reports. Cycles and
    self-reporting are rejected by the service layer, not by this table.
    Unique per rep (a rep reports to exactly one manager).
    """
    __tablename__ = "sales_reporting"
    __table_args__ = (
        UniqueConstraint("rep_user_id", name="uq_sales_reporting_rep"),
    )

    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    rep_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    manager_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class InsideSalesAssignment(Base):
    """Inside-sales → customer (optionally → supported rep) assignment.

    Customer-SPECIFIC by default: supporting Rep A does
    NOT grant every customer of A. Unique per (inside_sales_user, customer).
    """
    __tablename__ = "inside_sales_assignments"
    __table_args__ = (
        UniqueConstraint(
            "inside_sales_user_id", "customer_id",
            name="uq_inside_sales_assignment",
        ),
    )

    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    inside_sales_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    # Optional: the rep this inside-sales person supports on this account.
    rep_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # True only for assignments created by the opt-in golden-seed auto-link
    # (Pass 5 of seed_accounts_v3); False for manually assigned rows.
    auto_linked = Column(Boolean, nullable=False, server_default=sa.text("false"))
    # Human-readable rationale for auto-linked assignments (outside rep's
    # last-name match), NULL for manually assigned rows.
    link_reason = Column(String(255), nullable=True)


class SalesOpsAssignment(Base):
    """Sales-ops → customer assignment (per-account contributor access).

    A sales_ops user is read-only on assigned accounts plus may write sales
    notes and contribute customer knowledge; no account editing, team
    management or ownership transfer. Unique per (user, customer).
    """
    __tablename__ = "sales_ops_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "customer_id", name="uq_sales_ops_assignment"),
        Index("ix_sales_ops_assignments_customer_id", "customer_id"),
    )

    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
