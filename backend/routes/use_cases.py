"""REST API routes for use case CRUD operations."""


from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.models.use_case import UseCase
from backend.schemas.use_case import (
    UseCaseCreate,
    UseCaseResponse,
    UseCaseUpdate,
)
from backend.services import sales_access
from backend.services.use_case_service import UseCaseService

router = APIRouter(prefix="/api/use-cases", tags=["use-cases"])


def _require_user(request: Request) -> dict:
    """Return authenticated user or 401."""
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _require_edit(user: dict, db: Session, customer_id: int | None, defer_outsider: bool = False) -> None:
    """403 unless the caller holds CAP_EDIT on the use case's customer.

    Unassigned use cases (no customer) have no customer to authorize against
    and keep their existing service-layer behavior.
    """
    if customer_id is None:
        return
    # ``defer_outsider`` (create only): a caller with no grant on the customer
    # falls through to the service's own access error (its message is part of
    # the existing contract); a grant holder (e.g. an auditor junction) must
    # pass the resolver gate.
    if defer_outsider and user.get("is_admin") != 1 and customer_id not in (user.get("customer_ids") or []):
        return
    if not sales_access.can(user, db, sales_access.CAP_EDIT, customer_id):
        raise HTTPException(status_code=403, detail="Not authorized to modify this customer")


def _target_customer_id(db: Session, use_case_id: int) -> int | None:
    """Customer id derived from the persisted use case (None when missing)."""
    row = db.query(UseCase.customer_id).filter(UseCase.id == use_case_id).first()
    return row[0] if row else None


@router.get("/", response_model=list[UseCaseResponse])
def list_use_cases(
    request: Request,
    skip: int = Query(0, ge=0, description="Number of records to skip (>= 0)"),
    limit: int = Query(100, ge=1, le=1000, description="Page size (1..1000)"),
    sort: str = Query("updated", description="Sort key: updated|created|score|title"),
    department: str | None = None,
    status: str | None = None,
    search: str | None = None,
    customer_id: int | None = Query(None, ge=1, description="Customer filter (positive ID)"),
    db: Session = Depends(get_db),
):
    """List use cases with optional filtering, department and customer isolation.

    ``customer_id`` is typed and positive (``ge=1``): a zero/negative value is a
    422, never silently widened to the global set (BE-02). ``skip``/``limit`` are
    bounded (``ge=0`` / ``1..1000``) so the DB is never asked for an unlimited
    or negative page (BE-03). ``sort`` selects the authoritative ordering so
    pagination pages stay stable (BE-03/FE-03: updated|created|score|title).
    """
    if sort not in ("updated", "created", "score", "title"):
        raise HTTPException(status_code=422, detail="sort must be one of: updated, created, score, title")
    user = _require_user(request)
    use_cases = UseCaseService.get_all(
        db, skip=skip, limit=limit,
        department=department, status=status, search=search,
        customer_id=customer_id, user=user, sort=sort
    )
    return [uc.to_dict() for uc in use_cases]


@router.get("/stats/")
def get_stats(
    request: Request,
    db: Session = Depends(get_db),
):
    """Get aggregate statistics with department isolation."""
    user = _require_user(request)
    return UseCaseService.get_stats(db, user=user)


@router.get("/{use_case_id}/", response_model=UseCaseResponse)
def get_use_case(
    use_case_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get a single use case by ID with department isolation."""
    user = _require_user(request)
    use_case = UseCaseService.get_by_id(db, use_case_id, user=user)
    if not use_case:
        raise HTTPException(status_code=404, detail="Use case not found")
    return use_case.to_dict()


@router.post("/", response_model=UseCaseResponse, status_code=201)
def create_use_case(data: UseCaseCreate, request: Request, db: Session = Depends(get_db)):
    """Create a new use case with customer isolation.

    404-first (R4/Q7): a customer the caller cannot reach is the same 404 as
    a missing one (previously the service's 403 fell through the defer).
    """
    user = _require_user(request)
    if data.customer_id is not None and user.get("is_admin") != 1 \
            and data.customer_id not in (user.get("customer_ids") or []):
        raise HTTPException(status_code=404, detail="Customer not found")
    _require_edit(user, db, data.customer_id, defer_outsider=True)
    use_case = UseCaseService.create(
        db,
        title=data.title,
        description=data.description,
        department=data.department,
        department_id=data.department_id,
        status=data.status,
        goals=data.goals,
        challenges=data.challenges,
        pain_points=data.pain_points,
        impact_category=data.impact_category,
        impact_description=data.impact_description,
        estimated_savings=data.estimated_savings,
        estimated_revenue=data.estimated_revenue,
        timeline_estimate=data.timeline_estimate,
        user=user,
        scores=data.scores,
        overall_score=data.overall_score,
        customer_id=data.customer_id,
        # Technology tracking fields (WP27+)
        tech_stack=data.tech_stack,
        devices=data.devices,
        software=data.software,
        vendor=data.vendor,
    )
    return use_case.to_dict()


@router.put("/{use_case_id}/", response_model=UseCaseResponse)
def update_use_case(
    use_case_id: int,
    data: UseCaseUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update an existing use case."""
    user = _require_user(request)
    # R3: a use case never moves between customers. Checked before any scope
    # gate. An identical customer_id is not a move (the edit form always sends
    # the current one), so only a differing value is rejected.
    target_customer_id = _target_customer_id(db, use_case_id)
    if "customer_id" in data.model_fields_set and data.customer_id != target_customer_id:
        raise HTTPException(status_code=422, detail="Use case customer cannot be changed.")
    # 404-first (R4/Q7): a use case on a customer outside the caller's read
    # scope is indistinguishable from a missing one; in-scope write denials
    # keep their exact 403.
    if target_customer_id is not None \
            and not sales_access.can(user, db, sales_access.CAP_READ, target_customer_id):
        raise HTTPException(status_code=404, detail="Use case not found")
    _require_edit(user, db, target_customer_id)
    use_case = UseCaseService.update(db, use_case_id, user=user, **data.model_dump(exclude_none=True))
    if not use_case:
        raise HTTPException(status_code=404, detail="Use case not found")
    return use_case.to_dict()


@router.delete("/{use_case_id}/", status_code=204)
def delete_use_case(
    use_case_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Delete a use case. Admin or customer owner only (404-first)."""
    user = _require_user(request)
    target_customer_id = _target_customer_id(db, use_case_id)
    # 404-first (R4/Q7): out-of-scope == missing (see update above).
    if target_customer_id is not None \
            and not sales_access.can(user, db, sales_access.CAP_READ, target_customer_id):
        raise HTTPException(status_code=404, detail="Use case not found")
    _require_edit(user, db, target_customer_id)
    deleted = UseCaseService.delete(db, use_case_id, user=user)
    if not deleted:
        raise HTTPException(status_code=404, detail="Use case not found")
