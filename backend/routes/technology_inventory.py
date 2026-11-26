"""Technology Inventory API routes (S-A-I-L).

Per-customer structured technology inventory CRUD (CHANGELOG 0.0.80
P2). All routes are gated by CustomerUser authorization with admin bypass —
admins own all customers (same convention as customers.py, sales_section.py,
customer_knowledge.py, and sales_evaluations.py). Trailing slashes per the
repo's redirect_slashes=False convention.
"""


from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.models.customer_technology import CustomerTechnology as CTModel
from backend.schemas.customer_technology import (
    CustomerTechnology,
    CustomerTechnologyCreate,
    CustomerTechnologyUpdate,
)
from backend.services import customer_access, sales_access
from backend.services.technology_inventory_service import (
    create_technology,
    delete_technology,
    list_technology,
    update_technology,
)

router = APIRouter(tags=["technology-inventory"])


def _require_user(request: Request) -> dict:
    """Return authenticated user dict or 401."""
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _accessible_item(db: Session, user: dict, technology_id: int) -> CTModel | None:
    """Return the item if it exists and the caller may access it.

    The caller needs central READ on the item's customer (``sales_access``;
    admins pass). Returns None when the item is missing or out of scope
    (routes surface a 404).
    """
    item = db.query(CTModel).filter(CTModel.id == technology_id).first()
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
    "/api/customers/{customer_id}/technology/",
    response_model=list[CustomerTechnology],
)
def list_customer_technology(
    request: Request,
    customer_id: int,
    category: str | None = Query(None, max_length=50),
    vendor: str | None = Query(None, max_length=255),
    verification_state: str | None = Query(None, max_length=20),
    search: str | None = Query(None, max_length=255),
    sort: str = Query("name", max_length=30),
    db: Session = Depends(get_db),
):
    """List a customer's technology inventory with optional filters.

    Auth-gated: owner/admin/member per CustomerUser junction; admins bypass
    the junction (own all customers). Filters: category, vendor,
    verification_state, search (name/vendor substring), sort (name,
    category, vendor, date_observed, created_at).
    """
    user = _require_user(request)
    customer_access.read_or_404(db, user, customer_id)
    return list_technology(
        db,
        customer_id,
        category=category,
        vendor=vendor,
        verification_state=verification_state,
        search=search,
        sort=sort,
    )


@router.post(
    "/api/customers/{customer_id}/technology/",
    response_model=CustomerTechnology,
    status_code=201,
)
def create_customer_technology(
    request: Request,
    customer_id: int,
    payload: CustomerTechnologyCreate,
    db: Session = Depends(get_db),
):
    """Create a technology inventory item for a customer.

    Unknown attributes are omitted (None -> NULL) — never fabricated.
    """
    user = _require_user(request)
    customer_access.read_or_404(db, user, customer_id)
    _require_edit(user, db, customer_id)
    data = payload.model_dump(exclude_none=True)
    return create_technology(db, customer_id, data)


@router.get("/api/technology/{technology_id}/", response_model=CustomerTechnology)
def read_technology(
    request: Request,
    technology_id: int,
    db: Session = Depends(get_db),
):
    """Read a single technology item (auth-gated via its customer)."""
    user = _require_user(request)
    item = _accessible_item(db, user, technology_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Technology item not found")
    return item


@router.put("/api/technology/{technology_id}/", response_model=CustomerTechnology)
def update_technology_route(
    request: Request,
    technology_id: int,
    payload: CustomerTechnologyUpdate,
    db: Session = Depends(get_db),
):
    """Update a technology item's attributes (only provided fields change)."""
    user = _require_user(request)
    item = _accessible_item(db, user, technology_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Technology item not found")
    _require_edit(user, db, item.customer_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")
    updated = update_technology(db, technology_id, data)
    if updated is None:
        raise HTTPException(status_code=404, detail="Technology item not found")
    return updated


@router.delete("/api/technology/{technology_id}/", status_code=204)
def delete_technology_route(
    request: Request,
    technology_id: int,
    db: Session = Depends(get_db),
):
    """Delete a technology item."""
    user = _require_user(request)
    item = _accessible_item(db, user, technology_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Technology item not found")
    _require_edit(user, db, item.customer_id)
    delete_technology(db, technology_id)
