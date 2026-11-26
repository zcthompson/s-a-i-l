"""Third-Party Professional Services API routes (S-A-I-L).

Thin routes — business logic (vocab
validation, junction customer-ownership, date integrity, store-first
document storage) lives in ``backend/services/third_party_service.py``.

Authorization: the 3rd-party PS surface passes for (a) the ``ps_admin``
global role or admin — cross-account, no CustomerUser row required (§4.5),
or (b) a caller holding a CustomerUser row for the customer (existing
semantics; junction-``auditor`` rows are read-only, same rule as sales
notes / comments). Id-level routes are 404-first: a record whose
customer is outside the caller's PS read scope returns the same 404 as a
missing one (no existence leak); in-scope capability denials keep their
exact 403.
"""


from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.models.third_party_service import (
    ThirdPartyService as TPSModel,
)
from backend.models.third_party_service import (
    ThirdPartyServiceDocument as TPSDocModel,
)
from backend.schemas.third_party_service import (
    ThirdPartyServiceCreate,
    ThirdPartyServiceDocumentResponse,
    ThirdPartyServiceResponse,
    ThirdPartyServiceUpdate,
)
from backend.services import sales_access
from backend.services import third_party_service as tps
from backend.services.customer_access import (
    ps_customer_read_ok,
    ps_customer_write_ok,
    ps_role_ok,
    require_ps_customer_access,
)
from backend.upload_size import read_upload_bytes

router = APIRouter(tags=["third-party-services"])

def _require_user(request: Request) -> dict:
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _require_edit(user: dict, db: Session, customer_id: int | None) -> None:
    """Resolver write gate for non-PS callers.

    ps_admin/admin keep the existing third-party-surface write path (the
    resolver returns False for ps_admin on sales capabilities, so it is the
    OR, not the replacement); everyone else needs CAP_EDIT on the customer
    (a junction auditor is therefore read-only).
    """
    if customer_id is None or ps_role_ok(user):
        return
    if not sales_access.can(user, db, sales_access.CAP_EDIT, customer_id):
        raise HTTPException(status_code=403, detail="Not authorized to modify this customer")


def _service_customer_id(db: Session, service_id: int) -> int | None:
    row = db.query(TPSModel.customer_id).filter(TPSModel.id == service_id).first()
    return row[0] if row else None


def _document_customer_id(db: Session, document_id: int) -> int | None:
    row = db.query(TPSDocModel.customer_id).filter(TPSDocModel.id == document_id).first()
    return row[0] if row else None


def _require_in_scope(user: dict, customer_id: int | None, detail: str) -> None:
    """404 (same as missing) when an existing record's customer is out of
    scope; a missing record (None) keeps its existing not-found path.

    The PS-surface basis is junction-only by design
    (ps_admin confinement; never the central basis).
    """
    if customer_id is not None and not ps_customer_read_ok(user, customer_id):
        raise HTTPException(status_code=404, detail=detail)


@router.get(
    "/api/customers/{customer_id}/third-party-services/",
    response_model=list[ThirdPartyServiceResponse],
)
def list_third_party_services(
    request: Request,
    customer_id: int,
    status: str | None = None,
    category: str | None = None,
    search: str | None = None,
    sort: str = "created_at",
    direction: str = "desc",
    db: Session = Depends(get_db),
):
    """List a customer's third-party service engagements (PS-gated)."""
    user = require_ps_customer_access(request, customer_id)
    items = tps.list_for_customer(
        db,
        user,
        customer_id,
        status=status,
        category=category,
        search=search,
        sort=sort,
        direction=direction,
    )
    return [s.to_dict() for s in items]


@router.post(
    "/api/customers/{customer_id}/third-party-services/",
    response_model=ThirdPartyServiceResponse,
    status_code=201,
)
def create_third_party_service(
    request: Request,
    customer_id: int,
    payload: ThirdPartyServiceCreate,
    db: Session = Depends(get_db),
):
    """Create an engagement (PS write-gated: ps_admin/admin or owner/member)."""
    user = require_ps_customer_access(request, customer_id)
    if not ps_customer_write_ok(user, customer_id):
        raise HTTPException(status_code=403, detail="Write access required")
    _require_edit(user, db, customer_id)
    return tps.create(db, user, customer_id, payload).to_dict()


@router.get(
    "/api/third-party-services/{service_id}/",
    response_model=ThirdPartyServiceResponse,
)
def get_third_party_service(
    request: Request, service_id: int, db: Session = Depends(get_db)
):
    """Get an engagement by id (404 missing or out of scope — no leak)."""
    user = _require_user(request)
    _require_in_scope(user, _service_customer_id(db, service_id), "Engagement not found")
    svc = tps.get(db, user, service_id)
    if svc is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    return svc.to_dict()


