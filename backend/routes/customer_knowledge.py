"""Customer knowledge API routes.

Handles CRUD operations for customer environment knowledge entries.
All routes are gated by CustomerUser authorization, with admin bypass —
admins own all customers (same convention as customers.py,
sales_section.py, and sales_evaluations.py).
"""


from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.schemas.customer_knowledge import (
    CustomerKnowledge,
    CustomerKnowledgeUpdate,
    KnowledgeContentResponse,
    KnowledgeItemResponse,
    KnowledgeUploadResponse,
)
from backend.services import sales_access
from backend.services.customer_knowledge_service import (
    create_customer_knowledge,
    delete_customer_knowledge,
    enqueue_normalization,
    get_customer_knowledge_list,
    reprocess_customer_knowledge,
    update_customer_knowledge,
)
from backend.upload_size import read_upload_bytes

router = APIRouter(prefix="/api/customer-knowledge", tags=["customer-knowledge"])


def _require_user(request: Request) -> dict:
    """Return authenticated user dict or 401."""
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _accessible_customer_ids(user: dict, db: Session, customer_id: int | None = None) -> list[int]:
    """Customer ids the caller may act on for knowledge access.

    Central-policy basis (A-1 re-recon ruling 2026-11-01, R1 continuation):
    admins own all customers; everyone else the ``customer_scope`` union
    (junction + memberships + assignments + manager team scope). Raises
    the same 404 as a missing customer when an explicit ``customer_id``
    is outside the caller's scope (404-first, R4/Q7).
    """
    if user.get("is_admin") == 1:
        if customer_id is not None:
            return [customer_id]
        from backend.models.use_case import Customer

        return [c.id for c in db.query(Customer).all()]
    ids = sorted(sales_access.customer_scope(user, db))
    if customer_id is not None and customer_id not in ids:
        raise HTTPException(status_code=404, detail="Customer not found")
    return [customer_id] if customer_id is not None else ids


def _accessible_record(db: Session, user: dict, knowledge_id: int):
    """Return the knowledge entry if it exists and the caller may access it.

    Central-policy basis (A-1 re-recon ruling 2026-11-01): admins own all
    customers; other callers need the entry's customer in
    ``customer_scope``. Returns None when the entry is missing or out of
    scope (routes surface a 404).
    """
    from backend.models.customer_knowledge import CustomerKnowledge as CKModel

    record = db.query(CKModel).filter(CKModel.id == knowledge_id).first()
    if record is None:
        return None
    if (
        user.get("is_admin") == 1
        or record.customer_id in sales_access.customer_scope(user, db)
    ):
        return record
    return None


def _require_write(user: dict, db: Session, customer_id: int) -> None:
    """Require CAP_KNOWLEDGE; auditors and section-only inside sales cannot write.

    ACCOUNT_SECTIONS has no knowledge entry, so this stays unsectioned.
    """
    if not sales_access.can(user, db, sales_access.CAP_KNOWLEDGE, customer_id):
        raise HTTPException(status_code=403, detail="Not authorized to modify this customer")


@router.get("/", response_model=list[CustomerKnowledge])
def list_customer_knowledge(
    request: Request,
    customer_id: int | None = None,
    db: Session = Depends(get_db),
):
    """List knowledge entries for the authenticated user's customers.

    Auth-gated: owner/admin/member per CustomerUser junction; admins bypass
    the junction (own all customers). Optionally filter to a single customer
    via ``customer_id`` (validated against the caller's scope).
    """
    user = _require_user(request)
    # Customer ids the caller may read (admins own all customers).
    customer_ids = _accessible_customer_ids(user, db, customer_id)
    if not customer_ids:
        return []

    all_entries = []
    for cust_id in customer_ids:
        entries = get_customer_knowledge_list(db, customer_id=cust_id)
        all_entries.extend(entries)
    return all_entries


