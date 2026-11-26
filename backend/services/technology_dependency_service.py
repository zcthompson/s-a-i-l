"""Technology dependency service layer (S-A-I-L).

Business logic for persistent technology-to-technology relationships
(PLAN_FEATURE_ENHANCMENTS.md — technology dependency relationships):

- controlled-vocabulary validation (relationship_type,
  verification_state, confidence range) — vocabularies live in
  backend/models/technology_dependency.py (single source of truth);
- referential integrity: both endpoints must exist and belong to the
  SAME customer (cross-customer dependencies are rejected 422);
- no self-dependency (source == target rejected 422);
- **canonical orientation**: one row per (source, target,
  relationship_type) — the UNIQUE constraint makes it authoritative at
  the schema level; the service additionally rejects the mirrored
  direction of an existing relationship (409) so a relationship is never
  stored twice from either entity's perspective (the graph projection
  dedups at the source).

CustomerUser authorization is enforced at the route layer (same
convention as technology_inventory.py); the service validates data
integrity and returns records.
"""


from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.models.customer_technology import VERIFICATION_STATES
from backend.models.customer_technology import CustomerTechnology as CTModel
from backend.models.technology_dependency import (
    DEPENDENCY_TYPES,
)
from backend.models.technology_dependency import (
    TechnologyDependency as TDModel,
)

_ENUM_FIELDS = {
    "relationship_type": DEPENDENCY_TYPES,
    "verification_state": VERIFICATION_STATES,
}

# Directional synonyms: a stored (A -> B, type) relationship makes the
# mirrored (B -> A, synonym) an attempt to store the same logical
# relationship a second time. (associated_with is symmetric: its mirror
# is always the duplicate.)
_MIRROR_SYNONYMS = {
    "runs_on": {"hosts"},
    "hosts": {"runs_on"},
    "consumes_storage": {"provides_storage"},
    "provides_storage": {"consumes_storage"},
    "consumes_compute": {"provides_compute"},
    "provides_compute": {"consumes_compute"},
    "associated_with": {"associated_with"},
}


def _validate_payload(payload: dict) -> None:
    """Validate controlled-vocabulary and numeric fields (raise 422)."""
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


def _load_endpoint(
    db: Session, customer_id: int, endpoint_id: int, field: str
) -> CTModel:
    """Return the referenced technology if it exists for THIS customer.

    Missing or cross-customer references raise 422 — an endpoint pointing
    at another customer's inventory is rejected, never silently adopted.
    """
    tech = (
        db.query(CTModel)
        .filter(CTModel.id == endpoint_id, CTModel.customer_id == customer_id)
        .first()
    )
    if tech is None:
        raise HTTPException(
            status_code=422,
            detail=f"{field} must reference a technology of this customer",
        )
    return tech


def _reject_mirror(db: Session, source_id: int, target_id: int, rtype: str) -> None:
    """Raise 409 when the mirrored direction of the same logical
    relationship already exists (canonical orientation invariant)."""
    # NOTE: the probe is always the REVERSE direction (new target, new
    # source), so it can never match the row being created/updated.
    for other_type in (rtype, *_MIRROR_SYNONYMS.get(rtype, ())):
        existing = (
            db.query(TDModel)
            .filter(
                TDModel.target_id == source_id,
                TDModel.source_id == target_id,
                TDModel.relationship_type == other_type,
            )
            .first()
        )
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"mirrored relationship already exists "
                    f"(id {existing.id}: '{existing.source.name}' {other_type} "
                    f"'{existing.target.name}') — one canonical row per logical "
                    "relationship"
                ),
            )


