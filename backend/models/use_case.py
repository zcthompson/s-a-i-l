"""SQLAlchemy models for S-A-I-L (Sales Analytics and Intelligence Launchpad)."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from backend.config import get_settings
from backend.database import create_engine

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "%(table_name)s_%(column_0_name)s_key",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}
Base = declarative_base(metadata=MetaData(naming_convention=NAMING_CONVENTION))


class Customer(Base):
    """Top-level: Customer/client organization."""
    __tablename__ = "customers"
    # Retained audit evidence must never attach to a replacement account.
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, nullable=False, index=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    # Industry vertical — one of backend.verticals.VERTICALS, or NULL.
    vertical = Column(String(100), nullable=True)
    # Sales branch home (e.g. "BR20 - Example Customer H") — denormalized reference
    # value for the create-customer dropdown (prod-seed). Nullable; not a hard
    # FK to the ``branches`` reference table (see Branch model + migration
    # f0a1b2c3d4e5).
    branch = Column(String(100), nullable=True)
    # Sales-structure re-seed 2026-10-26 (updated_structure_accounts.xlsx):
    # the customer's Sales Area # under its rep (3-digit area code; NULL =
    # unassigned/unknown — the file's 'TBD' marker is not a value) and the
    # legal-entity primary subsidiary (e.g. "CR01 - Example Customer M, Inc.").
    # INFORMATIONAL ONLY: no authorization or filtering semantics
    # (CustomerUser remains the sole authority, as for branch/tech_profile).
    sales_area = Column(String(20), nullable=True)
    primary_subsidiary = Column(String(255), nullable=True)
    # Technology profile (Layer 1) — customer technology
    # landscape. INFORMATIONAL ONLY: does not participate in CustomerUser
    # authorization, customer visibility, or filtering
    # (CustomerUser remains the sole authoritative user-to-customer model).
    tech_profile = Column(JSON, nullable=True, comment="Customer technology profile (informational only)")
    # "needs_review" marks placeholder accounts whose primary
    # owner is not yet confirmed (admin ownership-review queue). NULL = normal.
    ownership_status = Column(String(20), nullable=True, default=None)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # One Customer has many Departments
    departments = relationship(
        "Department",
        back_populates="customer",
        cascade="all, delete-orphan",
        foreign_keys="[Department.customer_id]"
    )

    # One Customer has many UseCases
    use_cases = relationship(
        "UseCase",
        back_populates="customer",
        cascade="all, delete-orphan",
        foreign_keys="[UseCase.customer_id]"
    )

    # One Customer has many users (via junction table)
    users = relationship(
        "CustomerUser",
        back_populates="customer",
        cascade="all, delete-orphan",
        foreign_keys="CustomerUser.customer_id"
    )

    # One Customer has many Projections
    projections = relationship(
        "Projection",
        back_populates="customer",
        cascade="all, delete-orphan",
        foreign_keys="Projection.customer_id"
    )

    readiness_insight = relationship(
        "ReadinessInsight",
        back_populates="customer",
        cascade="all, delete-orphan",
        uselist=False,
        foreign_keys="ReadinessInsight.customer_id",
    )

    # One Customer has many Assessment rounds
    assessments = relationship(
        "CustomerAssessment",
        back_populates="customer",
        cascade="all, delete-orphan",
        foreign_keys="CustomerAssessment.customer_id"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "vertical": self.vertical,
            "branch": self.branch,
            "sales_area": self.sales_area,
            "primary_subsidiary": self.primary_subsidiary,
            "tech_profile": self.tech_profile,
            "ownership_status": self.ownership_status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "user_count": len(self.users) if self.users else 0,
        }


class Branch(Base):
    """Reference table of selectable sales-branch values.

    Imported from the customer seed CSV so the create-customer form can offer
    branches as a dropdown (mirrors the /api/customers/verticals/ endpoint).
    ``Customer.branch`` holds the same free-text value but is NOT a hard FK
    here — a new customer may be created against any branch string.
    """
    __tablename__ = "branches"

    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Department(Base):
    """Middle layer: Department within a customer."""
    __tablename__ = "departments"
    # IDs are never reissued (ER-12): retained references must not attach to a new row.
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    customer_id = Column(Integer, ForeignKey('customers.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Back-reference to Customer
    customer = relationship("Customer", back_populates="departments")

    # One Department has many UseCases
    use_cases = relationship(
        "UseCase",
        back_populates="department_obj",
        cascade="all, delete-orphan",
        foreign_keys="[UseCase.department_id]"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "customer_id": self.customer_id,
            "customer_name": self.customer.name if self.customer else None,
            "use_case_count": len(self.use_cases) if self.use_cases else 0,
        }


class User(Base):
    """Application user with authentication and role management."""
    __tablename__ = "users"
    # A deleted user's ID must never be reissued: retained references would
    # otherwise attach reporting or access to an unrelated new user.
    __table_args__ = (UniqueConstraint("external_id", name="uq_users_external_id"),
                      {"sqlite_autoincrement": True})

    id = Column(Integer, primary_key=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    # Nullable since the prod-seed (real-customer import): a customer's Owner
    # (sales rep) is seeded name-only (pending) until the operator fills in
    # contact details. SQLite UNIQUE treats NULLs as distinct, so many
    # name-only pending users coexist legally.
    email = Column(String(255), unique=True, nullable=True, index=True)
    # NULL for directory-managed rows (auth_provider='ldap'): the directory is
    # the password authority, so JIT-provisioned rows store no local hash.
    # Local rows always carry a hash (local-first precedence).
    hashed_password = Column(String(255), nullable=True)
    display_name = Column(String(100), nullable=True)
    department = Column(String(100), nullable=True)
    # Role: admin (global), user (assigned customers), auditor (read-only,
    # granted), ps_admin (3rd-party professional services, cross-account on
    # that surface only).
    role = Column(String(20), default="user", nullable=False, server_default="user")
    # Sales role (shift to global customer management, phase 2). ORTHOGONAL to
    # is_admin: a sales-manager NEVER sets is_admin=1 —
    # is_admin stays the exclusive system-admin authority. Values:
    #   'rep' (default sales account owner) | 'inside_sales' | 'sales_manager'
    #   | 'auditor' | None (non-sales: admin / ps_admin / plain user).
    sales_role = Column(String(20), nullable=True)
    is_admin = Column(Integer, default=0)
    approved = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Integer, default=1)
    # ── Federated identity (LDAP/AD as an additional provider) ──
    # 'local' | 'ldap'. Drives provider resolution on /login/; local rows
    # default to 'local' (pre-existing accounts are untouched).
    auth_provider = Column(String(20), nullable=False, server_default="local")
    # Stable directory entry id — AD objectGUID (hex-encoded) or LDAP entry
    # UUID. Unique, nullable. Powers idempotent JIT link + admin re-link.
    external_id = Column(String(64), nullable=True)
    # Audit trail: last time this user signed in through the directory.
    last_directory_login_at = Column(DateTime, nullable=True)

    # Relationships to customer-user junction table
    owned_customers = relationship(
        "CustomerUser",
        back_populates="user",
        foreign_keys="CustomerUser.user_id",
        cascade="all, delete-orphan"
    )
    # Users who have granted access to this user (via granted_by FK)
    granted_users = relationship(
        "CustomerUser",
        back_populates="granted_by_user",
        foreign_keys="CustomerUser.granted_by",
        cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "display_name": self.display_name,
            "department": self.department,
            "role": self.role,
            "sales_role": self.sales_role,
            "is_admin": self.is_admin,
            "approved": self.approved,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_active": self.is_active,
            # federated identity: 'local' | 'ldap' (admin UI provider
            # column — directory rows show "managed by directory").
            "auth_provider": self.auth_provider or "local",
        }


# ── Customer-User Junction Table ────────────────────────────────────────────────

class CustomerUser(Base):
    """Junction table: many-to-many between Customer and User with role assignment."""
    __tablename__ = "customer_users"

    id = Column(Integer, primary_key=True, nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), default="member", nullable=False, server_default="member")
    # Role within this customer: "owner" | "member" | "auditor"
    granted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    granted_at = Column(DateTime, default=datetime.utcnow)

    # Relationships (foreign_keys required because granted_by also points to users.id)
    customer = relationship("Customer", back_populates="users")
    user = relationship("User", back_populates="owned_customers", foreign_keys="CustomerUser.user_id")
    granted_by_user = relationship("User", back_populates="granted_users", foreign_keys="CustomerUser.granted_by")

    def to_dict(self):
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "customer_name": self.customer.name if self.customer else None,
            "user_id": self.user_id,
            "username": self.user.username if self.user else None,
            "role": self.role,
            "granted_by": self.granted_by,
            "granted_at": self.granted_at.isoformat() if self.granted_at else None,
        }


class Projection(Base):
    """Customer AI readiness projection with 30-day forecasts."""
    __tablename__ = "projections"

    id = Column(Integer, primary_key=True, nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey('customers.id', ondelete='CASCADE'), nullable=False, index=True)
    customer_name = Column(String(255), nullable=False, index=True)
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    projection_data = Column(JSON, nullable=False)
    status = Column(String(20), default="completed", server_default="completed", nullable=False)
    # status: "pending" | "completed" | "failed"

    # Relationships
    customer = relationship("Customer", back_populates="projections")

    def to_dict(self):
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "customer_name": self.customer.name if self.customer else None,
            "generated_at": self.generated_at.isoformat(),
            "projection_data": self.projection_data,
            "status": self.status,
        }


class ReadinessInsight(Base):
    """Persisted organization-wide readiness insight for one customer."""
    __tablename__ = "readiness_insights"
    __table_args__ = (UniqueConstraint("customer_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    customer_id = Column(
        Integer,
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    customer_name = Column(String(255), nullable=False)
    insight_data = Column(JSON, nullable=False)
    data_fingerprint = Column(String(64), nullable=False, index=True)
    model = Column(String(100), nullable=True)
    generated_by = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="completed")
    generated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="readiness_insight")

    def to_dict(self):
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "insight_data": self.insight_data,
            "data_fingerprint": self.data_fingerprint,
            "model": self.model,
            "generated_by": self.generated_by,
            "status": self.status,
            "generated_at": self.generated_at.isoformat(),
        }


class UseCase(Base):
    """Bottom layer: AI use case scoped to customer + department."""
    __tablename__ = "use_cases"
    # IDs are never reissued (ER-12): retained references must not attach to a new row.
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    customer_id = Column(Integer, ForeignKey('customers.id', ondelete='CASCADE'), nullable=True, index=True)
    # Department as a string column (legacy — deprecated, use department_id instead)
    department = Column(String(100), nullable=True)
    # FK to the Department model (primary)
    department_id = Column(Integer, ForeignKey('departments.id', ondelete='CASCADE',
                                               name='fk_use_cases_department_id_departments'), nullable=True, index=True)
    _DEPARTMENT_FIELD_DEPRECATED = True  # Flag for deprecation tracking
    status = Column(String(20), default="draft", server_default="draft", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    goals = Column(JSON, nullable=True)
    challenges = Column(JSON, nullable=True)
    pain_points = Column(JSON, nullable=True)

    impact_category = Column(String(50), nullable=True)
    impact_description = Column(Text, nullable=True)
    estimated_savings = Column(Float, nullable=True)
    estimated_revenue = Column(Float, nullable=True)
    timeline_estimate = Column(String(50), nullable=True)

    scores = Column(JSON, nullable=True)
    overall_score = Column(Float, nullable=True)
    scored_at = Column(DateTime, nullable=True)
    score_history = Column(JSON, nullable=True)
    created_by = Column(String(100), nullable=True)
    updated_by = Column(String(100), nullable=True)
    # Assessment round this use case belongs to (simplified lifecycle:
    # at most one active round per customer; see CustomerAssessment)
    assessment_id = Column(Integer, ForeignKey('assessments.id', ondelete='SET NULL'), nullable=True, index=True)

    # Technology tracking fields
    tech_stack = Column(JSON, nullable=True,
                       comment="Structured technology stack information")
    devices = Column(JSON, nullable=True,
                   comment="Device inventory and association data")
    software = Column(JSON, nullable=True,
                    comment="Software licenses and tools tracking")
    vendor = Column(String(255), nullable=True,
                   comment="Vendor or partner name")

    # Relationships
    customer = relationship(
        "Customer",
        back_populates="use_cases",
        foreign_keys="[UseCase.customer_id]",
    )
    department_obj = relationship(
        "Department",
        back_populates="use_cases",
        foreign_keys="[UseCase.department_id]",
    )
    assessment = relationship(
        "CustomerAssessment",
        back_populates="use_cases",
        foreign_keys="[UseCase.assessment_id]",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "customer_id": self.customer_id,
            "customer_name": self.customer.name if self.customer else None,
            "department_id": self.department_id,
            "department": self.department,
            "status": self.status,
            "goals": self.goals,
            "challenges": self.challenges,
            "pain_points": self.pain_points,
            "impact_category": self.impact_category,
            "impact_description": self.impact_description,
            "estimated_savings": self.estimated_savings,
            "estimated_revenue": self.estimated_revenue,
            "timeline_estimate": self.timeline_estimate,
            "scores": self.scores,
            "overall_score": self.overall_score,
            "scored_at": self.scored_at.isoformat() if self.scored_at else None,
            "score_history": self.score_history,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": self.created_by,
            "assessment_id": self.assessment_id,
            "assessment_name": self.assessment.name if self.assessment else None,
            # the round's type (legacy NULL round → 'ai').
            # Lets every use-case surface gate AI-only controls from the
            # payload alone (no extra request).
            "assessment_type": (self.assessment.assessment_type or "ai") if self.assessment else "ai",
            # Technology tracking fields
            "tech_stack": self.tech_stack,
            "devices": self.devices,
            "software": self.software,
            "vendor": self.vendor,
        }

    def set_department(self, department: str | None, department_id: int | None):
        """Set department (legacy) and department_id (primary).

        Prevents setting both simultaneously. If both are provided,
        department_id wins and department is set to None with a warning.
        """
        if department is not None and department_id is not None:
            import warnings
            warnings.warn(
                "Both department and department_id provided. "
                "department_id is preferred; department string field is deprecated.",
                DeprecationWarning,
                stacklevel=2,
            )
            self.department_id = department_id
            self.department = None
        elif department is not None:
            self.department = department
            # department_id stays as-is
        elif department_id is not None:
            self.department_id = department_id
            # Keep legacy department field in sync for display purposes
            if self.department_id is not None and self.department_obj:
                self.department = self.department_obj.name
            else:
                self.department = None


class CustomerAssessment(Base):
    """One assessment round for a customer.

    Simplified lifecycle (2026-08-20 direction): at most ONE active
    assessment per customer. To start a new round, the current one must be
    archived first (or its use cases deleted). Archived rounds are
    read-only: their use cases can no longer be edited, scored, or deleted,
    but they remain exportable through the established export endpoints.
    """
    __tablename__ = "assessments"
    # IDs are never reissued (ER-12): retained references must not attach to a new row.
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey('customers.id', ondelete='CASCADE'), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    status = Column(String(20), default="active", nullable=False)  # active | archived
    # round type — 'ai' (AI readiness / use-case
    # scoring; the default for all existing data) | 'generic' (non-AI
    # customer discovery; AI scoring/predictions/insight are refused).
    assessment_type = Column(String(20), nullable=False, default="ai", server_default="ai")
    # The round's "why" (free text; optional for either type).
    purpose = Column(Text, nullable=True)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    archived_at = Column(DateTime, nullable=True)

    customer = relationship("Customer", back_populates="assessments")
    use_cases = relationship(
        "UseCase",
        back_populates="assessment",
        foreign_keys="[UseCase.assessment_id]"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "name": self.name,
            "status": self.status,
            "assessment_type": self.assessment_type or "ai",
            "purpose": self.purpose,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
            "use_case_count": len(self.use_cases) if self.use_cases else 0,
        }


class AIPrediction(Base):
    """Persisted model-generated readiness prediction for a use case.

    Generated by the configured OpenAI-compatible model (AI endpoint in
    .env); the application never computes predictions itself.
    """
    __tablename__ = "ai_predictions"

    id = Column(Integer, primary_key=True, nullable=False, index=True)
    use_case_id = Column(Integer, ForeignKey('use_cases.id', ondelete='CASCADE'), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey('customers.id', ondelete='CASCADE'), nullable=True, index=True)
    horizon_days = Column(Integer, nullable=False)
    predicted_score = Column(Float, nullable=False)
    score_change = Column(Float, nullable=True)
    trend = Column(String(20), nullable=True)  # improving | stable | declining
    confidence = Column(Float, nullable=True)  # 0.0 - 1.0
    reasoning = Column(Text, nullable=True)
    model = Column(String(100), nullable=True)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    use_case = relationship("UseCase")
    customer = relationship("Customer")

    def to_dict(self):
        return {
            "id": self.id,
            "use_case_id": self.use_case_id,
            "use_case_title": self.use_case.title if self.use_case else None,
            "customer_id": self.customer_id,
            "horizon_days": self.horizon_days,
            "predicted_score": self.predicted_score,
            "score_change": self.score_change,
            "trend": self.trend,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "model": self.model,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def get_session():
    settings = get_settings()
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    return Session()
