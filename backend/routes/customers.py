"""REST API routes for customer operations.

Access control (404-first, R4/Q7):
- Admin users: unrestricted access.
- Junction users: access limited to their assigned customers.
- Unauthenticated: 401.

A customer outside the caller's reach returns the same 404 as a missing one,
so a by-name probe cannot reveal existence. In-scope capability denials keep
their exact 403.
"""

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.models.customer_alias import CustomerAlias
from backend.models.sales_access import (
    InsideSalesAssignment,
    SalesOpsAssignment,
    SalesReporting,
)
from backend.models.use_case import Branch, Customer, CustomerUser, UseCase, User
from backend.schemas.use_case import (
    BootstrapResultOut,
    CustomerCreate,
    CustomerResponse,
    CustomerUpdate,
)
from backend.services import customer_access, membership_service, sales_access
from backend.services.assessment_bootstrap import (
    AssessmentBootstrapService,
    UnknownTemplateError,
)
from backend.services.assessment_service import ASSESSMENT_TYPES, AssessmentService
from backend.services.customers_service import (
    assert_customer_owner_or_admin,
    build_customer_response,
    delete_customer_with_use_cases,
    get_accessible_customers,
    get_customer_by_name,
    get_customer_use_cases,
    list_all_customers,
    prospect_name_conflict,
)
from backend.verticals import VERTICAL_DEPARTMENTS, VERTICALS, canonical_vertical


class AssessmentNameIn(BaseModel):
    name: str
    # Part 13 WS5 (R4): optional round type + purpose. Omitted → an 'ai'
    # round exactly as before; any value outside the vocabulary → 422.
    type: str | None = None
    purpose: str | None = None

    @field_validator("type")
    @classmethod
    def _check_type(cls, value):
        if value is None:
            return None
        if value not in ASSESSMENT_TYPES:
            raise ValueError(
                f"Unknown assessment type '{value}'. Must be one of: {', '.join(ASSESSMENT_TYPES)}"
            )
        return value


class TemplateAssessmentIn(BaseModel):
    template_id: str


class BootstrapResultWithTypeOut(BootstrapResultOut):
    """BootstrapResultOut + the round's type/purpose (Part 13 WS5, R6 —
    additive; the base wire shape is unchanged)."""
    assessment_type: str = "ai"
    purpose: str | None = None


def _resolve_vertical_or_422(value):
    """Empty/None → None; a known vertical (case-insensitive) → canonical
    case; anything else → HTTP 422."""
    if value is None or not str(value).strip():
        return None
    canon = canonical_vertical(value)
    if canon is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown vertical '{value}'. Must be one of: {', '.join(VERTICALS)}",
        )
    return canon


router = APIRouter(prefix="/api/customers", tags=["customers"])


