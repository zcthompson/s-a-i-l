"""Account-membership routes (RBAC model).

HTTP only: authenticate, resolve the customer, delegate to
``membership_service`` (which owns every authorization and data rule and
raises before any content is assembled).

404-first: a customer outside the caller's read scope returns the
same 404 as a missing one, so a by-name probe cannot reveal existence.
In-scope capability denials keep the service's exact 403.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.services import customer_access
from backend.services import membership_service as svc
from backend.services.customers_service import get_customer_by_name
from backend.services.sales_access import effective_role

router = APIRouter(prefix="/api/customers", tags=["account-memberships"])
admin_router = APIRouter(prefix="/api/admin", tags=["account-memberships"])

MembershipRole = Literal["primary_owner", "co_owner", "sales_ops", "inside_sales"]


class MembershipCreate(BaseModel):
    user_id: int
    role: MembershipRole
    section_grants: dict[str, str] | None = None


class TransferRequest(BaseModel):
    user_id: int


class GrantsUpdate(BaseModel):
    section_grants: dict[str, str]


def _actor(request: Request) -> dict:
    user = get_user_from_request(request)
    if user is None or user.get("user_id") is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _customer(db: Session, name: str, user: dict):
    customer = get_customer_by_name(db, name)
    if customer is None or not customer_access.can_read(user, db, customer.id):
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.MembershipError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/{customer_name}/memberships/")
def list_memberships(customer_name: str, request: Request, db: Session = Depends(get_db)):
    user = _actor(request)
    customer = _customer(db, customer_name, user)
    return {"customer_id": customer.id, "members": svc.list_memberships(db, customer.id)}


@router.post("/{customer_name}/memberships/", status_code=201)
def add_membership(customer_name: str, payload: MembershipCreate, request: Request,
                   db: Session = Depends(get_db)):
    user = _actor(request)
    customer = _customer(db, customer_name, user)
    return _call(
        svc.add_membership, db, customer.id, payload.user_id, payload.role,
        user["user_id"], section_grants=payload.section_grants, request=request,
    )


@router.delete("/{customer_name}/memberships/{user_id}/")
def remove_membership(customer_name: str, user_id: int, request: Request,
                      role: MembershipRole = Query(...), db: Session = Depends(get_db)):
    user = _actor(request)
    customer = _customer(db, customer_name, user)
    return _call(
        svc.remove_membership, db, customer.id, user_id, role, user["user_id"], request=request,
    )


@router.post("/{customer_name}/transfer-ownership/")
def transfer_ownership(customer_name: str, payload: TransferRequest, request: Request,
                       db: Session = Depends(get_db)):
    user = _actor(request)
    customer = _customer(db, customer_name, user)
    return _call(
        svc.transfer_ownership, db, customer.id, payload.user_id, user["user_id"],
        request=request,
    )


@router.put("/{customer_name}/memberships/{user_id}/grants/")
def set_section_grants(customer_name: str, user_id: int, payload: GrantsUpdate,
                       request: Request, db: Session = Depends(get_db)):
    user = _actor(request)
    customer = _customer(db, customer_name, user)
    return _call(
        svc.set_section_grants, db, customer.id, user_id, payload.section_grants,
        user["user_id"], request=request,
    )


def _require_review_admin(request: Request) -> dict:
    user = _actor(request)
    if effective_role(user) not in ("system_admin", "sales_admin"):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


@admin_router.get("/ownership-review/")
def ownership_review(request: Request, db: Session = Depends(get_db)):
    _require_review_admin(request)
    return {"items": svc.list_ownership_review(db)}


@admin_router.post("/ownership-review/{customer_id}/")
def resolve_ownership_review(customer_id: int, payload: TransferRequest, request: Request,
                             db: Session = Depends(get_db)):
    user = _require_review_admin(request)
    return _call(
        svc.resolve_ownership_review, db, customer_id, payload.user_id, user["user_id"],
        request=request,
    )
