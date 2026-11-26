"""Technology dependency API routes (S-A-I-L).

Per-customer persistent technology-to-technology relationships
(PLAN_FEATURE_ENHANCMENTS.md — technology dependency relationships).
All routes are gated by CustomerUser authorization with admin bypass —
admins own all customers (same convention as technology_inventory.py,
customer_knowledge.py, sales_evaluations.py). Trailing slashes per the
repo's redirect_slashes=False convention.
"""


from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.models.technology_dependency import TechnologyDependency as TDModel
from backend.schemas.technology_dependency import (
    TechnologyDependency,
    TechnologyDependencyCreate,
    TechnologyDependencyUpdate,
)
from backend.services import customer_access, sales_access
from backend.services.technology_dependency_service import (
    create_dependency,
    delete_dependency,
    list_dependencies,
    update_dependency,
)

router = APIRouter(tags=["technology-dependencies"])


def _require_user(request: Request) -> dict:
    """Return authenticated user dict or 401."""
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _accessible_item(db: Session, user: dict, dependency_id: int) -> TDModel | None:
    """Return the dependency if it exists and the caller may access it.

    The caller needs central READ on the dependency's customer (``sales_access``;
    admins pass). Returns None when the dependency is missing or out of scope
    (routes surface a 404).
    """
    item = db.query(TDModel).filter(TDModel.id == dependency_id).first()
    if item is None:
        return None
    if sales_access.can(user, db, sales_access.CAP_READ, item.customer_id):
        return item
    return None


def _require_edit(user: dict, db: Session, customer_id: int) -> None:
    """403 unless the caller holds CAP_EDIT on the customer (auditor is read-only)."""
    if not sales_access.can(user, db, sales_access.CAP_EDIT, customer_id):
        raise HTTPException(status_code=403, detail="Not authorized to modify this customer")


@router.get(
    "/api/customers/{customer_id}/technology-dependencies/",
    response_model=list[TechnologyDependency],
)
def list_customer_dependencies(
    request: Request,
    customer_id: int,
    relationship_type: str | None = Query(None, max_length=50),
    verification_state: str | None = Query(None, max_length=20),
    search: str | None = Query(None, max_length=255),
    db: Session = Depends(get_db),
):
    """List a customer's technology dependencies with optional filters.

    Filters: relationship_type, verification_state, search (source/target
    name or vendor substring).
    """
    user = _require_user(request)
    customer_access.read_or_404(db, user, customer_id)
    return list_dependencies(
        db,
        customer_id,
        relationship_type=relationship_type,
        verification_state=verification_state,
        search=search,
    )


@router.post(
    "/api/customers/{customer_id}/technology-dependencies/",
    response_model=TechnologyDependency,
    status_code=201,
)
def create_customer_dependency(
    request: Request,
    customer_id: int,
    payload: TechnologyDependencyCreate,
    db: Session = Depends(get_db),
):
    """Create a technology dependency for a customer.

    Both endpoints must be technologies of this customer; the mirrored
    direction of an existing relationship is rejected (canonical
    orientation).
    """
    user = _require_user(request)
    customer_access.read_or_404(db, user, customer_id)
    _require_edit(user, db, customer_id)
    data = payload.model_dump(exclude_none=True)
    return create_dependency(db, customer_id, data)


@router.get(
    "/api/technology-dependencies/{dependency_id}/",
    response_model=TechnologyDependency,
)
def read_dependency(
    request: Request,
    dependency_id: int,
    db: Session = Depends(get_db),
):
    """Read a single technology dependency (auth-gated via its customer)."""
    user = _require_user(request)
    item = _accessible_item(db, user, dependency_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Technology dependency not found")
    return item


@router.put(
    "/api/technology-dependencies/{dependency_id}/",
    response_model=TechnologyDependency,
)
def update_dependency_route(
    request: Request,
    dependency_id: int,
    payload: TechnologyDependencyUpdate,
    db: Session = Depends(get_db),
):
    """Update a technology dependency (only provided fields change)."""
    user = _require_user(request)
    item = _accessible_item(db, user, dependency_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Technology dependency not found")
    _require_edit(user, db, item.customer_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")
    updated = update_dependency(db, dependency_id, data)
    if updated is None:
        raise HTTPException(status_code=404, detail="Technology dependency not found")
    return updated


@router.delete("/api/technology-dependencies/{dependency_id}/", status_code=204)
def delete_dependency_route(
    request: Request,
    dependency_id: int,
    db: Session = Depends(get_db),
):
    """Delete a technology dependency."""
    user = _require_user(request)
    item = _accessible_item(db, user, dependency_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Technology dependency not found")
    _require_edit(user, db, item.customer_id)
    delete_dependency(db, dependency_id)
