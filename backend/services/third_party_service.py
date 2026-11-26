"""Third-Party Professional Services service layer (S-A-I-L Sales section).

docs/archive/PLAN_THIRD_PARTY_SERVICES.md §4.2. Module functions per repo style.

- CRUD with controlled-vocabulary validation (categories, statuses, billing
  models, document types — single source in
  ``backend/models/third_party_service.py``, same mechanism as
  ``sales_note.py``) and date-ordering integrity (ended_on ≥ started_on).
- Unknown stays unknown (charter §4): every optional field stays NULL until
  a user enters a value — no server-side fabrication.
- Use-case links (junction) are validated for CUSTOMER OWNERSHIP (an
  engagement may only link its own customer's use cases — cross-customer
  links rejected with 422, same isolation rule as sales notes).
- Authorization: routes gate first; the service RE-VERIFIES the row's
  customer_id against the caller on every id-level operation
  (``user`` dict from ``get_user_from_request``; ``ps_admin``/admin bypass
  via ``ps_role_ok``, else a junction row required). Cross-customer access
  raises 403 — not 404 (no existence leakage, per plan §4.2/§6).
"""

from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models.third_party_service import (
    BILLING_MODELS,
    DOCUMENT_TYPES,
    ENGAGEMENT_STATUSES,
    SERVICE_CATEGORIES,
    VERIFICATION_STATES,
    ThirdPartyService,
    ThirdPartyServiceDocument,
)
from backend.models.use_case import UseCase
from backend.services import record_cleanup
from backend.services.customer_access import ps_role_ok

# ── validation ───────────────────────────────────────────────────────────────


def _validate_enum_fields(data: dict) -> None:
    """Validate controlled-vocabulary fields (raise 422 on bad value)."""
    checks = {
        "service_category": SERVICE_CATEGORIES,
        "engagement_status": ENGAGEMENT_STATUSES,
        "billing_model": BILLING_MODELS,
        "verification_state": VERIFICATION_STATES,
    }
    for field, allowed in checks.items():
        value = data.get(field)
        if value is not None and value not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"{field} must be one of: {', '.join(allowed)}",
            )


def _parse_iso_date(value: str | None, field: str) -> date | None:
    """Parse an ISO date string (or None) — 422 on malformed input."""
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422, detail=f"{field} must be an ISO date (YYYY-MM-DD)"
        )


def _validate_date_order(started_on: date | None, ended_on: date | None) -> None:
    """ended_on ≥ started_on when both are set (422 otherwise)."""
    if started_on is not None and ended_on is not None and ended_on < started_on:
        raise HTTPException(
            status_code=422, detail="ended_on must be on or after started_on"
        )


def _validate_use_case_ids(db: Session, customer_id: int, uc_ids: list[int]) -> list[int]:
    """Dedupe + verify every use case exists AND belongs to this customer."""
    ids = list(dict.fromkeys(uc_ids))
    if not ids:
        return ids
    found = (
        db.query(UseCase)
        .filter(UseCase.id.in_(ids), UseCase.customer_id == customer_id)
        .all()
    )
    if len(found) != len(set(ids)):
        raise HTTPException(
            status_code=422,
            detail="use_case_ids contains missing or out-of-customer items",
        )
    return ids


# ── authorization (service re-verification, plan §4.2) ───────────────────────


def _check_access(user: dict | None, customer_id: int) -> None:
    """Raise 403 unless the caller may act on *customer_id*.

    ps_admin / admin bypass (any account); otherwise a CustomerUser row is
    required. 403 (never 404) so an id-level probe cannot leak existence.
    """
    if user is None:
        # Routes gate first (401); a service call with no user is a defect —
        # refuse rather than fall through.
        raise HTTPException(status_code=401, detail="Authentication required")
    if ps_role_ok(user):
        return
    if customer_id not in user.get("customer_ids", []):
        raise HTTPException(status_code=403, detail="Not authorized for this customer")


def _check_write(user: dict, customer_id: int) -> None:
    """Write permission: ps_role_ok, else owner/member junction role."""
    _check_access(user, customer_id)
    if ps_role_ok(user):
        return
    if (user.get("junction_roles") or {}).get(customer_id) not in ("owner", "member"):
        raise HTTPException(status_code=403, detail="Write access required")


# ── engagement CRUD ───────────────────────────────────────────────────────────


