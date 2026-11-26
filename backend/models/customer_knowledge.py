"""Customer knowledge SQLAlchemy model.

Original + normalized document pair (PLAN.md part 43 /
CHANGELOG 0.1.1):

- ``file_name`` / ``file_data`` hold the ORIGINAL uploaded document,
  unchanged. ``file_name`` is the original filename;
  ``original_content_type`` is its MIME-ish type (extension-derived).
  ``original_storage_path`` is the DB location descriptor
  (``database:customer_knowledge.file_data:<id>``).
- ``normalized_content`` is the canonical Markdown representation produced
  by Docling (or the in-process Markdown short-circuit). All Customer
  Knowledge consumers (search, AI context, evaluation, briefs, future
  RAG) read the normalized content; the original is retained for
  reprocessing, download, and future format changes.
- ``processing_status`` is the processing lifecycle:
  UPLOADED -> PROCESSING -> READY | FAILED. The legacy ``processed``
  integer is kept for compatibility; new code sets/reads it as a mirror
  of ``processing_status == READY`` (1) / otherwise (0).
- ``extracted_text`` is the legacy text field (pre-Docling ingestion);
  ``normalized_content`` supersedes it — consumers fall back to
  ``extracted_text`` only when no normalized content exists.
"""

import re
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import relationship  # noqa: F401  (kept for parity)

from backend.models.use_case import Base

# Processing lifecycle (plan item 7).
STATUS_UPLOADED = "UPLOADED"
STATUS_PROCESSING = "PROCESSING"
STATUS_READY = "READY"
STATUS_FAILED = "FAILED"
PROCESSING_STATUSES = (STATUS_UPLOADED, STATUS_PROCESSING, STATUS_READY, STATUS_FAILED)

# Processor identifiers.
PROCESSOR_DOCLING = "docling"
PROCESSOR_MARKDOWN_NATIVE = "markdown-native"

# ── Knowledge categories (CHANGELOG 0.1.2 item 1) ──────────
# Controlled vocabulary for the document knowledge category. Stored as
# free-form String so the vocabulary can grow without a destructive
# migration; the service layer validates against this list. The legacy
# ``classification`` column is the pre-enrichment LLM *type* guess
# (technology/organization/etc.) — a different axis, left untouched.
KNOWLEDGE_CATEGORIES = [
    "general_customer_information",
    "business_strategy_goals",
    "business_challenges_pain_points",
    "technology_infrastructure",
    "applications_platforms",
    "security_compliance",
    "operations_processes",
    "projects_initiatives",
    "products_services",
    "vendors_partners",
    "organizational_stakeholder_information",
    "use_cases",
    "opportunities",
    "assessments_discovery",
    "commercial_procurement",
    "meeting_notes_customer_communications",
    "architecture_technical_documentation",
    "other",
]


# ── LLM enrichment lifecycle (CHANGELOG 0.1.2 items 2, 16) ──
ENRICHMENT_NOT_RUN = "NOT_RUN"
ENRICHMENT_ENRICHING = "ENRICHING"
ENRICHMENT_ENRICHED = "ENRICHED"
ENRICHMENT_FAILED = "FAILED"
ENRICHMENT_SKIPPED = "SKIPPED"  # no normalized content / no LLM configured
ENRICHMENT_STATUSES = (
    ENRICHMENT_NOT_RUN,
    ENRICHMENT_ENRICHING,
    ENRICHMENT_ENRICHED,
    ENRICHMENT_FAILED,
    ENRICHMENT_SKIPPED,
)


