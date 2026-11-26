"""Sales Notes API routes (S-A-I-L).

Per-customer structured sales notes (CHANGELOG 0.0.80 items 16-18,
P3). All routes are gated by CustomerUser authorization with admin bypass —
admins own all customers (same convention as customers.py, sales_section.py,
customer_knowledge.py, sales_evaluations.py, technology_inventory.py).
Out-of-scope per-id access returns 404 (no existence leakage). Business
logic (category vocabulary, junction customer-ownership validation) lives in
backend/services/sales_note_service.py.
"""


from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.models.sales_note import SalesNote as SNModel
from backend.models.use_case import Customer
from backend.schemas.sales_note import (
    SalesNote,
    SalesNoteCreate,
    SalesNoteUpdate,
)
from backend.services import sales_access
from backend.services import sales_note_service as sns

router = APIRouter(tags=["sales-notes"])


def _require_user(request: Request) -> dict:
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _accessible_customer(user: dict, db: Session, customer_id: int) -> Customer:
    """Return the customer if the caller may access it; else the same 404.

    Missing and out-of-scope are indistinguishable (404-first, R4/Q7); the
    in-scope basis is the central policy (A-1 re-recon ruling 2026-11-01,
    R1 continuation): admin unrestricted or a ``customer_scope`` grant.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if customer is not None and (
        sales_access.is_unrestricted(user)
        or customer_id in sales_access.customer_scope(user, db)
    ):
        return customer
    raise HTTPException(status_code=404, detail="Customer not found")


def _accessible_note(db: Session, user: dict, note_id: int) -> SNModel | None:
    """Return the note if the caller may access it; else None (→ 404).

    Central-policy basis (A-1 re-recon ruling 2026-11-01): admin
    unrestricted or a ``customer_scope`` grant on the note's customer.
    """
    note = db.query(SNModel).filter(SNModel.id == note_id).first()
    if note is None:
        return None
    if (
        sales_access.is_unrestricted(user)
        or note.customer_id in sales_access.customer_scope(user, db)
    ):
        return note
    return None


def _require_write(user: dict, db: Session, customer_id: int) -> None:
    """Require CAP_NOTES for the notes section on create, edit, and delete.

    The same gate applies to one's own and other authors' notes; authorship
    confers no additional rights. Auditors remain read-only.
    """
    if not sales_access.can(user, db, sales_access.CAP_NOTES, customer_id, section="notes"):
        raise HTTPException(status_code=403, detail="Not authorized to modify this customer")


@router.get("/api/customers/{customer_id}/sales-notes/", response_model=list[SalesNote])
def list_sales_notes(
    request: Request,
    customer_id: int,
    category: str | None = None,
    search: str | None = None,
    author: str | None = None,
    sort: str = "note_date",
    direction: str = "desc",
    db: Session = Depends(get_db),
):
    """List a customer's sales notes (CustomerUser-gated, admin bypass)."""
    user = _require_user(request)
    _accessible_customer(user, db, customer_id)
    items = sns.list_sales_notes(
        db,
        customer_id,
        category=category,
        search=search,
        author=author,
        sort=sort,
        direction=direction,
    )
    return [note.to_dict() for note in items]


@router.post("/api/customers/{customer_id}/sales-notes/", response_model=SalesNote, status_code=201)
def create_sales_note(
    request: Request, customer_id: int, payload: SalesNoteCreate, db: Session = Depends(get_db)
):
    """Create a sales note for a customer (CustomerUser-gated, admin bypass)."""
    user = _require_user(request)
    _accessible_customer(user, db, customer_id)
    _require_write(user, db, customer_id)
    return sns.create_sales_note(db, customer_id, payload).to_dict()


@router.get("/api/sales-notes/{note_id}/", response_model=SalesNote)
def get_sales_note(request: Request, note_id: int, db: Session = Depends(get_db)):
    """Get a sales note by id (404 if missing or out of scope)."""
    user = _require_user(request)
    note = _accessible_note(db, user, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Sales note not found")
    return note.to_dict()


@router.put("/api/sales-notes/{note_id}/", response_model=SalesNote)
def update_sales_note(
    request: Request, note_id: int, payload: SalesNoteUpdate, db: Session = Depends(get_db)
):
    """Update a sales note (only provided fields; related id lists replace)."""
    user = _require_user(request)
    note = _accessible_note(db, user, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Sales note not found")
    _require_write(user, db, note.customer_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields provided to update")
    updated = sns.update_sales_note(db, note_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="Sales note not found")
    return updated.to_dict()


@router.delete("/api/sales-notes/{note_id}/", status_code=204)
def delete_sales_note(request: Request, note_id: int, db: Session = Depends(get_db)):
    """Delete a sales note (CustomerUser-gated, admin bypass)."""
    user = _require_user(request)
    note = _accessible_note(db, user, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Sales note not found")
    _require_write(user, db, note.customer_id)
    if not sns.delete_sales_note(db, note_id):
        raise HTTPException(status_code=404, detail="Sales note not found")