def list_for_customer(
    db: Session,
    user: dict,
    customer_id: int,
    status: str | None = None,
    category: str | None = None,
    search: str | None = None,
    sort: str = "created_at",
    direction: str = "desc",
) -> list[ThirdPartyService]:
    """List a customer's engagements with optional filters (auth-checked)."""
    _check_access(user, customer_id)
    query = db.query(ThirdPartyService).filter(
        ThirdPartyService.customer_id == customer_id
    )
    if status:
        query = query.filter(ThirdPartyService.engagement_status == status)
    if category:
        query = query.filter(ThirdPartyService.service_category == category)
    if search:
        pattern = f"%{search.lower()}%"
        query = query.filter(
            ThirdPartyService.vendor_name.ilike(pattern)
            | ThirdPartyService.description.ilike(pattern)
            | ThirdPartyService.sow_reference.ilike(pattern)
        )
    allowed_sorts = {"created_at", "updated_at", "vendor_name", "started_on", "engagement_status"}
    if sort not in allowed_sorts:
        raise HTTPException(status_code=422, detail="invalid sort field")
    col = getattr(ThirdPartyService, sort)
    query = query.order_by(col.desc() if direction == "desc" else col.asc())
    return query.all()


def cross_account_list(
    db: Session,
    user: dict,
    status: str | None = None,
    category: str | None = None,
    search: str | None = None,
) -> list[ThirdPartyService]:
    """Cross-account listing — admin/ps_admin ONLY (plan §4.3 admin route)."""
    if not ps_role_ok(user):
        raise HTTPException(
            status_code=403, detail="Third-party admin role required"
        )
    query = db.query(ThirdPartyService)
    if status:
        query = query.filter(ThirdPartyService.engagement_status == status)
    if category:
        query = query.filter(ThirdPartyService.service_category == category)
    if search:
        pattern = f"%{search.lower()}%"
        query = query.filter(
            ThirdPartyService.vendor_name.ilike(pattern)
            | ThirdPartyService.description.ilike(pattern)
            | ThirdPartyService.sow_reference.ilike(pattern)
        )
    return query.order_by(ThirdPartyService.created_at.desc()).all()


def create(
    db: Session, user: dict, customer_id: int, payload
) -> ThirdPartyService:
    """Create an engagement. vendor_name/service_category/description
    required; junction ids must belong to this customer; unknowns NULL."""
    _check_write(user, customer_id)
    data = payload.model_dump(exclude_unset=True, exclude_none=True)
    data.pop("use_case_ids", None)
    data["started_on"] = _parse_iso_date(data.get("started_on"), "started_on")
    data["ended_on"] = _parse_iso_date(data.get("ended_on"), "ended_on")
    _validate_enum_fields(data)
    if data.get("started_on") is None and "engagement_status" not in data:
        pass  # defaults apply
    _validate_date_order(data.get("started_on"), data.get("ended_on"))
    if "engagement_status" not in data:
        data["engagement_status"] = "active"
    if "verification_state" not in data:
        data["verification_state"] = "verified"
    data["created_by"] = user.get("username")
    svc = ThirdPartyService(customer_id=customer_id, **data)
    db.add(svc)
    db.commit()
    db.refresh(svc)
    uc_ids = _validate_use_case_ids(db, customer_id, payload.use_case_ids or [])
    if uc_ids:
        svc.related_use_cases = (
            db.query(UseCase).filter(UseCase.id.in_(uc_ids)).all()
        )
        db.commit()
    return svc


def get(db: Session, user: dict, service_id: int) -> ThirdPartyService | None:
    """Fetch by id (or None). Out-of-scope callers raise 403 (no 404 leak)."""
    svc = db.query(ThirdPartyService).filter(ThirdPartyService.id == service_id).first()
    if svc is None:
        return None
    _check_access(user, svc.customer_id)
    return svc