def list_dependencies(
    db: Session,
    customer_id: int,
    relationship_type: str | None = None,
    verification_state: str | None = None,
    search: str | None = None,
) -> list[TDModel]:
    """List a customer's technology dependencies with optional filters.

    ``search`` matches the source or target technology name/vendor
    (case-insensitive substring) — joined through the endpoints.
    """
    query = db.query(TDModel).filter(TDModel.customer_id == customer_id)
    if relationship_type:
        query = query.filter(TDModel.relationship_type == relationship_type)
    if verification_state:
        query = query.filter(TDModel.verification_state == verification_state)
    if search:
        like = f"%{search.lower()}%"
        source_match = db.query(CTModel.id).filter(
            or_(CTModel.name.ilike(like), CTModel.vendor.ilike(like))
        )
        target_match = db.query(CTModel.id).filter(
            or_(CTModel.name.ilike(like), CTModel.vendor.ilike(like))
        )
        query = query.filter(
            or_(
                TDModel.source_id.in_(source_match),
                TDModel.target_id.in_(target_match),
            )
        )
    return query.order_by(TDModel.id).all()


def create_dependency(db: Session, customer_id: int, payload: dict) -> TDModel:
    """Create a technology dependency for a customer.

    Validates vocabulary, same-customer endpoints, no self-dependency,
    and canonical orientation (the mirrored direction 409s via
    _reject_mirror; the exact duplicate 409s via the UNIQUE constraint).
    """
    _validate_payload(payload)
    source = _load_endpoint(db, customer_id, payload["source_id"], "source_id")
    target = _load_endpoint(db, customer_id, payload["target_id"], "target_id")
    if source.id == target.id:
        raise HTTPException(
            status_code=422, detail="source_id and target_id must differ"
        )
    rtype = payload["relationship_type"]
    _reject_mirror(db, source.id, target.id, rtype)
    record = TDModel(
        customer_id=customer_id,
        source_id=source.id,
        target_id=target.id,
        relationship_type=rtype,
        verification_state=payload.get("verification_state", "verified"),
        confidence=payload.get("confidence"),
        source_provenance=payload.get("source_provenance"),
        date_observed=payload.get("date_observed"),
        notes=payload.get("notes"),
    )
    db.add(record)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="this relationship already exists (canonical orientation)",
        )
    db.refresh(record)
    return record


def get_dependency(db: Session, dependency_id: int) -> TDModel | None:
    """Return a dependency by id (None when missing)."""
    return db.query(TDModel).filter(TDModel.id == dependency_id).first()


def update_dependency(
    db: Session, dependency_id: int, payload: dict
) -> TDModel | None:
    """Update a dependency's attributes (only provided fields change).

    Endpoint/relationship changes are re-validated exactly as on create
    (same customer, no self-reference, canonical orientation against the
    other rows). Returns None when the record does not exist.
    """
    record = db.query(TDModel).filter(TDModel.id == dependency_id).first()
    if record is None:
        return None
    _validate_payload(payload)
    source_id = payload.get("source_id") or record.source_id
    target_id = payload.get("target_id") or record.target_id
    rtype = payload.get("relationship_type") or record.relationship_type
    source = _load_endpoint(db, record.customer_id, source_id, "source_id")
    target = _load_endpoint(db, record.customer_id, target_id, "target_id")
    if source.id == target.id:
        raise HTTPException(
            status_code=422, detail="source_id and target_id must differ"
        )
    # The mirror check queries rows OTHER than the one being updated:
    # a row's own (source, target) pair is the reverse of the mirrored
    # (target, source) probe, so it never matches itself. The UNIQUE
    # constraint is the final guard for exact duplicates.
    _reject_mirror(db, source.id, target.id, rtype)
    for field, value in payload.items():
        if hasattr(record, field):
            setattr(record, field, value)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="this relationship already exists (canonical orientation)",
        )
    db.refresh(record)
    return record


def delete_dependency(db: Session, dependency_id: int) -> bool:
    """Delete a dependency. Returns True when a row was removed."""
    record = db.query(TDModel).filter(TDModel.id == dependency_id).first()
    if record is None:
        return False
    db.delete(record)
    db.commit()
    return True
