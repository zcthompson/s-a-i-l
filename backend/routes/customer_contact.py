"""Thin, centrally authorized customer contact routes."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.models.customer_contact import CustomerContact
from backend.schemas.contact import Contact, ContactCoverage, ContactCreate, ContactUpdate
from backend.services import customer_contact_service as service
from backend.services import sales_access
from backend.services.customer_access import (
    read_or_404,
    require_account_read,
)

router = APIRouter(tags=["contacts"])


def _require_user(request):
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(401, "Authentication required")
    return user


def _read(request, db, customer_id):
    try:
        return require_account_read(request, db, customer_id)
    except HTTPException as exc:
        if exc.status_code == 403:
            raise HTTPException(404, "Customer not found") from exc
        raise


def _accessible_contact(user, db, contact_id):
    contact = db.query(CustomerContact).filter_by(id=contact_id).first()
    if contact is None or not sales_access.can(user, db, sales_access.CAP_READ, contact.customer_id):
        raise HTTPException(404, "Contact not found")
    return contact


def _require_write(user, db, customer_id):
    if not sales_access.can(user, db, sales_access.CAP_CONTACTS, customer_id, section="contacts"):
        raise HTTPException(403, "Not authorized to modify this customer")


@router.get("/api/customers/{customer_id}/contacts/", response_model=list[Contact])
def list_contacts(request: Request, customer_id: int, include_archived: bool = False,
                  search: str | None = None, db: Session = Depends(get_db)):
    _read(request, db, customer_id)
    return [row.to_dict() for row in service.list_contacts(db, customer_id, include_archived, search)]


@router.post("/api/customers/{customer_id}/contacts/", response_model=Contact, status_code=201)
def create_contact(request: Request, customer_id: int, payload: ContactCreate,
                   db: Session = Depends(get_db)):
    user = _require_user(request)
    read_or_404(db, user, customer_id)
    _require_write(user, db, customer_id)
    return service.create_contact(db, customer_id, payload.model_dump(), user["username"]).to_dict()


@router.get("/api/customers/{customer_id}/contacts/coverage/", response_model=ContactCoverage)
def coverage(request: Request, customer_id: int, db: Session = Depends(get_db)):
    _read(request, db, customer_id)
    return service.contact_coverage_for(db, customer_id)


@router.get("/api/contacts/{contact_id}/", response_model=Contact)
def get_contact(request: Request, contact_id: int, db: Session = Depends(get_db)):
    return _accessible_contact(_require_user(request), db, contact_id).to_dict()


@router.put("/api/contacts/{contact_id}/", response_model=Contact)
def update_contact(request: Request, contact_id: int, payload: ContactUpdate,
                   db: Session = Depends(get_db)):
    user = _require_user(request)
    contact = _accessible_contact(user, db, contact_id)
    _require_write(user, db, contact.customer_id)
    return service.update_contact(db, contact, payload.model_dump(exclude_unset=True), user["username"]).to_dict()


@router.delete("/api/contacts/{contact_id}/", status_code=204)
def delete_contact(request: Request, contact_id: int, db: Session = Depends(get_db)):
    user = _require_user(request)
    contact = _accessible_contact(user, db, contact_id)
    _require_write(user, db, contact.customer_id)
    service.delete_contact(db, contact)