def _require_user(request: Request) -> dict:
    """Return authenticated user or 401."""
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _batched_sales_context(db: Session, ids: list) -> dict:
    """Sales-structure context for a whole customer list in a FIXED number
    of batch queries (H2: the list payload must carry owner/manager/inside/
    ops without one lookup per account).

    Per-customer values match the per-customer ``build_customer_response``
    path byte-for-byte: owners in CustomerUser.id order (the batch ordering
    (customer_id, CustomerUser.id) preserves it within each customer),
    inside/ops in assignment-id order, the first reporting row per owner.
    """
    context: dict = {}
    if not ids:
        return context
    for cid, owner in (
        db.query(CustomerUser.customer_id, User)
        .select_from(CustomerUser)
        .join(User, CustomerUser.user_id == User.id)
        .filter(CustomerUser.customer_id.in_(ids), CustomerUser.role == "owner")
        .order_by(CustomerUser.customer_id, CustomerUser.id)
        .all()
    ):
        context.setdefault(cid, {}).setdefault("owners", []).append(owner)
    # The manager is the reporting row of the SELECTED owner (same rule as
    # _sales_context_fields: exactly one rep-role owner wins, else the first
    # owner in junction-id order) — never of an unselected co-owner.
    selected_owner: dict = {}
    for cid, entry in context.items():
        owners = entry["owners"]
        rep_owners = [o for o in owners if o.sales_role == "rep"]
        selected_owner[cid] = rep_owners[0] if len(rep_owners) == 1 else owners[0]
    selected_ids = {u.id for u in selected_owner.values() if u is not None}
    if selected_ids:
        managers: dict = {}
        for rep_id, manager in (
            db.query(SalesReporting.rep_user_id, User)
            .select_from(SalesReporting)
            .join(User, SalesReporting.manager_user_id == User.id)
            .filter(SalesReporting.rep_user_id.in_(selected_ids))
            .all()
        ):
            managers.setdefault(rep_id, manager)
        for cid, owner in selected_owner.items():
            if owner is not None:
                context[cid]["manager"] = managers.get(owner.id)
    for cid, user in (
        db.query(InsideSalesAssignment.customer_id, User)
        .select_from(InsideSalesAssignment)
        .join(User, InsideSalesAssignment.inside_sales_user_id == User.id)
        .filter(InsideSalesAssignment.customer_id.in_(ids))
        .order_by(InsideSalesAssignment.customer_id, InsideSalesAssignment.id)
        .all()
    ):
        context.setdefault(cid, {}).setdefault("inside", []).append(user)
    for cid, user in (
        db.query(SalesOpsAssignment.customer_id, User)
        .select_from(SalesOpsAssignment)
        .join(User, SalesOpsAssignment.user_id == User.id)
        .filter(SalesOpsAssignment.customer_id.in_(ids))
        .order_by(SalesOpsAssignment.customer_id, SalesOpsAssignment.id)
        .all()
    ):
        context.setdefault(cid, {}).setdefault("ops", []).append(user)
    return context


def _batched_aliases(db: Session, ids: list) -> dict:
    """Customer aliases for a whole list in ONE query (Part 14, A4 — the H2
    fixed-query convention: no N+1, per-customer alias lookups are a test
    failure). Rows arrive ordered (customer_id, alias), so each list is
    already the payload's sorted raw-alias order."""
    context: dict = {}
    if not ids:
        return context
    for cid, alias in (
        db.query(CustomerAlias.customer_id, CustomerAlias.alias)
        .filter(CustomerAlias.customer_id.in_(ids))
        .order_by(CustomerAlias.customer_id, CustomerAlias.alias)
        .all()
    ):
        context.setdefault(cid, []).append(alias)
    return context


@router.get("/", response_model=list[CustomerResponse])
def list_customers(
    request: Request,
    db: Session = Depends(get_db),
):
    """List all customers for admins; accessible customers for junction users."""
    user = _require_user(request)
    # Admins see ALL customers. Junction users see only their assigned ones.
    is_admin = user.get("is_admin") == 1
    if is_admin:
        customers = list_all_customers(db)
    else:
        customers = get_accessible_customers(db, user)
    # One batched query for the scoped set instead of one per customer (N+1).
    ids = [c.id for c in customers]
    uc_by_customer: dict = defaultdict(list)
    if ids:
        for uc in db.query(UseCase).filter(UseCase.customer_id.in_(ids)).all():
            uc_by_customer[uc.customer_id].append(uc)
    # H2: batched sales-structure context (owner/manager/inside/ops) so the
    # list payload carries the same sales context as the detail route —
    # a fixed number of queries, never one lookup per account.
    sales_context = _batched_sales_context(db, ids)
    # Part 14 (A4): aliases on every row via ONE batched query — the H2
    # fixed-query convention (per-customer alias lookups are a test failure).
    aliases_context = _batched_aliases(db, ids)
    return [
        build_customer_response(c, uc_by_customer.get(c.id, []),
                                sales_context=sales_context, aliases_context=aliases_context)
        for c in customers
    ]


@router.get("/verticals/")
def list_verticals(request: Request):
    """The canonical vertical list + the 4 seed departments per vertical."""
    _require_user(request)
    return {
        "verticals": list(VERTICALS),
        "departments_by_vertical": {
            name: list(depts) for name, depts in VERTICAL_DEPARTMENTS.items()
        },
    }


