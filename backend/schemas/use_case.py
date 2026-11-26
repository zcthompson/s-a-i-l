"""Pydantic schemas for API request/response validation."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ORMBaseModel(BaseModel):
    """Base model with from_attributes enabled for SQLAlchemy ORM serialization."""
    model_config = ConfigDict(from_attributes=True)


class UserCreate(ORMBaseModel):
    """Schema for creating a new user."""
    username: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=12)
    display_name: str | None = Field(None, max_length=100)
    department: str | None = Field(None, max_length=100)


class UserResponse(ORMBaseModel):
    """Schema for user API responses."""
    id: int
    username: str
    # Nullable: name-only pending owners (prod-seed) carry no email until the
    # operator fills it in. SQLite UNIQUE treats NULLs as distinct.
    email: str | None = None
    display_name: str | None = None
    department: str | None = None
    role: str = "user"
    sales_role: str | None = None
    is_admin: int
    approved: int
    created_at: datetime
    is_active: int
    # 0.2.0 federated identity (docs/archive/PLAN_LDAP_AD_AUTH.md): 'local' | 'ldap'.
    # Additive — pre-0.2.0 clients ignore the extra field.
    auth_provider: str = "local"


class UserUpdate(ORMBaseModel):
    """Admin user-management edit payload (all fields optional)."""
    display_name: str | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=255)
    department: str | None = Field(None, max_length=100)
    # Global role: admin (global privileges), user (assigned customers),
    # auditor (read-only), ps_admin (third-party admin — cross-account access
    # to the 3rd-party professional services surface only, §4.5). Setting
    # role to "admin" also sets is_admin=1; any other role clears it (single
    # source of admin authority preserved).
    role: str | None = Field(
        None, pattern="^(admin|user|auditor|ps_admin)$"
    )
    sales_role: str | None = Field(
        None, pattern="^(rep|inside_sales|sales_manager|auditor|sales_ops|sales_admin)$"
    )


class UserCreateAdmin(ORMBaseModel):
    """Global-admin user creation payload (POST /api/auth/users/, 0.2.11).

    The operator's in-app path for adding people the seed import missed
    (e.g. real managers after the 2026-10-14 org correction). ``email`` is
    optional (name-only pending users follow the established prod-seed
    pattern); ``role='admin'`` sets is_admin=1 (single source of admin
    authority); ``approved``/``is_active`` let the admin create either an
    immediately usable account or a pending one (default: pending, inactive —
    the operator then approves from Pending, mirroring seeded users).
    """
    username: str = Field(..., min_length=1, max_length=100)
    email: str | None = Field(None, max_length=255)
    password: str = Field(..., min_length=12)
    display_name: str | None = Field(None, max_length=100)
    department: str | None = Field(None, max_length=100)
    role: str = Field("user", pattern="^(admin|user|auditor|ps_admin)$")
    sales_role: str | None = Field(
        None, pattern="^(rep|inside_sales|sales_manager|auditor|sales_ops|sales_admin)$"
    )
    approved: bool = False
    is_active: bool = False


class UserPasswordReset(ORMBaseModel):
    """Admin-initiated password reset payload."""
    new_password: str = Field(..., min_length=12)


class LoginRequest(ORMBaseModel):
    """Schema for login."""
    username: str
    password: str


class LoginResponse(ORMBaseModel):
    """Schema for login response."""
    username: str
    # Nullable defensively: a user row with no stored email (pending import)
    # cannot authenticate locally, but directory-provisioned rows surface the
    # DB value verbatim — never 500 on serialization.
    email: str | None = None
    display_name: str | None = None
    token: str
    department: str | None = None
    is_admin: bool = False
    # Global role (0.1.6, additive — old clients ignore the new field):
    # drives the frontend's ps_admin render gates. No JWT payload change;
    # old sessions carry no claim, the live DB value is what matters.
    role: str = "user"
    # 2026-11-01 (additive — old clients ignore the new field): the caller's
    # sales role (rep/inside_sales/sales_manager/sales_ops/auditor/
    # sales_admin) — drives the alias-section write gate on the FE
    # (owner, sales admin, or admin). No JWT payload change.
    sales_role: str | None = None


class UseCaseCreate(ORMBaseModel):
    """Schema for creating a new use case."""
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    customer_id: int | None = None
    department_id: int | None = None
    department: str | None = None
    status: str | None = None
    goals: list[str] | None = None
    challenges: list[str] | None = None
    pain_points: list[str] | None = None
    impact_category: str | None = Field(None, max_length=50)
    impact_description: str | None = None
    estimated_savings: float | None = None
    estimated_revenue: float | None = None
    timeline_estimate: str | None = None
    # Technology tracking fields (WP27+)
    tech_stack: dict | None = None
    devices: dict | None = None
    software: dict | None = None
    vendor: str | None = Field(None, max_length=255)
    # Optional pre-computed scores (for testing / direct scoring without AI)
    scores: dict | None = None
    overall_score: float | None = None


class UseCaseUpdate(ORMBaseModel):
    """Schema for updating an existing use case."""
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    customer_id: int | None = None
    department_id: int | None = None
    department: str | None = None
    status: str | None = None
    goals: list[str] | None = None
    challenges: list[str] | None = None
    pain_points: list[str] | None = None
    impact_category: str | None = None
    impact_description: str | None = None
    estimated_savings: float | None = None
    estimated_revenue: float | None = None
    timeline_estimate: str | None = None
    # Technology tracking fields (WP27+)
    tech_stack: dict | None = None
    devices: dict | None = None
    software: dict | None = None
    vendor: str | None = Field(None, max_length=255)
    # Optional pre-computed scores
    scores: dict | None = None
    overall_score: float | None = None


class UseCaseResponse(ORMBaseModel):
    """Schema for use case API responses."""
    id: int
    title: str
    description: str | None = None
    customer_id: int | None = None
    customer_name: str | None = None
    department_id: int | None = None
    department: str | None = None
    status: str
    goals: list[str] | None = None
    challenges: list[str] | None = None
    pain_points: list[str] | None = None
    impact_category: str | None = None
    impact_description: str | None = None
    estimated_savings: float | None = None
    estimated_revenue: float | None = None
    timeline_estimate: str | None = None
    # Technology tracking fields (WP27+)
    tech_stack: dict | None = None
    devices: dict | None = None
    software: dict | None = None
    vendor: str | None = None
    scores: dict | None = None
    overall_score: float | None = None
    scored_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None
    # Assessment round membership (audit P1-2: the list route's
    # UseCaseResponse used to strip these; to_dict() provides both)
    assessment_id: int | None = None
    assessment_name: str | None = None
    # Part 13 WS5 (R5/R8): round type — 'ai' (default incl. legacy NULL) |
    # 'generic'; AI-only surfaces gate on this from the payload alone.
    assessment_type: str = "ai"


class ScoringRequest(ORMBaseModel):
    """Schema for scoring a use case."""
    use_case_id: int


class DimensionScore(ORMBaseModel):
    """Individual dimension score."""
    name: str
    score: float = Field(..., ge=0, le=10)
    weight: float = Field(..., ge=0, le=1)
    description: str


class ScoringResponse(ORMBaseModel):
    """Schema for scoring API responses."""
    dimension_scores: list[dict] | None = None
    overall_score: float = 0.0
    reasoning: str | None = None
    scored_at: datetime | None = None
    recommendations: list[str] | None = None


class DimensionInfo(ORMBaseModel):
    """A scoring dimension definition (name + weight) as served by
    GET /api/scoring/dimensions/ (audit P1-3: was untyped ``list``)."""
    name: str
    weight: float


class CustomerCreate(ORMBaseModel):
    """Schema for creating a new customer."""
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    # Industry vertical (WP19) — validated case-insensitively against
    # backend.verticals.VERTICALS in the route; stored canonical-case.
    vertical: str | None = Field(None, max_length=100)
    # Sales branch home (free text; see /api/customers/branches/ for the
    # selectable reference list).
    branch: str | None = Field(None, max_length=100)


class CustomerUpdate(ORMBaseModel):
    """Schema for updating an existing customer."""
    description: str | None = None
    vertical: str | None = Field(None, max_length=100)
    branch: str | None = Field(None, max_length=100)


class CustomerResponse(ORMBaseModel):
    """Schema for customer API responses."""
    id: int
    name: str
    description: str | None = None
    vertical: str | None = None
    branch: str | None = None
    sales_area: str | None = None
    primary_subsidiary: str | None = None
    primary_rep: str | None = None
    rep_sales_role: str | None = None
    manager_name: str | None = None
    inside_sales: list[dict] = Field(default_factory=list)
    sales_ops: list[dict] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    use_case_count: int = 0
    departments: list[str] = []
    total_impact: float = 0.0
    # Part 14 (A4): raw alias strings, sorted. Additive — every existing
    # consumer is unchanged; the list payload carries this via ONE batched
    # query (no N+1), the detail response via a single read.
    aliases: list[str] = []


# ── WP19 — template-assessment bootstrap response ────────────────────────────


class BootstrapDepartmentOut(ORMBaseModel):
    """A department entry in the bootstrap result (created or reused)."""
    name: str
    created: bool


class BootstrapUseCaseOut(ORMBaseModel):
    """A seeded draft use case entry in the bootstrap result."""
    id: int
    title: str
    department: str | None = None


class BootstrapResultOut(ORMBaseModel):
    """POST /customers/{name}/assessments/from-template/ response (WP19).

    The service returns a plain dict; this model pins the wire shape so the
    backend and the frontend `BootstrapResult` type cannot drift apart
    (Codex review P2-2, 2026-08-29).
    """
    assessment_id: int
    assessment_name: str
    departments: list[BootstrapDepartmentOut]
    use_cases: list[BootstrapUseCaseOut]
    # WP21 — example use cases pre-seeded into vertical departments that the
    # per-goal seeding left empty (vertical-determined; fill-empty-only).
    preseeded: list[BootstrapUseCaseOut] = Field(default_factory=list)
    count: int


class DepartmentCreate(ORMBaseModel):
    """Schema for creating a new department."""
    name: str = Field(..., min_length=1, max_length=100)
    customer_name: str = Field(..., min_length=1, max_length=255)


class DepartmentUpdate(ORMBaseModel):
    """Schema for updating an existing department."""
    name: str = Field(..., min_length=1, max_length=100)


class DepartmentResponse(ORMBaseModel):
    """Schema for department API responses."""
    id: int
    name: str
    customer_id: int
    created_at: datetime | None = None
    use_case_count: int = Field(default=0)


class ScoredUseCaseResponse(ORMBaseModel):
    """Combined use case with scores."""
    use_case: UseCaseResponse | None = None
    scores: ScoringResponse | None = None


class ManualScoreRequest(ORMBaseModel):
    """Schema for manually overriding a use case's scores."""
    use_case_id: int
    scores: dict
    overall_score: float
    reasoning: str | None = None


class ManualScoreResponse(ORMBaseModel):
    """Response after manual score override."""
    use_case: UseCaseResponse | None = None
    scores: ScoringResponse | None = None
    is_manual: bool = True


class ScoringValidationRequest(ORMBaseModel):
    """Schema for validating scoring AI responses."""
    scores: dict | None = None


class ScoringValidationResponse(ORMBaseModel):
    """Validation result for scoring responses."""
    is_valid: bool
    errors: list[str] | None = None
    warnings: list[str] | None = None


class ScoreHistoryEntry(ORMBaseModel):
    """Individual score history entry."""
    id: int
    use_case_id: int
    score: float
    scored_at: datetime | None = None
    scored_by: str
    is_manual: bool
    reasoning: str | None = None
    status: str
    dimension_scores: list[dict] | None = None


class DimensionConfigCreate(ORMBaseModel):
    """Schema for creating a new dimension config."""
    name: str
    weight: float
    version: str = "1"


class DimensionConfigResponse(ORMBaseModel):
    """Schema for dimension config responses."""
    id: int
    version: str
    name: str
    weight: float
    is_active: bool
    created_at: datetime | None = None
