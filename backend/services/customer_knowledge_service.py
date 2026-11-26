"""Customer knowledge service layer.

Business logic for customer environment knowledge management:
- Create/read/update/delete customer knowledge entries
- Docling-based document normalization into canonical Markdown

- CustomerUser scoping via junction table (route layer owns auth; this
  layer owns the data behavior)

Processing flow (plan items 3, 7, 9, 13, 14):

    upload ──> persist ORIGINAL (store-first; a Docling outage must not
               lose an uploaded file) ──> mark PROCESSING ──> return
    worker ──> Markdown short-circuit (.md files, no Docling round-trip)
              or the configured provider (build_converter → convert)
           ──> persist normalized Markdown + metadata ──> READY
           ──> any failure ──> FAILED + processing_error (original kept,
               recoverable via Reprocess)

The background worker is an application-managed single-thread executor
(plan item 9: no new external queue system). The worker opens its OWN DB
session (``get_session``) — it must never use a request session, and each
job commits independently so one failure cannot roll back another.
"""

import logging
import queue
import threading
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.knowledge_ingestion import ingest_customer_knowledge
from backend.models.customer_knowledge import (
    STATUS_FAILED,
    STATUS_PROCESSING,
    STATUS_READY,
    STATUS_UPLOADED,
)
from backend.models.customer_knowledge import (
    CustomerKnowledge as CKModel,
)
from backend.models.use_case import CustomerUser  # noqa: F401  (auth context)
from backend.services.docling_service import (
    is_markdown_upload,
    normalize_markdown_text,
)
from backend.services.document_provider import (
    DocumentConverter,
    ProviderError,
    build_converter,
    file_extension,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _mime_for_extension(filename: str) -> str:
    """Deterministic extension → content-type mapping (upload metadata)."""
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in (filename or "") else ""
    return {
        ".pdf": "application/pdf",
        ".csv": "text/csv",
        ".tsv": "text/tab-separated-values",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".ppt": "application/vnd.ms-powerpoint",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".html": "text/html",
        ".htm": "text/html",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(ext, "application/octet-stream")


# ----------------------------------------------------------------------
# Read / update / delete (regression-safe CRUD)
# ----------------------------------------------------------------------


def get_customer_knowledge_list(db: Session, customer_id: int) -> list[CKModel]:
    """List all knowledge entries for a customer."""
    return db.query(CKModel).filter(CKModel.customer_id == customer_id).all()


def get_customer_knowledge(db: Session, knowledge_id: int, customer_id: int) -> CKModel | None:
    """Fetch one entry scoped to a customer (None when missing/out-of-scope)."""
    return (
        db.query(CKModel)
        .filter(CKModel.id == knowledge_id, CKModel.customer_id == customer_id)
        .first()
    )


def update_customer_knowledge(
    db: Session,
    knowledge_id: int,
    customer_id: int,
    payload: dict,
) -> CKModel | None:
    """Update a knowledge entry's structured fields."""
    record = db.query(CKModel).filter(
        CKModel.id == knowledge_id,
        CKModel.customer_id == customer_id,
    ).first()

    if not record:
        return None

    if "classified_type" in payload:
        record.knowledge_type = payload["classified_type"]
    if "category" in payload:
        record.category = payload["category"]
    if "knowledge_category" in payload:
        from backend.models.customer_knowledge import KNOWLEDGE_CATEGORIES

        value = payload["knowledge_category"]
        if value is not None and value not in KNOWLEDGE_CATEGORIES:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=422,
                detail=f"knowledge_category must be one of: {', '.join(KNOWLEDGE_CATEGORIES)}",
            )
        record.knowledge_category = value
    if "extracted_text" in payload:
        record.extracted_text = payload["extracted_text"]
    if "processed" in payload:
        # Legacy mirror: keep in sync with the processing lifecycle.
        record.processed = 1 if payload["processed"] else 0

    db.commit()
    db.refresh(record)
    return record


def delete_customer_knowledge(
    db: Session,
    knowledge_id: int,
    customer_id: int,
) -> bool:
    """Delete a knowledge entry (original + normalized + extracted items).

    The item rows are deleted explicitly: the schema declares an
    ON DELETE CASCADE foreign key, but the runtime SQLite connection does
    not enforce foreign keys (PRAGMA foreign_keys is off by default), so
    without this the LLM-extracted intelligence would be orphaned.
    """
    record = db.query(CKModel).filter(
        CKModel.id == knowledge_id,
        CKModel.customer_id == customer_id,
    ).first()

    if not record:
        return False

    from backend.models.customer_knowledge import CustomerKnowledgeItem

    db.query(CustomerKnowledgeItem).filter(
        CustomerKnowledgeItem.source_knowledge_id == record.id
    ).delete(synchronize_session=False)
    db.delete(record)
    db.commit()
    return True


# ----------------------------------------------------------------------
# Upload (store-first) + normalization
# ----------------------------------------------------------------------


def _storage_path(record_id: int) -> str:
    return f"database:customer_knowledge.file_data:{record_id}"


def create_customer_knowledge(
    db: Session,
    customer_id: int,
    knowledge_type: str,
    file_name: str,
    file_data: bytes,
    extracted_text: str | None = None,
    knowledge_category: str | None = None,
) -> CKModel:
    """Persist the ORIGINAL document and mark it for processing.

    Store-first (plan item 13): the record exists and is durable before
    any Docling call, so a Docling outage can never lose an upload.
    ``knowledge_category`` (when supplied by the caller) is the
    user-authoritative classification — the LLM may only fill it when it stays None.
    """
    record = CKModel(
        customer_id=customer_id,
        knowledge_type=knowledge_type,
        file_name=file_name,
        file_data=file_data,
        uploaded_at=_utcnow(),
        processed=0,
        extracted_text=extracted_text,
        ingestion_status="pending",
        knowledge_category=knowledge_category,
        original_content_type=_mime_for_extension(file_name),
        original_storage_path=_storage_path(0),  # finalized after commit
        normalized_format="markdown",
        processing_status=STATUS_UPLOADED,
        processing_error=None,
        processing_error_kind=None,
        processor=None,
        processor_version=None,
        processing_time_seconds=None,
        processed_at=None,
        # enrichment_status keeps its NOT_RUN default (item 16: the LLM
        # stage has not started yet).
        enrichment_error=None,
        enrichment_error_kind=None,
        enrichment_model=None,
        enrichment_time_seconds=None,
        enriched_at=None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    record.original_storage_path = _storage_path(record.id)
    db.commit()
    return record


def _async_enabled() -> bool:
    """Production runs normalization on the background worker thread.

    ``SAIL_KNOWLEDGE_ASYNC=0`` (set by the test suite) runs it
    inline on the caller's session — deterministic, same connection,
    no cross-connection SQLite locking under the test StaticPool.
    """
    import os

    return os.environ.get("SAIL_KNOWLEDGE_ASYNC", "1") != "0"


def _enrichment_enabled() -> bool:
    """LLM enrichment runs automatically after Docling success.

    ``SAIL_KNOWLEDGE_ENRICHMENT=0`` (test seam — conftest sets it
    so the default knowledge tests stay deterministic and never hit the
    configured LLM; the enrichment test files re-enable it with a mocked
    AIClient) disables the auto-call.
    """
    import os

    return os.environ.get("SAIL_KNOWLEDGE_ENRICHMENT", "1") != "0"


def enqueue_normalization(record_id: int, db: Session | None = None,
                          force_reprocess: bool = False) -> None:
    """Mark PROCESSING and dispatch the normalization job.

    With ``db`` (the route's request session) the status flip happens on
    that session — committed by the route's normal flow (a commit on a
    SECOND session over the shared dev SQLite connection destroys the
    caller's open transaction; in tests it destroys the fixture
    savepoint). Without it, an own session is used (production
    reprocess/worker paths).

    ``force_reprocess`` marks the job as a full-pipeline rerun (item 15):
    the worker reruns Docling AND enrichment on an already-READY record
    instead of the plain-job no-op path.
    """
    if db is not None:
        record = db.query(CKModel).filter(CKModel.id == record_id).first()
        if record is not None and record.processing_status in (STATUS_UPLOADED, STATUS_FAILED):
            record.processing_status = STATUS_PROCESSING
            record.processing_error = None
            record.processing_error_kind = None
        return _dispatch(record_id, db, force_reprocess=force_reprocess)

    own = get_worker_session()
    try:
        record = own.query(CKModel).filter(CKModel.id == record_id).first()
        if record is not None and record.processing_status in (STATUS_UPLOADED, STATUS_FAILED):
            record.processing_status = STATUS_PROCESSING
            record.processing_error = None
            record.processing_error_kind = None
            own.commit()
    except Exception:
        logger.exception("enqueue: failed to mark PROCESSING for knowledge id %s", record_id)
        own.rollback()
    finally:
        own.close()
    _dispatch(record_id, None, force_reprocess=force_reprocess)


def _dispatch(record_id: int, db: Session | None = None,
              force_reprocess: bool = False) -> None:
    """Worker dispatch (production) or inline execution (test seam).

    In inline mode the normalization runs on the caller's session (the
    route's request session or the test fixture session) so every commit
    lands on the caller's connection — a second session's commit is
    invisible to the caller's open transaction.
    """
    if _async_enabled():
        global _worker_started
        with _worker_lock:
            if not _worker_started:
                _worker_started = True
                _worker.start()
        if force_reprocess:
            _set_force_flag(record_id)
        _JOB_QUEUE.put(record_id)
    else:
        normalize_record(record_id, db=db, force_reprocess=force_reprocess)


def normalize_record(record_id: int, db: Session | None = None,
                     force_reprocess: bool = False) -> None:
    """Run the document normalization for one record (worker context).

    - ``.md`` uploads: in-process short-circuit (no Docling round-trip,
      plan item 8).
    - Uploads the configured provider supports (``build_converter``, resolved
      per job): ``converter.convert``.
    - Unsupported uploads: FAILED ``unsupported_document`` (original kept).

    Success (incl. partial_success) → READY + normalized Markdown.
    Any ProviderError / failure class → FAILED + processing_error. The
    original file is NEVER deleted here (plan item 14).

    LLM enrichment runs
    automatically after a successful normalization. On a record that is
    already READY, a plain job skips normalization and only fills in a
    missing enrichment (e.g. the enrichment FAILED previously — the
    normalized content stays available and Docling is NOT rerun);
    ``force_reprocess=True`` (the explicit Reprocess action) reruns the
    full pipeline, reconciling any previous enrichment.

    ``db``: session to use. Production worker leaves it None → own
    session (never a request session). Tests pass the fixture session →
    deterministic inline execution on the test connection.
    """
    owns_session = db is None
    if owns_session:
        db = get_worker_session()
    record: CKModel | None = None
    try:
        record = db.query(CKModel).filter(CKModel.id == record_id).first()
        if record is None:
            return
        if record.processing_status == STATUS_READY:
            if not force_reprocess:
                # Already normalized: plain job is a no-op, EXCEPT that a
                # missing/failed enrichment is filled in (item 16 — retry
                # enrichment without rerunning Docling). The _maybe_enrich
                # guard skips in-flight/succeeded states.
                _maybe_enrich(db, record)
                return
            # force_reprocess (item 15): reset the enrichment so the
            # re-run reconciles the previous extraction results.
            _reset_enrichment_state(record)
            # fall through to a full rerun

        # The provider is resolved per job on the worker's own session, so
        # the admin-saved selection (DB-only) is runtime-effective here.
        # Built after the record query so a construction-time config error
        # (non-https endpoint, unresolvable ssl_verify) lands on the record
        # instead of leaving it stuck in PROCESSING.
        try:
            converter = build_converter(db)
        except ValueError as exc:
            _mark_failed(db, record, kind="invalid_configuration", message=str(exc))
            db.commit()
            logger.warning(
                "Document converter configuration invalid for knowledge id %s (customer %s): %s",
                record_id, record.customer_id, exc,
            )
            return

        filename = record.file_name
        if is_markdown_upload(filename):
            _normalize_markdown_inplace(db, record, converter=converter)
        elif file_extension(filename) in converter.supported_extensions():
            _normalize_via_provider(db, record, converter)
        else:
            _mark_failed(
                db, record,
                kind="unsupported_document",
                message=(
                    f"Unsupported document type '{filename}': {converter.name} does not "
                    "accept this format. Supported: "
                    f"{', '.join(sorted(converter.supported_extensions()))}. "
                    "Reupload the document in a supported format (or Markdown), "
                    "or switch the provider in Application Settings."
                ),
            )
        db.commit()
        # Two-stage pipeline:
        # enrichment runs automatically right after a successful
        # normalization, on the same session. A FAILED Docling result
        # never reaches this point — enrichment stays NOT_RUN.
        _maybe_enrich(db, record)
    except ProviderError as exc:
        try:
            if record is not None:
                _mark_failed(db, record, kind=exc.kind, message=exc.message)
                db.commit()
        except Exception:
            logger.exception("failed to persist FAILED state for knowledge id %s", record_id)
            db.rollback()
        logger.warning(
            "Document normalization failed for knowledge id %s (customer %s): [%s] %s",
            record_id, getattr(record, "customer_id", None) if record is not None else None,
            exc.kind, exc.message,
        )
    except Exception:
        # Persistence failure or unexpected error: leave the record in a
        # recoverable FAILED state when possible (plan item 13).
        try:
            if record is not None:
                _mark_failed(db, record, kind="local_persistence_failure", message="Local processing error — see server logs.")
                db.commit()
        except Exception:
            db.rollback()
        logger.exception("unexpected error normalizing knowledge id %s", record_id)
    finally:
        if owns_session:
            db.close()


def _normalize_markdown_inplace(db: Session, record: CKModel, converter: DocumentConverter) -> None:
    """Markdown short-circuit (plan item 8) — provider-agnostic, no converter call."""
    try:
        markdown = normalize_markdown_text(record.file_data)
    except ProviderError as exc:
        _mark_failed(db, record, kind=exc.kind, message=exc.message)
        return
    record.normalized_content = markdown
    record.normalized_format = "markdown"
    record.processor = "markdown-native"
    record.processor_version = None
    record.processing_time_seconds = 0.0
    record.processing_status = STATUS_READY
    record.processing_error = None
    record.processing_error_kind = None
    record.processed = 1
    record.ingested_at = _utcnow()
    record.processed_at = _utcnow()


def _normalize_via_provider(db: Session, record: CKModel, converter: DocumentConverter) -> None:
    """Provider conversion (plan items 5, 6)."""
    content_type = record.original_content_type or _mime_for_extension(record.file_name)
    try:
        result = converter.convert(
            record.file_data,
            record.file_name,
            content_type=content_type,
        )
    except ProviderError:
        raise  # handled by normalize_record
    record.normalized_content = result.markdown
    record.normalized_format = "markdown"
    record.processor = result.processor
    record.processor_version = result.processor_version
    record.processing_time_seconds = result.processing_time_seconds
    record.processing_status = STATUS_READY
    record.processed = 1
    record.ingested_at = _utcnow()
    record.processed_at = _utcnow()
    record.processing_error = None
    record.processing_error_kind = None
    if result.partial:
        # partial_success: output retained, warning recorded (plan item 6).
        record.processing_error = "Partial conversion: " + "; ".join(result.warnings)


def _mark_failed(db: Session, record: CKModel, kind: str, message: str) -> None:
    """Recoverable FAILED state (plan item 13): original retained."""
    record.processing_status = STATUS_FAILED
    record.processing_error = message
    record.processing_error_kind = kind
    record.processed = 0


def reprocess_customer_knowledge(
    db: Session,
    knowledge_id: int,
    customer_id: int,
) -> CKModel | None:
    """Queue a reprocess of the retained ORIGINAL (plan item 11).

    Reuses the stored file bytes and runs them through the current
    processor. Replaces the normalized derivative only — the original is
    untouched. Works after a Docling outage recovery.
    """
    record = get_customer_knowledge(db, knowledge_id, customer_id)
    if record is None:
        return None
    if record.processing_status == STATUS_PROCESSING:
        return record  # already in flight
    # Reset to PROCESSING on the request session (flushed with the
    # route's response), then dispatch as a FULL pipeline rerun (item 15:
    # rerun Docling + LLM enrichment, reconciling previous items).
    record.processing_status = STATUS_PROCESSING
    record.processing_error = None
    record.processing_error_kind = None
    _reset_enrichment_state(record)
    db.flush()
    db.refresh(record)
    enqueue_normalization(record.id, db=db, force_reprocess=True)
    return record


def _maybe_enrich(db: Session, record: "CKModel") -> None:
    """Run LLM enrichment for a READY record (items 2, 4; failures
    isolated per item 16).

    Never raises: Docling success must not be jeopardized by an LLM
    failure. An ``EnrichmentError`` marks enrichment FAILED (the
    normalized content stays available and can be retried via the
    dedicated retry path without rerunning Docling).

    No-op when: enrichment is disabled (test seam), the record is not
    READY / has no text, enrichment is already in flight, or it already
    succeeded (duplicate job).
    """
    if not _enrichment_enabled():
        return
    if record.processing_status != STATUS_READY or not record.knowledge_text:
        return
    from backend.models.customer_knowledge import (
        ENRICHMENT_ENRICHED,
        ENRICHMENT_ENRICHING,
        ENRICHMENT_FAILED,
    )
    if record.enrichment_status in (ENRICHMENT_ENRICHING, ENRICHMENT_ENRICHED):
        return
    from backend.services import knowledge_enrichment_service as kes

    record.enrichment_status = ENRICHMENT_ENRICHING
    record.enrichment_error = None
    record.enrichment_error_kind = None
    db.commit()
    try:
        kes.enrich_knowledge_record(db, record)
        db.commit()
    except kes.EnrichmentError as exc:
        record.enrichment_status = ENRICHMENT_FAILED
        record.enrichment_error = exc.message
        record.enrichment_error_kind = exc.kind
        try:
            db.commit()
        except Exception:
            db.rollback()
        logger.warning(
            "LLM enrichment failed for knowledge id %s (customer %s): [%s] %s",
            record.id, record.customer_id, exc.kind, exc.message,
        )
    except Exception:
        record.enrichment_status = ENRICHMENT_FAILED
        record.enrichment_error = "Enrichment error — see server logs."
        record.enrichment_error_kind = "local_persistence_failure"
        try:
            db.commit()
        except Exception:
            db.rollback()
        logger.exception(
            "unexpected error enriching knowledge id %s", record.id
        )


def _reset_enrichment_state(record: "CKModel") -> None:
    """Revert the enrichment layer to NOT_RUN (reprocess preparation,
    item 15). The previous items are deleted by the enrichment run
    itself (``remove_document_items``) — reconciliation happens there."""
    from backend.models.customer_knowledge import ENRICHMENT_NOT_RUN

    record.enrichment_status = ENRICHMENT_NOT_RUN
    record.enrichment_error = None
    record.enrichment_error_kind = None
    record.enriched_at = None


# Force-reprocess flags (plan item 15): the worker queue carries record
# ids only; a reprocess request marks its id so the next worker run of
# that record reruns the FULL pipeline (Docling + enrichment) instead of
# the plain-job no-op path for an already-READY document. The flag is
# consumed by the worker (single-threaded, so no race with readers).
# Enrich-only flags do the same for the dedicated retry path (item 16):
# rerun enrichment WITHOUT rerunning Docling.
_FORCE_FLAGS: "set[int]" = set()
_ENRICH_FLAGS: "set[int]" = set()
_FORCE_LOCK = threading.Lock()


def _set_force_flag(record_id: int) -> None:
    with _FORCE_LOCK:
        _FORCE_FLAGS.add(record_id)


def _consume_force_flag(record_id: int) -> bool:
    with _FORCE_LOCK:
        if record_id in _FORCE_FLAGS:
            _FORCE_FLAGS.discard(record_id)
            return True
        return False


def _set_enrich_flag(record_id: int) -> None:
    with _FORCE_LOCK:
        _ENRICH_FLAGS.add(record_id)


def _consume_enrich_flag(record_id: int) -> bool:
    with _FORCE_LOCK:
        if record_id in _ENRICH_FLAGS:
            _ENRICH_FLAGS.discard(record_id)
            return True
        return False


def enqueue_enrichment(record_id: int, db: Session | None = None) -> None:
    """Dispatch an ENRICHMENT-ONLY job (item 16 retry path).

    With ``db`` (inline/test mode) runs on the caller's session;
    otherwise marks the worker queue so the next job for this id
    performs the enrichment stage only — the Docling-normalized content
    stays as-is. The caller is responsible for the preconditions
    (record READY, enrichment not in flight) and for resetting the
    enrichment state.
    """
    if _async_enabled():
        global _worker_started
        with _worker_lock:
            if not _worker_started:
                _worker_started = True
                _worker.start()
        _set_enrich_flag(record_id)
        _JOB_QUEUE.put(record_id)
        return
    if db is not None:
        record = db.query(CKModel).filter(CKModel.id == record_id).first()
        if record is not None:
            _maybe_enrich(db, record)
    else:
        own = get_worker_session()
        try:
            record = own.query(CKModel).filter(CKModel.id == record_id).first()
            if record is not None:
                _maybe_enrich(own, record)
        finally:
            own.close()

_JOB_QUEUE: "queue.Queue[int]" = queue.Queue(maxsize=128)
_worker_started = False
_worker_lock = threading.Lock()


def get_worker_session() -> Session:
    """A fresh DB session for worker use (never a request session).

    ``get_session`` is imported INSIDE the function (not at module
    top level): tests patch ``create_engine`` before importing
    ``backend.models`` — a module-level import here would bind the
    REAL engine and make worker commits hit the real dev DB instead
    of the test database.
    """
    from backend.models.use_case import get_session

    return get_session()


def _worker_loop() -> None:
    q: queue.Queue[int] = _JOB_QUEUE
    while True:
        record_id = q.get()
        try:
            if _consume_enrich_flag(record_id):
                # Enrichment-only retry (item 16): Docling is NOT rerun.
                own = get_worker_session()
                try:
                    record = (
                        own.query(CKModel)
                        .filter(CKModel.id == record_id)
                        .first()
                    )
                    if record is not None:
                        _maybe_enrich(own, record)
                finally:
                    own.close()
            else:
                normalize_record(record_id,
                                 force_reprocess=_consume_force_flag(record_id))
        finally:
            q.task_done()


# The thread is created at import but only STARTED on first enqueue
# (``_worker_started`` guard) — import must stay side-effect free.
_worker = threading.Thread(target=_worker_loop, name="ck-normalizer", daemon=True)


# ----------------------------------------------------------------------
# Legacy pipeline wrapper (kept for the pre-Docling ingestion path)
# ----------------------------------------------------------------------


def ingest_knowledge_for_customer(
    db: Session,
    customer_id: int,
    file_data: bytes,
    file_type: str,
) -> dict:
    """Full legacy ingestion pipeline for a customer (CSV/PDF heuristics +
    context7-style domain grounding). Retained for the existing
    upload-route behavior; new uploads also normalize via Docling.
    """
    # Step 1: Parse and ground
    result = ingest_customer_knowledge(file_data, file_type, customer_id)

    # Step 2: Create database record
    if result["success"]:
        create_customer_knowledge(
            db=db,
            customer_id=customer_id,
            knowledge_type=result["classified_type"],
            file_name="uploaded_" + file_data[:8].hex()[:8] + ".bin",
            file_data=file_data,
            extracted_text=result.get("extracted_text"),
        )

    return result