class CustomerKnowledge(Base):
    __tablename__ = "customer_knowledge"
    # IDs are never reissued (ER-12): retained references must not attach to a new row.
    __table_args__ = {"sqlite_autoincrement": True}

    id = sa.Column(sa.Integer, primary_key=True, nullable=False, index=True)
    customer_id = sa.Column(sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    knowledge_type = sa.Column(sa.String(50), nullable=False)
    file_name = sa.Column(sa.String(255), nullable=False)
    file_data = sa.Column(sa.LargeBinary, nullable=False)
    uploaded_at = sa.Column(sa.DateTime, nullable=False)
    processed = sa.Column(sa.Integer, nullable=False, default=0)
    extracted_text = sa.Column(sa.Text, nullable=True)
    ingested_at = sa.Column(sa.DateTime, nullable=True)
    ingestion_status = sa.Column(sa.String(50), nullable=True, default="pending")
    classification = sa.Column(sa.String(50), nullable=True)
    # Legacy free-text category column (pre-enrichment upload heuristic);
    # kept for compatibility. The enrichment era uses
    # ``knowledge_category`` (controlled vocabulary).
    category = sa.Column(sa.String(50), nullable=True)
    # Knowledge category (CHANGELOG 0.1.2 item 1): one of
    # KNOWLEDGE_CATEGORIES, user-authoritative when set at upload; the LLM
    # may suggest one when the user did not choose (item 1).
    knowledge_category = sa.Column(sa.String(60), nullable=True, index=True)

    # ── Docling normalization layer (plan item 7) ────────────────────
    original_content_type = sa.Column(sa.String(100), nullable=True)
    original_storage_path = sa.Column(sa.String(255), nullable=True)
    normalized_format = sa.Column(sa.String(20), nullable=True)
    normalized_content = sa.Column(sa.Text, nullable=True)
    processing_status = sa.Column(sa.String(20), nullable=False, default=STATUS_UPLOADED)
    processing_error = sa.Column(sa.Text, nullable=True)
    processing_error_kind = sa.Column(sa.String(50), nullable=True)
    processor = sa.Column(sa.String(50), nullable=True)
    processor_version = sa.Column(sa.String(50), nullable=True)
    processing_time_seconds = sa.Column(sa.Float, nullable=True)
    processed_at = sa.Column(sa.DateTime, nullable=True)

    # ── LLM enrichment layer (CHANGELOG 0.1.2) ──────────
    # Docling and LLM enrichment failures are tracked SEPARATELY (item 16):
    # processing_status covers Docling; enrichment_status covers the LLM.
    enrichment_status = sa.Column(
        sa.String(20), nullable=False, default=ENRICHMENT_NOT_RUN
    )
    enrichment_error = sa.Column(sa.Text, nullable=True)
    enrichment_error_kind = sa.Column(sa.String(50), nullable=True)
    enrichment_model = sa.Column(sa.String(100), nullable=True)
    enrichment_time_seconds = sa.Column(sa.Float, nullable=True)
    enriched_at = sa.Column(sa.DateTime, nullable=True)

    @property
    def knowledge_text(self):
        """Canonical text for consumer-side parsing (plan item 16): the
        normalized Markdown first, falling back to the legacy
        ``extracted_text`` (pre-Docling rows / backfilled legacy data).
        Returns None when no text of either kind exists."""
        text = self.normalized_content or self.extracted_text
        if text and self.knowledge_type == "rvtools_report" and self.processor_version != "rvtools-summary/2":
            # Legacy generated totals treated unknown source rows as zero.
            # Keep the stored original intact but never pass those numbers on
            # as current evidence through the shared knowledge-text accessor.
            text = re.sub(
                r"(?m)^- (total_cores|total_memory_gb|total_vcpus|total_vm_memory_gb|powered_on_vms):[^\r\n]*$",
                r"- \1: unavailable (legacy total; see current RVTools footprint)",
                text,
            )
        return text

    def to_dict(self) -> dict:
        """Wire representation for this record.

        Deliberately omits ``file_data`` (binary blob) and
        ``normalized_content`` (potentially large) — both are served via
        the dedicated content/download endpoints. ``original_filename`` is
        exposed alongside ``file_name`` for the new contract.
        """
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "knowledge_type": self.knowledge_type,
            "file_name": self.file_name,
            "original_filename": self.file_name,
            "original_content_type": self.original_content_type,
            "original_storage_path": self.original_storage_path,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
            "processed": bool(self.processed),
            "extracted_text": self.extracted_text,
            "ingested_at": self.ingested_at.isoformat() if self.ingested_at else None,
            "ingestion_status": self.ingestion_status,
            "classification": self.classification,
            "category": self.category,
            "knowledge_category": self.knowledge_category,
            "normalized_format": self.normalized_format,
            "normalized_content_present": bool(self.normalized_content),
            "processing_status": self.processing_status,
            "processing_error": self.processing_error,
            "processing_error_kind": self.processing_error_kind,
            "processor": self.processor,
            "processor_version": self.processor_version,
            "processing_time_seconds": self.processing_time_seconds,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            # LLM enrichment layer (CHANGELOG 0.1.2 item 16):
            # tracked separately from Docling processing_status.
            "enrichment_status": self.enrichment_status,
            "enrichment_error": self.enrichment_error,
            "enrichment_error_kind": self.enrichment_error_kind,
            "enrichment_model": self.enrichment_model,
            "enrichment_time_seconds": self.enrichment_time_seconds,
            "enriched_at": self.enriched_at.isoformat() if self.enriched_at else None,
        }


