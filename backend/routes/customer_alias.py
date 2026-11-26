"""REST API routes for customer alias tags.

Access control — the existing read scope + the alias write gate:
- Unauthenticated: 401.
- Read (all verbs): the central-policy read scope
  (``sales_access.can(..., CAP_READ, ...)``); a missing or out-of-scope
  customer returns the same 404 "Customer not found" (404-first).
- Write (POST/DELETE): customer owner or global admin — PLUS sales_admin
  (the alias section is import-matching
  metadata, and the sales admin manages it alongside admin and the
  account owner). The main.py app-wide sales-admin CONTENT block
  deliberately does not cover this surface. In-scope non-writers get 403.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.models.use_case import Customer
from backend.services import customer_alias_service, sales_access
from backend.services.customers_service import get_customer_by_name

router = APIRouter(prefix="/api/customers", tags=["customer-aliases"])

_WRITE_REQUIRED = "Customer owner, sales admin, or admin required"

_STATUS = {
    customer_alias_service.EMPTY: 422,
    customer_alias_service.OWN_NAME: 422,
    customer_alias_service.OTHER_NAME: 422,
    customer_alias_service.DUPLICATE: 409,
    customer_alias_service.NOT_FOUND: 404,
}


class AliasIn(BaseModel):
    alias: str


def _require_user(request: Request) -> dict:
    """Return authenticated user or 401."""
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _readable_customer_or_404(db: Session, customer_name: str, user: dict) -> Customer:
    customer = get_customer_by_name(db, customer_name)
    if customer is None or not sales_access.can(user, db, sales_access.CAP_READ, customer.id):
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def _can_manage_aliases(user: dict, customer: Customer) -> bool:
    """Alias writers: customer owner, global admin, or the sales_admin role
    (aliases are import-matching metadata
    the sales admin manages; the app-wide sales-admin content block in
    main.py intentionally does not cover this surface)."""
    if user.get("is_admin") == 1:
        return True
    if sales_access.effective_role(user) == "sales_admin":
        return True
    return user.get("junction_roles", {}).get(customer.id) == "owner"


def _writable_customer(db: Session, customer_name: str, user: dict) -> Customer:
    customer = _readable_customer_or_404(db, customer_name, user)
    if not _can_manage_aliases(user, customer):
        raise HTTPException(status_code=403, detail=_WRITE_REQUIRED)
    return customer


def _service_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    if message not in _STATUS:
        raise exc
    return HTTPException(status_code=_STATUS[message], detail=message)


@router.get("/{customer_name}/aliases/")
def list_customer_aliases(
    customer_name: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """The customer's aliases, sorted by raw alias."""
    user = _require_user(request)
    customer = _readable_customer_or_404(db, customer_name, user)
    return [row.to_dict() for row in customer_alias_service.list_aliases(db, customer)]


@router.post("/{customer_name}/aliases/", status_code=201)
def add_customer_alias(
    customer_name: str,
    data: AliasIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Add an alias. Owner, sales admin, or admin only (404-first)."""
    user = _require_user(request)
    customer = _writable_customer(db, customer_name, user)
    try:
        row = customer_alias_service.add_alias(db, customer, data.alias, user.get("username"))
    except ValueError as exc:
        raise _service_error(exc) from exc
    return row.to_dict()


@router.delete("/{customer_name}/aliases/{alias_id}/", status_code=204)
def delete_customer_alias(
    customer_name: str,
    alias_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Remove an alias. Owner, sales admin, or admin only (404-first)."""
    user = _require_user(request)
    customer = _writable_customer(db, customer_name, user)
    try:
        customer_alias_service.remove_alias(db, customer, alias_id)
    except ValueError as exc:
        raise _service_error(exc) from exc
    return Response(status_code=204)
