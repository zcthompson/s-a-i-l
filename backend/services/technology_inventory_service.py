"""Technology Inventory service layer (S-A-I-L).

Business logic for per-customer structured technology inventory:
- Create/read/update/delete technology items
- Controlled-vocabulary validation (category, deployment model, lifecycle,
  support, criticality, verification state) — vocabularies live in
  backend/models/customer_technology.py (single source of truth)
- Unknown attributes stay None -> NULL (never fabricated, charter §4)

CustomerUser authorization is enforced at the route layer (same convention
as customer_knowledge.py / sales_evaluations.py); the service validates
data integrity and returns records.
"""


from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models.customer_technology import (
    BUSINESS_CRITICALITIES,
    CATEGORIES,
    DEPLOYMENT_MODELS,
    LIFECYCLE_STATES,
    SUPPORT_STATES,
    VERIFICATION_STATES,
)
from backend.models.customer_technology import (
    CustomerTechnology as CTModel,
)
from backend.services import record_cleanup

_ENUM_FIELDS = {
    "category": CATEGORIES,
    "deployment_model": DEPLOYMENT_MODELS,
    "lifecycle_state": LIFECYCLE_STATES,
    "support_state": SUPPORT_STATES,
    "business_criticality": BUSINESS_CRITICALITIES,
    "verification_state": VERIFICATION_STATES,
}


def _validate_payload(payload: dict) -> None:
    """Validate controlled-vocabulary and numeric fields (raise 422).

    Only validates fields actually present in the payload — absent fields
    remain unknown (None -> NULL), which is always valid.
    """
    for field, allowed in _ENUM_FIELDS.items():
        value = payload.get(field)
        if value is not None and value not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"{field} must be one of: {', '.join(allowed)}",
            )
    confidence = payload.get("confidence")
    if confidence is not None and not (0.0 <= float(confidence) <= 1.0):
        raise HTTPException(
            status_code=422, detail="confidence must be between 0.0 and 1.0"
        )
    quantity = payload.get("quantity")
    if quantity is not None and (not isinstance(quantity, int) or quantity < 1):
        raise HTTPException(
            status_code=422, detail="quantity must be a positive integer"
        )


def list_technology(
    db: Session,
    customer_id: int,
    category: str | None = None,
    vendor: str | None = None,
    verification_state: str | None = None,
    search: str | None = None,
    sort: str = "name",
) -> list[CTModel]:
    """List technology items for a customer with optional filters.

    ``search`` matches name or vendor (case-insensitive substring).
    ``sort`` whitelists the sortable column; anything else sorts by name.
    """
    query = db.query(CTModel).filter(CTModel.customer_id == customer_id)
    if category:
        query = query.filter(CTModel.category == category)
    if vendor:
        query = query.filter(CTModel.vendor == vendor)
    if verification_state:
        query = query.filter(CTModel.verification_state == verification_state)
    if search:
        like = f"%{search.lower()}%"
        query = query.filter(
            (CTModel.name.ilike(like)) | (CTModel.vendor.ilike(like))
        )
    sort_column = {
        "name": CTModel.name,
        "category": CTModel.category,
        "vendor": CTModel.vendor,
        "date_observed": CTModel.date_observed,
        "created_at": CTModel.created_at,
    }.get(sort, CTModel.name)
    return query.order_by(sort_column, CTModel.id).all()


def create_technology(db: Session, customer_id: int, payload: dict) -> CTModel:
    """Create a technology item for a customer.

    ``payload`` is the validated schema dict (already None for unknown
    attributes). Controlled vocabularies are re-checked here so non-API
    callers (seed enrichment, intelligence services) get the same
    guarantees.
    """
    _validate_payload(payload)
    record = CTModel(
        customer_id=customer_id,
        name=payload["name"],
        category=payload["category"],
        verification_state=payload.get("verification_state", "unverified"),
        vendor=payload.get("vendor"),
        version_edition=payload.get("version_edition"),
        deployment_model=payload.get("deployment_model"),
        quantity=payload.get("quantity"),
        footprint=payload.get("footprint"),
        purpose=payload.get("purpose"),
        lifecycle_state=payload.get("lifecycle_state"),
        support_state=payload.get("support_state"),
        business_criticality=payload.get("business_criticality"),
        source=payload.get("source"),
        date_observed=payload.get("date_observed"),
        end_of_support_date=payload.get("end_of_support_date"),
        eol_source=payload.get("eol_source"),
        confidence=payload.get("confidence"),
        notes=payload.get("notes"),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_technology(db: Session, technology_id: int) -> CTModel | None:
    """Return a technology item by id (None when missing)."""
    return db.query(CTModel).filter(CTModel.id == technology_id).first()


def update_technology(
    db: Session, technology_id: int, payload: dict
) -> CTModel | None:
    """Update a technology item's attributes.

    ``payload`` contains only the fields to change (exclude_unset at the
    route layer). Returns None when the item does not exist.
    """
    _validate_payload(payload)
    record = db.query(CTModel).filter(CTModel.id == technology_id).first()
    if record is None:
        return None
    for field, value in payload.items():
        if hasattr(record, field):
            setattr(record, field, value)
    db.commit()
    db.refresh(record)
    return record


def delete_technology(db: Session, technology_id: int) -> bool:
    """Delete a technology item. Returns True when a row was removed."""
    record = db.query(CTModel).filter(CTModel.id == technology_id).first()
    if record is None:
        return False
    record_cleanup.technologies(db, [record.id])
    db.delete(record)
    db.commit()
    return True