def update(
    db: Session, user: dict, service_id: int, payload
) -> ThirdPartyService | None:
    """Partial update (exclude_unset; explicit nulls clear). use_case_ids
    present = full replacement of the link set."""
    svc = db.query(ThirdPartyService).filter(
        ThirdPartyService.id == service_id
    ).first()
    if svc is None:
        return None
    _check_write(user, svc.customer_id)
    data = payload.model_dump(exclude_unset=True, exclude={"use_case_ids"})
    for field in ("started_on", "ended_on"):
        if field in data:
            data[field] = _parse_iso_date(data[field], field)
    # Required fields cannot be cleared.
    for required in ("vendor_name", "service_category", "description"):
        if required in data and data[required] is None:
            raise HTTPException(
                status_code=422,
                detail=f"{required} cannot be cleared (required field)",
            )
    _validate_enum_fields(data)
    for field, value in data.items():
        setattr(svc, field, value)
    _validate_date_order(svc.started_on, svc.ended_on)
    if payload.use_case_ids is not None:
        uc_ids = _validate_use_case_ids(db, svc.customer_id, payload.use_case_ids)
        svc.related_use_cases = (
            db.query(UseCase).filter(UseCase.id.in_(uc_ids)).all() if uc_ids else []
        )
    db.commit()
    db.refresh(svc)
    return svc


def delete(db: Session, user: dict, service_id: int) -> bool:
    """Delete an engagement (documents + junction links cascade).

    Runtime SQLite does not enforce ON DELETE CASCADE (PRAGMA foreign_keys
    off by default) — delete documents explicitly, mirroring the
    customer_knowledge delete fix (2026-09-11)."""
    svc = db.query(ThirdPartyService).filter(
        ThirdPartyService.id == service_id
    ).first()
    if svc is None:
        return False
    _check_write(user, svc.customer_id)
    record_cleanup.third_party_services(db, [service_id])
    db.delete(svc)
    db.commit()
    return True


# ── documents ─────────────────────────────────────────────────────────────────


def list_documents(db: Session, user: dict, service_id: int) -> list[ThirdPartyServiceDocument]:
    """List an engagement's documents (no blobs in the wire shape)."""
    svc = db.query(ThirdPartyService).filter(
        ThirdPartyService.id == service_id
    ).first()
    if svc is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    _check_access(user, svc.customer_id)
    return (
        db.query(ThirdPartyServiceDocument)
        .filter(ThirdPartyServiceDocument.service_id == service_id)
        .order_by(ThirdPartyServiceDocument.created_at.desc())
        .all()
    )


def store_document(
    db: Session,
    user: dict,
    service_id: int,
    document_type: str,
    file_name: str,
    file_data: bytes,
    title: str | None,
) -> ThirdPartyServiceDocument:
    """Store a document store-first (original bytes in the DB row before
    anything else — customer-knowledge precedent)."""
    svc = db.query(ThirdPartyService).filter(
        ThirdPartyService.id == service_id
    ).first()
    if svc is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    _check_write(user, svc.customer_id)
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"document_type must be one of: {', '.join(DOCUMENT_TYPES)}",
        )
    if not file_data:
        raise HTTPException(status_code=400, detail="Upload is empty")
    doc = ThirdPartyServiceDocument(
        service_id=service_id,
        customer_id=svc.customer_id,
        document_type=document_type,
        file_name=file_name or "upload",
        file_data=file_data,
        title=title,
        uploaded_by=user.get("username"),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def get_document(
    db: Session, user: dict, document_id: int
) -> ThirdPartyServiceDocument | None:
    """Fetch a document by id (or None). Out-of-scope callers raise 403."""
    doc = db.query(ThirdPartyServiceDocument).filter(
        ThirdPartyServiceDocument.id == document_id
    ).first()
    if doc is None:
        return None
    _check_access(user, doc.customer_id)
    return doc


def delete_document(db: Session, user: dict, document_id: int) -> bool:
    """Delete a document (auth-checked against its customer)."""
    doc = db.query(ThirdPartyServiceDocument).filter(
        ThirdPartyServiceDocument.id == document_id
    ).first()
    if doc is None:
        return False
    _check_write(user, doc.customer_id)
    db.delete(doc)
    db.commit()
    return True


# ── readiness aggregation ─────────────────────────────────────────────────────


def readiness_summary(db: Session, customer_id: int) -> dict:
    """Engagement counts for the readiness endpoint (§4.4, additive)."""
    rows = (
        db.query(
            ThirdPartyService.engagement_status,
            ThirdPartyService.id,
        )
        .filter(ThirdPartyService.customer_id == customer_id)
        .all()
    )
    by_status = {s: 0 for s in ENGAGEMENT_STATUSES}
    for status, _ in rows:
        if status in by_status:
            by_status[status] += 1
    documents = (
        db.query(ThirdPartyServiceDocument.id)
        .filter(ThirdPartyServiceDocument.customer_id == customer_id)
        .count()
    )
    return {
        "engagements": len(rows),
        "by_status": by_status,
        "documents": documents,
    }
