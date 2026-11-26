"""Pydantic schemas for customer knowledge operations.

Contract additions:
- ``processing_status`` lifecycle (UPLOADED/PROCESSING/READY/FAILED)
  replaces the simple ``processed`` Yes/No as the UI's source of truth;
  ``processed`` stays for backward compatibility (mirrors READY).
- ``normalized_content`` is the canonical Markdown (served by the
  dedicated content endpoint — NOT by the list/detail schemas, which
  carry ``normalized_content_present`` instead).
- ``original_filename`` mirrors ``file_name`` for the new contract.
"""

from datetime import datetime

from pydantic import BaseModel, model_validator


class ORMBaseModel(BaseModel):
    """Base model with from_attributes enabled for SQLAlchemy ORM serialization."""
    model_config = {"from_attributes": True}


class CustomerKnowledgeBase(ORMBaseModel):
    """Base customer knowledge schema with common fields."""
    id: int
    customer_id: int
    knowledge_type: str
    file_name: str
    original_filename: str | None = None
    uploaded_at: datetime
    processed: bool
    extracted_text: str | None = None
    ingestion_status: str | None = None
    classification: str | None = None
    category: str | None = None
    # Knowledge category
    knowledge_category: str | None = None
    # Docling normalization layer
    original_content_type: str | None = None
    original_storage_path: str | None = None
    normalized_format: str | None = None
    normalized_content_present: bool | None = None
    processing_status: str = "UPLOADED"
    processing_error: str | None = None
    processing_error_kind: str | None = None
    processor: str | None = None
    processor_version: str | None = None
    processing_time_seconds: float | None = None
    processed_at: datetime | None = None
    # LLM enrichment layer (item 16: tracked separately from processing)
    enrichment_status: str = "NOT_RUN"
    enrichment_error: str | None = None
    enrichment_error_kind: str | None = None
    enrichment_model: str | None = None
    enrichment_time_seconds: float | None = None
    enriched_at: datetime | None = None


class CustomerKnowledgeCreate(ORMBaseModel):
    """Schema for creating a new customer knowledge entry."""
    customer_id: int
    knowledge_type: str
    file_name: str
    file_data: bytes
    extracted_text: str | None = None


class CustomerKnowledge(CustomerKnowledgeBase):
    """Response schema for a customer knowledge entry.

    Built from the model's ``to_dict()`` (see the route layer) so binary
    blobs and large normalized content never ride the list/detail wire.
    ``from_attributes`` remains enabled for ORM-object responses; the
    validator routes ORM instances through ``to_dict()`` first.
    """
    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _via_to_dict(cls, data):
        if not isinstance(data, dict) and hasattr(data, "to_dict"):
            return data.to_dict()
        return data


class CustomerKnowledgeUpdate(ORMBaseModel):
    """Schema for updating a knowledge entry's structured fields."""
    classified_type: str | None = None
    category: str | None = None
    # Knowledge category: the user may
    # change it after upload — a changed value is authoritative.
    knowledge_category: str | None = None
    extracted_text: str | None = None
    processed: bool | None = None


class KnowledgeUploadResponse(ORMBaseModel):
    """Schema for the knowledge upload response.

    The upload returns once the original is stored and processing has been
    initiated (plan item 9) — ``processing_status`` is the caller's
    progress signal (the UI polls the list/detail endpoints).
    """
    success: bool
    knowledge_id: int
    classified_type: str
    entries_count: int
    warnings: list[str] = []
    processing_status: str = "PROCESSING"


class KnowledgeUploadPayload(ORMBaseModel):
    """Schema for the upload payload."""
    file: str  # filename
    file_type: str  # csv or pdf


class KnowledgeContentResponse(ORMBaseModel):
    """Normalized content payload (GET .../content/)."""
    id: int
    customer_id: int
    file_name: str
    normalized_format: str
    normalized_content: str
    processor: str | None = None
    processing_status: str
    processed_at: datetime | None = None


class KnowledgeItemResponse(ORMBaseModel):
    """One LLM-extracted intelligence item: provenance + evidence + application pointer."""
    id: int
    customer_id: int
    source_knowledge_id: int
    legacy_rvtools_source: bool = False
    kind: str
    name: str
    description: str | None = None
    provenance: str
    confidence: float | None = None
    evidence: str | None = None
    source_reference: str | None = None
    applied_status: str | None = None
    applied_object_type: str | None = None
    applied_object_id: int | None = None
    enrichment_model: str | None = None
    extracted_at: datetime | None = None