@router.put(
    "/api/third-party-services/{service_id}/",
    response_model=ThirdPartyServiceResponse,
)
def update_third_party_service(
    request: Request,
    service_id: int,
    payload: ThirdPartyServiceUpdate,
    db: Session = Depends(get_db),
):
    """Update an engagement (only provided fields; use_case_ids present =
    full link replacement)."""
    user = _require_user(request)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields provided to update")
    customer_id = _service_customer_id(db, service_id)
    _require_in_scope(user, customer_id, "Engagement not found")
    _require_edit(user, db, customer_id)
    updated = tps.update(db, user, service_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    return updated.to_dict()


@router.delete(
    "/api/third-party-services/{service_id}/",
    status_code=204,
)
def delete_third_party_service(
    request: Request, service_id: int, db: Session = Depends(get_db)
):
    """Delete an engagement (cascades documents + use-case links)."""
    user = _require_user(request)
    customer_id = _service_customer_id(db, service_id)
    _require_in_scope(user, customer_id, "Engagement not found")
    _require_edit(user, db, customer_id)
    if not tps.delete(db, user, service_id):
        raise HTTPException(status_code=404, detail="Engagement not found")


# ── documents ─────────────────────────────────────────────────────────────────


@router.get(
    "/api/third-party-services/{service_id}/documents/",
    response_model=list[ThirdPartyServiceDocumentResponse],
)
def list_third_party_service_documents(
    request: Request, service_id: int, db: Session = Depends(get_db)
):
    """List an engagement's documents (no blobs in the list response)."""
    user = _require_user(request)
    _require_in_scope(user, _service_customer_id(db, service_id), "Engagement not found")
    docs = tps.list_documents(db, user, service_id)
    return [d.to_dict() for d in docs]


@router.post(
    "/api/third-party-services/{service_id}/documents/",
    response_model=ThirdPartyServiceDocumentResponse,
    status_code=201,
)
async def upload_third_party_service_document(
    request: Request,
    service_id: int,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    title: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Upload a tracked document (store-first; explicit 413 at >10MB)."""
    user = _require_user(request)
    customer_id = _service_customer_id(db, service_id)
    _require_in_scope(user, customer_id, "Engagement not found")
    _require_edit(user, db, customer_id)
    file_name = file.filename or ""
    if not file_name or "." not in file_name:
        raise HTTPException(
            status_code=400,
            detail="Upload must have a filename with an extension",
        )
    file_data = await read_upload_bytes(file)
    doc = tps.store_document(
        db, user, service_id, document_type, file_name, file_data, title
    )
    return doc.to_dict()


@router.get("/api/third-party-services/{document_id}/download/")
def download_third_party_service_document(
    request: Request, document_id: int, db: Session = Depends(get_db)
):
    """Download the original document bytes (knowledge download precedent)."""
    user = _require_user(request)
    _require_in_scope(user, _document_customer_id(db, document_id), "Document not found")
    doc = tps.get_document(db, user, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(
        content=doc.file_data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{doc.file_name}"'
        },
    )


@router.delete(
    "/api/third-party-services/{service_id}/documents/{document_id}/",
    status_code=204,
)
def delete_third_party_service_document(
    request: Request,
    service_id: int,
    document_id: int,
    db: Session = Depends(get_db),
):
    """Delete a tracked document (nested under the engagement — the bare
    ``DELETE /api/third-party-services/{id}/`` pattern is owned by the
    engagement delete; plan §4.3's two bare-id DELETEs would have collided)."""
    user = _require_user(request)
    customer_id = _document_customer_id(db, document_id)
    _require_in_scope(user, customer_id, "Document not found")
    _require_edit(user, db, customer_id)
    if not tps.delete_document(db, user, document_id):
        raise HTTPException(status_code=404, detail="Document not found")


# ── cross-account listing (admin + ps_admin only) ────────────────────────────


@router.get(
    "/api/admin/third-party-services/",
    response_model=list[ThirdPartyServiceResponse],
)
def list_all_third_party_services(
    request: Request,
    status: str | None = None,
    category: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
):
    """Cross-account engagement listing — admin/ps_admin only (§4.5)."""
    user = _require_user(request)
    items = tps.cross_account_list(
        db, user, status=status, category=category, search=search
    )
    return [s.to_dict() for s in items]