@router.get("/branches/")
def list_branches(
    request: Request,
    db: Session = Depends(get_db),
):
    """The selectable sales-branch reference list.

    Backs the branch dropdown on the create-customer form (mirrors
    /api/customers/verticals/). Returns every value in the ``branches``
    reference table, ordered by id (insertion order = the seed CSV's
    distinct branch list).
    """
    _require_user(request)
    rows = db.query(Branch).order_by(Branch.id).all()
    return {
        "branches": [r.name for r in rows],
        "items": [r.to_dict() for r in rows],
    }


@router.get("/{customer_name}/", response_model=CustomerResponse)
def get_customer(
    customer_name: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get a customer by name with summary stats (access-controlled)."""
    user = _require_user(request)
    customer = customer_access.read_by_name_or_404(db, user, customer_name)
    use_cases = get_customer_use_cases(db, customer)
    return build_customer_response(customer, use_cases, db)


@router.post("/", response_model=CustomerResponse, status_code=201)
def create_customer(
    data: CustomerCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a customer (system admin) or a prospect account (sales manager).

    Decision D3: an active sales manager may create a prospect. It enters the
    existing ownership-review queue (``ownership_status = needs_review``) with
    the manager as its provisional owner; an admin confirms or reassigns the
    owner there. Name/alias duplicates are refused. Other roles get 403.
    """
    user = _require_user(request)
    is_admin = user.get("is_admin") == 1
    prospect = False
    if not is_admin:
        # Re-read the role: a stale token must not grant creation.
        creator = db.query(User).filter(User.id == user.get("user_id"), User.is_active == 1).first()
        if creator is None or sales_access.effective_role({
            "is_admin": creator.is_admin, "role": creator.role, "sales_role": creator.sales_role,
        }) != "sales_manager":
            raise HTTPException(status_code=403, detail="Admin or sales manager privileges required")
        prospect = True
    existing = get_customer_by_name(db, data.name)
    if existing:
        raise HTTPException(status_code=400, detail="Customer already exists")
    if prospect:
        conflict = prospect_name_conflict(db, data.name)
        if conflict:
            raise HTTPException(status_code=400, detail=f"An account already uses this name: {conflict}")
    vertical = _resolve_vertical_or_422(data.vertical)
    customer = Customer(name=data.name, description=data.description, vertical=vertical,
                        branch=data.branch, ownership_status="needs_review" if prospect else None)
    db.add(customer)
    db.flush()
    creator_id = user.get("user_id")
    # The API-key auth path (dept restrictions) builds a user dict without
    # user_id — the key itself is the identity, so there is no user to grant
    # owner to; skip the grant rather than inserting a NULL user_id (500).
    if creator_id:
        db.add(CustomerUser(
            customer_id=customer.id, user_id=creator_id, role="owner",
            granted_by=creator_id,
        ))
        # Directive membership parity (2026-10-15 gap): the creator also
        # receives the primary_owner membership row in the SAME transaction.
        # stage_creator_membership is idempotent and never displaces an
        # existing primary owner.
        membership_service.stage_creator_membership(
            db, customer, creator_id, creator_id, request
        )
    if prospect:
        membership_service.stage_prospect_audit(db, creator_id, customer, request)
    db.commit()
    db.refresh(customer)
    return build_customer_response(customer, [], db)


@router.put("/{customer_name}/", response_model=CustomerResponse)
def update_customer(
    customer_name: str,
    data: CustomerUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update a customer. Requires CAP_METADATA (central policy; 404-first)."""
    user = _require_user(request)
    customer = customer_access.read_by_name_or_404(db, user, customer_name)
    if not sales_access.can(user, db, sales_access.CAP_METADATA, customer.id):
        raise HTTPException(status_code=403, detail="Not authorized to modify this customer")
    if data.description is not None:
        customer.description = data.description
    if data.vertical is not None:
        customer.vertical = _resolve_vertical_or_422(data.vertical)
    if data.branch is not None:
        customer.branch = data.branch
    db.commit()
    db.refresh(customer)
    use_cases = get_customer_use_cases(db, customer)
    return build_customer_response(customer, use_cases, db)


@router.delete("/{customer_name}/", status_code=204)
def delete_customer(
    customer_name: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Delete a customer. In-scope admin or owner only (404-first)."""
    user = _require_user(request)
    customer = customer_access.read_by_name_or_404(db, user, customer_name)
    try:
        assert_customer_owner_or_admin(db, customer, user)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        actor = db.query(User).filter(User.username == user["username"]).first()
        customer_id, name = customer.id, customer.name
        deleted_counts = delete_customer_with_use_cases(db, customer)
        membership_service._audit(db, actor, "customer.delete", customer_id, None,
                                  {"customer_name": name, "deleted_counts": deleted_counts}, request)
        db.commit()
    except Exception:
        db.rollback()
        raise


@router.get("/{customer_name}/use-cases/", response_model=list[dict])
def get_customer_use_cases_route(
    customer_name: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get all use cases for a customer (access-controlled)."""
    user = _require_user(request)
    customer = customer_access.read_by_name_or_404(db, user, customer_name)
    use_cases = get_customer_use_cases(db, customer)
    return [uc.to_dict() for uc in use_cases]


# ── Assessment rounds (simplified lifecycle: one active per customer) ────────

@router.get("/{customer_name}/assessments/")
def list_customer_assessments(
    customer_name: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """List the customer's assessment rounds (active + archived)."""
    user = _require_user(request)
    customer = customer_access.read_by_name_or_404(db, user, customer_name)
    return AssessmentService.list_for_customer(db, customer.id)


@router.post("/{customer_name}/assessments/", status_code=201)
def create_customer_assessment(
    customer_name: str,
    data: AssessmentNameIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Start a new assessment round.

    Requires that no active round exists — archive the current one first
    (or delete its use cases). Requires CAP_EDIT (central policy).
    """
    user = _require_user(request)
    customer = customer_access.read_by_name_or_404(db, user, customer_name)
    if not sales_access.can(user, db, sales_access.CAP_EDIT, customer.id):
        raise HTTPException(status_code=403, detail="Not authorized to modify this customer")
    try:
        assessment = AssessmentService.create(
            db, customer.id, data.name, user.get("username"),
            assessment_type=data.type or "ai", purpose=data.purpose,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return assessment.to_dict()


@router.post("/{customer_name}/assessments/from-template/", status_code=201,
             response_model=BootstrapResultWithTypeOut)
def bootstrap_template_assessment(
    customer_name: str,
    data: TemplateAssessmentIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Bootstrap a vertical-aware template assessment for the customer.

    Seeds the 4 most-likely departments for the customer's vertical and
    one draft use case per template goal. In-scope with central CAP_EDIT.
    """
    user = _require_user(request)
    customer = customer_access.read_by_name_or_404(db, user, customer_name)
    # Out-of-scope callers already got the 404 above. In-scope callers must
    # hold central CAP_EDIT (Part 13 DV wave — DV2/A8, ruling R1).
    if not sales_access.can(user, db, sales_access.CAP_EDIT, customer.id):
        raise HTTPException(status_code=403, detail="Not authorized to modify this customer")
    # Part 13 WS5 (R8 honesty): template bootstrap seeds AI use cases — it can
    # only work against an AI round. An active generic round would be seeded
    # with AI content (ensure_active returns it), so refuse with 409, naming
    # the fix. (No active round → the service creates an 'ai' round as before.)
    active = AssessmentService.get_active(db, customer.id)
    if active is not None and (active.assessment_type or "ai") == "generic":
        raise HTTPException(
            409,
            detail="An AI template cannot be seeded into a generic assessment. "
                   "Archive it (or start an AI round) first.",
        )
    try:
        return AssessmentBootstrapService.bootstrap_template_assessment(
            db, customer, data.template_id, user
        )
    except UnknownTemplateError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{customer_name}/assessments/{assessment_id}/archive/")
def archive_customer_assessment(
    customer_name: str,
    assessment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Archive the active assessment round.

    Its use cases become read-only (no edit/score/delete; they remain
    exportable through the established export endpoints).
    """
    user = _require_user(request)
    customer = customer_access.read_by_name_or_404(db, user, customer_name)
    if not sales_access.can(user, db, sales_access.CAP_EDIT, customer.id):
        raise HTTPException(status_code=403, detail="Not authorized to modify this customer")
    assessment = AssessmentService.get_by_id_for_customer(db, assessment_id, customer.id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    try:
        assessment = AssessmentService.archive(db, assessment.id, user.get("username"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return assessment.to_dict()
