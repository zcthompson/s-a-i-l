"""Sales Notes service layer (S-A-I-L).

Business logic for per-customer structured sales notes

- Create/read/update/delete notes with category control vocabulary
- Related Technology Inventory items and use cases via junction tables,
  validated for CUSTOMER OWNERSHIP (a note may only link its own customer's
  technologies and use cases — cross-customer junctions are rejected with 422)
- Original note content is preserved verbatim; AI-derived notes must use
  verification_state="inferred"/"unverified" with a traceable source
- Unknown attributes (author, source, note_date) stay NULL — never fabricated

CustomerUser authorization is enforced at the route layer (same convention
as customer_knowledge.py / technology_inventory.py); the service validates
data integrity and customer-scope of junction references.
"""


from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models.customer_technology import CustomerTechnology as CTModel
from backend.models.sales_note import CATEGORIES, VERIFICATION_STATES, SalesNote
from backend.models.use_case import UseCase
from backend.services import record_cleanup


def _validate_enum_fields(data: dict) -> None:
    """Validate controlled-vocabulary fields (raise 422 on bad value)."""
    checks = {
        "category": CATEGORIES,
        "verification_state": VERIFICATION_STATES,
    }
    for field, allowed in checks.items():
        value = data.get(field)
        if value is not None and value not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"{field} must be one of: {', '.join(allowed)}",
            )


def _validate_related_techs(db: Session, customer_id, tech_ids: list[int]) -> None:
    """Every related technology must exist AND belong to this customer."""
    if not tech_ids:
        return
    found = (
        db.query(CTModel)
        .filter(CTModel.id.in_(tech_ids), CTModel.customer_id == customer_id)
        .all()
    )
    if len(found) != len(set(tech_ids)):
        raise HTTPException(
            status_code=422,
            detail="related_technology_ids contains missing or out-of-customer items",
        )


def _validate_related_use_cases(db: Session, customer_id, uc_ids: list[int]) -> None:
    """Every related use case must exist AND belong to this customer."""
    if not uc_ids:
        return
    found = (
        db.query(UseCase)
        .filter(UseCase.id.in_(uc_ids), UseCase.customer_id == customer_id)
        .all()
    )
    if len(found) != len(set(uc_ids)):
        raise HTTPException(
            status_code=422,
            detail="related_use_case_ids contains missing or out-of-customer items",
        )


def _set_related(
    db: Session, note: SalesNote, tech_ids: list[int], uc_ids: list[int]
) -> None:
    """Replace the note's junction sets (validation already passed)."""
    note.related_technologies = (
        db.query(CTModel).filter(CTModel.id.in_(tech_ids)).all() if tech_ids else []
    )
    note.related_use_cases = (
        db.query(UseCase).filter(UseCase.id.in_(uc_ids)).all() if uc_ids else []
    )
    db.commit()


def list_sales_notes(
    db: Session,
    customer_id: int,
    category: str | None = None,
    search: str | None = None,
    author: str | None = None,
    sort: str = "note_date",
    direction: str = "desc",
) -> list[SalesNote]:
    """List a customer's notes with optional filters.

    Default ordering: newest note_date first (NULL dates last).
    """
    query = db.query(SalesNote).filter(SalesNote.customer_id == customer_id)
    if category:
        query = query.filter(SalesNote.category == category)
    if search:
        pattern = f"%{search.lower()}%"
        query = query.filter(
            SalesNote.title.ilike(pattern) | SalesNote.content.ilike(pattern)
        )
    if author:
        query = query.filter(SalesNote.author.ilike(f"%{author.lower()}%"))
    allowed_sorts = {"note_date", "created_at", "category", "title"}
    if sort not in allowed_sorts:
        raise HTTPException(status_code=422, detail="invalid sort field")
    col = getattr(SalesNote, sort)
    query = query.order_by(col.desc() if direction == "desc" else col.asc())
    return query.all()


def create_sales_note(db: Session, customer_id: int, payload) -> SalesNote:
    """Create a note. Only category/title/content required; related ids
    must belong to this customer. Unknowns stay NULL."""
    data = payload.model_dump(
        exclude_none=True,
        exclude={"related_technology_ids", "related_use_case_ids"},
    )
    if "verification_state" not in data:
        data["verification_state"] = "verified"
    _validate_enum_fields(data)
    tech_ids = list(dict.fromkeys(payload.related_technology_ids or []))
    uc_ids = list(dict.fromkeys(payload.related_use_case_ids or []))
    _validate_related_techs(db, customer_id, tech_ids)
    _validate_related_use_cases(db, customer_id, uc_ids)
    note = SalesNote(customer_id=customer_id, **data)
    db.add(note)
    db.commit()
    db.refresh(note)
    _set_related(db, note, tech_ids, uc_ids)
    return note


def get_sales_note(db: Session, note_id: int) -> SalesNote | None:
    """Fetch a note by id (or None)."""
    return db.query(SalesNote).filter(SalesNote.id == note_id).first()


def update_sales_note(
    db: Session, note_id: int, payload
) -> SalesNote | None:
    """Update a note. Only provided fields change (explicit nulls clear);
    provided related_*_ids replace the current sets."""
    note = db.query(SalesNote).filter(SalesNote.id == note_id).first()
    if note is None:
        return None
    data = payload.model_dump(
        exclude_unset=True,
        exclude={"related_technology_ids", "related_use_case_ids"},
    )
    for required in ("category", "title", "content"):
        if required in data and data[required] is None:
            raise HTTPException(
                status_code=422, detail=f"{required} cannot be cleared (required field)"
            )
    _validate_enum_fields(data)
    for field, value in data.items():
        setattr(note, field, value)
    if payload.related_technology_ids is not None:
        tech_ids = list(dict.fromkeys(payload.related_technology_ids))
        _validate_related_techs(db, note.customer_id, tech_ids)
        note.related_technologies = (
            db.query(CTModel).filter(CTModel.id.in_(tech_ids)).all()
            if tech_ids
            else []
        )
    if payload.related_use_case_ids is not None:
        uc_ids = list(dict.fromkeys(payload.related_use_case_ids))
        _validate_related_use_cases(db, note.customer_id, uc_ids)
        note.related_use_cases = (
            db.query(UseCase).filter(UseCase.id.in_(uc_ids)).all()
            if uc_ids
            else []
        )
    db.commit()
    db.refresh(note)
    return note


def delete_sales_note(db: Session, note_id: int) -> bool:
    """Delete a note (junction rows cascade). Returns False if not found."""
    note = db.query(SalesNote).filter(SalesNote.id == note_id).first()
    if note is None:
        return False
    record_cleanup.sales_notes(db, [note.id])
    db.delete(note)
    db.commit()
    return True