# ── LLM-derived structured intelligence (CHANGELOG 0.1.2) ──
# Provenance types (item 6): "explicit" (directly stated in the source),
# "derived" (reasonably inferred), "suggested" (AI-generated candidate
# requiring validation). Items are the durable, traceable record of what
# the LLM learned from a document; high-value items are additionally
# APPLIED to the existing domain objects (Technology Inventory, Sales
# Notes, Use Cases) through the normal service layer (item 5) — this row
# is never deleted when applied, it is the evidence.
ITEM_KINDS = [
    "customer_fact",
    "business_objective",
    "business_challenge",
    "project",
    "stakeholder",
    "requirement",
    "decision",
    "follow_up_item",
    "risk",
    "technology",           # also applied to Technology Inventory
    "technology_dependency",  # also applied to Technology Dependency
    "use_case",             # also applied to Use Cases
    "opportunity",          # also applied as a Sales Note (opportunity)
]
PROVENANCE_TYPES = ["explicit", "derived", "suggested"]


class CustomerKnowledgeItem(Base):
    """One LLM-extracted intelligence item from a knowledge document.

    ``source_knowledge_id`` → CustomerKnowledge (the uploaded document);
    ``customer_id`` is denormalized so items are always queryable in the
    customer's own scope. Deletion of the source document cascades its
    items (the document is the evidence owner).

    NOTE: deleting this row does NOT delete the applied domain objects
    (tech inventory / notes / use cases) — application is one-directional
    (item 7: prefer strengthening existing knowledge; the provenance link
    is preserved via source references on the applied rows).
    """

    __tablename__ = "customer_knowledge_items"

    id = sa.Column(sa.Integer, primary_key=True, nullable=False)
    customer_id = sa.Column(
        sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_knowledge_id = sa.Column(
        sa.Integer,
        sa.ForeignKey("customer_knowledge.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    kind = sa.Column(sa.String(50), nullable=False)  # one of ITEM_KINDS
    name = sa.Column(sa.String(500), nullable=False)
    description = sa.Column(sa.Text, nullable=True)
    provenance = sa.Column(sa.String(20), nullable=False, default="derived")
    confidence = sa.Column(sa.Float, nullable=True)  # 0.0-1.0
    evidence = sa.Column(sa.Text, nullable=True)  # supporting text from the doc
    source_reference = sa.Column(sa.String(500), nullable=True)  # section/page ref
    # Application result (item 5): NULL = not applied, "created" = new domain
    # record created, "linked" = existing record found and strengthened.
    applied_status = sa.Column(sa.String(20), nullable=True)
    applied_object_type = sa.Column(sa.String(50), nullable=True)  # e.g. "technology"
    applied_object_id = sa.Column(sa.Integer, nullable=True)
    enrichment_model = sa.Column(sa.String(100), nullable=True)
    extracted_at = sa.Column(sa.DateTime, nullable=False, default=lambda: datetime.now(UTC))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "source_knowledge_id": self.source_knowledge_id,
            "kind": self.kind,
            "name": self.name,
            "description": self.description,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "source_reference": self.source_reference,
            "applied_status": self.applied_status,
            "applied_object_type": self.applied_object_type,
            "applied_object_id": self.applied_object_id,
            "enrichment_model": self.enrichment_model,
            "extracted_at": self.extracted_at.isoformat() if self.extracted_at else None,
        }