@router.post("/", response_model=KnowledgeUploadResponse)
async def upload_customer_knowledge(
    request: Request,
    file: UploadFile = File(...),
    customer_id: int | None = Form(None),
    knowledge_category: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Upload a customer knowledge document (store-first, async processing).

    Accepted types: any Docling-supported format (PDF, CSV, DOCX, PPTX,
    HTML, ODF, images, ...) plus Markdown (short-circuited, no Docling
    round-trip). Optionally target a specific customer via the
    ``customer_id`` form field (validated against the caller's scope;
    admins own all customers); defaults to the first accessible customer.

    ``knowledge_category`` (CHANGELOG 0.1.2 item 1): one of
    the ``KNOWLEDGE_CATEGORIES`` slugs. A user-selected category is
    AUTHORITATIVE — the LLM may only suggest one when it is absent.
    422 when an out-of-vocabulary slug is supplied.

    The upload returns once the ORIGINAL is durably stored and processing
    has been initiated (plan item 9): the record is PROCESSING and the
    UI polls its status until READY or FAILED, then watches
    ``enrichment_status`` through ENRICHING → ENRICHED/FAILED.
    """
    user = _require_user(request)
    if knowledge_category is not None:
        from backend.models.customer_knowledge import KNOWLEDGE_CATEGORIES

        knowledge_category = knowledge_category.strip() or None
        if knowledge_category is not None and knowledge_category not in KNOWLEDGE_CATEGORIES:
            raise HTTPException(
                status_code=422,
                detail=f"knowledge_category must be one of: {', '.join(KNOWLEDGE_CATEGORIES)}",
            )
    if customer_id is not None:
        _accessible_customer_ids(user, db, customer_id)  # 404 if out of scope (404-first)
        # Resolved target customer (int): explicit form value.
        target_customer_id: int = customer_id
    else:
        accessible = _accessible_customer_ids(user, db)
        if not accessible:
            raise HTTPException(status_code=403, detail="No accessible customers")
        # Defaults to the caller's first accessible customer.
        target_customer_id = int(accessible[0])
    _require_write(user, db, target_customer_id)

    filename = file.filename or ""
    if not filename or "." not in filename:
        raise HTTPException(status_code=400, detail="Upload must have a filename with an extension")

    file_data = await read_upload_bytes(file)

    # Knowledge type classification: legacy heuristic for csv/pdf (regression
    # behavior), deterministic file-kind for everything else.
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext in (".csv", ".pdf"):
        from backend.knowledge_ingestion import ingest_customer_knowledge

        result = ingest_customer_knowledge(file_data, ext[1:], target_customer_id)
        knowledge_type = result["classified_type"]
        warnings = list(result.get("warnings") or [])
        entries_count = len(result.get("entries") or [])
        # The legacy pipeline's extraction text (when any) is retained as
        # the pre-Docling fallback content.
        extracted_text = result.get("extracted_text") or None
    else:
        knowledge_type = {
            ".md": "markdown",
            ".markdown": "markdown",
            ".txt": "text",
            ".doc": "document",
            ".docx": "document",
            ".xls": "spreadsheet",
            ".xlsx": "spreadsheet",
            ".ppt": "presentation",
            ".pptx": "presentation",
            ".html": "html",
            ".htm": "html",
            ".tsv": "table",
            ".png": "image",
            ".jpg": "image",
            ".jpeg": "image",
        }.get(ext, "file")
        warnings: list[str] = []
        entries_count = 0
        extracted_text = None

    # Store-first: persist the original (knowledge_category is the
    # user's authoritative classification — item 1), then kick off
    # background normalization + enrichment (an LLM outage cannot lose
    # the upload).
    db_record = create_customer_knowledge(
        db=db,
        customer_id=target_customer_id,
        knowledge_type=knowledge_type,
        file_name=filename,
        file_data=file_data,
        extracted_text=extracted_text,
        knowledge_category=knowledge_category,
    )
    enqueue_normalization(db_record.id, db=db)

    return KnowledgeUploadResponse(
        success=True,
        knowledge_id=db_record.id,
        classified_type=knowledge_type,
        entries_count=entries_count,
        warnings=warnings,
        processing_status="PROCESSING",
    )


@router.get("/{knowledge_id}", response_model=CustomerKnowledge)
def get_customer_knowledge_entry(
    request: Request,
    knowledge_id: int,
    db: Session = Depends(get_db),
):
    """Get a single knowledge entry by ID (admins bypass the junction)."""
    user = _require_user(request)
    record = _accessible_record(db, user, knowledge_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    return record


@router.put("/{knowledge_id}", response_model=CustomerKnowledge)
def update_customer_knowledge_entry(
    request: Request,
    knowledge_id: int,
    payload: CustomerKnowledgeUpdate,
    db: Session = Depends(get_db),
):
    """Update a knowledge entry's structured fields (JSON body).

    Accepted keys: classified_type, category, extracted_text, processed.
    (Previously called the 4-argument service with 3 arguments — TypeError.)
    """
    user = _require_user(request)
    record = _accessible_record(db, user, knowledge_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    _require_write(user, db, record.customer_id)
    updated = update_customer_knowledge(
        db, knowledge_id, record.customer_id, payload.model_dump(exclude_none=True)
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    return updated


@router.delete("/{knowledge_id}")
def delete_customer_knowledge_entry(
    request: Request,
    knowledge_id: int,
    db: Session = Depends(get_db),
):
    """Delete a knowledge entry (admins bypass the junction)."""
    user = _require_user(request)
    record = _accessible_record(db, user, knowledge_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    _require_write(user, db, record.customer_id)
    success = delete_customer_knowledge(db, knowledge_id, record.customer_id)
    if success:
        return {"detail": "Knowledge entry deleted"}
    raise HTTPException(status_code=404, detail="Knowledge entry not found")


@router.get("/{knowledge_id}/content", response_model=KnowledgeContentResponse)
def get_knowledge_normalized_content(
    request: Request,
    knowledge_id: int,
    db: Session = Depends(get_db),
):
    """Return the normalized (canonical) Markdown content of a document.

    409 when the document has not reached READY yet (processing in
    flight or failed — the caller should surface the status/error from
    the detail endpoint).
    """
    user = _require_user(request)
    record = _accessible_record(db, user, knowledge_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    if record.processing_status != "READY" or not record.normalized_content:
        raise HTTPException(
            status_code=409,
            detail=f"Normalized content not available yet (status: {record.processing_status})",
        )
    return KnowledgeContentResponse(
        id=record.id,
        customer_id=record.customer_id,
        file_name=record.file_name,
        normalized_format=record.normalized_format or "markdown",
        normalized_content=record.knowledge_text,
        processor=record.processor,
        processing_status=record.processing_status,
        processed_at=record.processed_at,
    )


@router.post("/{knowledge_id}/reprocess", response_model=CustomerKnowledge)
def reprocess_knowledge_entry(
    request: Request,
    knowledge_id: int,
    db: Session = Depends(get_db),
):
    """Reprocess the retained ORIGINAL through the current processor.

    Replaces the normalized derivative only — the original file is never
    touched (plan items 11, 14). Allows recovery after a Docling outage.
    Returns the entry immediately; the caller polls its status.
    """
    user = _require_user(request)
    record = _accessible_record(db, user, knowledge_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    _require_write(user, db, record.customer_id)
    if record.processing_status == "PROCESSING":
        raise HTTPException(
            status_code=409,
            detail="Reprocess already in progress — poll the entry status",
        )
    updated = reprocess_customer_knowledge(db, knowledge_id, record.customer_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    return updated


@router.post("/{knowledge_id}/enrich", response_model=CustomerKnowledge)
def retry_enrichment(
    request: Request,
    knowledge_id: int,
    db: Session = Depends(get_db),
):
    """Retry LLM enrichment for a READY document (CHANGELOG 0.1.2
    items 2, 16): a Docling SUCCESS + LLM FAILURE leaves the normalized
    content available; this endpoint re-runs ONLY the enrichment stage
    (Docling is NOT rerun — that is Reprocess's job).

    409 when the document is not READY (normalization must succeed first)
    or enrichment is already in flight. Returns the entry immediately;
    the caller polls its ``enrichment_status``.
    """
    user = _require_user(request)
    record = _accessible_record(db, user, knowledge_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    _require_write(user, db, record.customer_id)
    if record.processing_status != "READY" or not record.normalized_content:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Document is not READY (status: {record.processing_status}) — "
                "Docling normalization must succeed before enrichment can run"
            ),
        )
    if record.enrichment_status == "ENRICHING":
        raise HTTPException(
            status_code=409, detail="Enrichment already in progress — poll the entry status"
        )
    # Reset the enrichment layer (reconciles any partially applied
    # previous items — the enrichment run deletes this document's old
    # items before persisting the new ones), then dispatch: the worker
    # runs the LLM call out of the request (production); tests run it
    # inline on the request session (deterministic).
    from backend.services.customer_knowledge_service import (
        _enrichment_enabled,
        _reset_enrichment_state,
        enqueue_enrichment,
    )

    if not _enrichment_enabled():
        # Test seam disabled — nothing to run.
        return record
    _reset_enrichment_state(record)
    db.commit()
    db.refresh(record)
    enqueue_enrichment(record.id, db=db)
    db.commit()
    db.refresh(record)
    return record


@router.get("/{knowledge_id}/items", response_model=list[KnowledgeItemResponse])
def list_knowledge_items(
    request: Request,
    knowledge_id: int,
    db: Session = Depends(get_db),
):
    """List the LLM-extracted intelligence items for one document
    (CHANGELOG 0.1.2 items 6, 13): the traceable record of
    what the enrichment learned — provenance, evidence, and the domain
    objects each item was applied to."""
    user = _require_user(request)
    record = _accessible_record(db, user, knowledge_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    from backend.models.customer_knowledge import CustomerKnowledgeItem

    items = (
        db.query(CustomerKnowledgeItem)
        .filter(
            CustomerKnowledgeItem.source_knowledge_id == record.id,
            CustomerKnowledgeItem.customer_id == record.customer_id,
        )
        .order_by(CustomerKnowledgeItem.kind, CustomerKnowledgeItem.id)
        .all()
    )
    legacy = record.knowledge_type == "rvtools_report" and record.processor_version != "rvtools-summary/2"
    return [{**i.to_dict(), "legacy_rvtools_source": legacy} for i in items]


@router.get("/{knowledge_id}/download")
def download_knowledge_original(
    request: Request,
    knowledge_id: int,
    db: Session = Depends(get_db),
):
    """Download the ORIGINAL uploaded document (auth-gated).

    The original is always retained after successful conversion (plan
    item 14); this endpoint serves it back unchanged.
    """
    user = _require_user(request)
    record = _accessible_record(db, user, knowledge_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    headers = {"Content-Disposition": f'attachment; filename="{record.file_name}"'}
    if record.knowledge_type == "rvtools_report" and record.processor_version != "rvtools-summary/2":
        headers["Warning"] = '299 S-A-I-L "Legacy RVTools totals may be incomplete; see current footprint"'
    return Response(
        content=record.file_data,
        media_type=record.original_content_type or "application/octet-stream",
        headers=headers,
    )
