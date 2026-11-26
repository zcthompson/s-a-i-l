"""Third-Party Professional Services schemas (S-A-I-L Sales section).

Controlled vocabularies live in
``backend/models/third_party_service.py`` (single source, same mechanism as
``sales_note.py``); the service layer enforces them so API 422s are
consistent with the existing sales endpoints.
"""


from pydantic import Field

from backend.schemas.use_case import ORMBaseModel


class ThirdPartyServiceCreate(ORMBaseModel):
    """Create payload. vendor_name / service_category / description required;
    everything else optional (status defaults "active", verification
    defaults "verified"). Unknowns stay NULL — never fabricated."""

    vendor_name: str = Field(..., min_length=1, max_length=255)
    service_category: str = Field(..., max_length=50)
    engagement_status: str | None = Field(None, max_length=20)
    description: str = Field(..., min_length=1)
    sow_reference: str | None = Field(None, max_length=255)
    contract_reference: str | None = Field(None, max_length=255)
    started_on: str | None = None  # ISO date (YYYY-MM-DD)
    ended_on: str | None = None
    billing_model: str | None = Field(None, max_length=20)
    fee_amount: float | None = None
    verification_state: str | None = Field(None, max_length=20)
    notes: str | None = None
    # Optional initial use-case links (same-customer only, service-validated).
    use_case_ids: list[int] | None = None


class ThirdPartyServiceUpdate(ORMBaseModel):
    """Update payload — all fields optional (exclude_unset semantics;
    explicit nulls clear a value). ``use_case_ids`` present = full
    replacement of the link set (simplest deterministic contract)."""

    vendor_name: str | None = Field(None, min_length=1, max_length=255)
    service_category: str | None = Field(None, max_length=50)
    engagement_status: str | None = Field(None, max_length=20)
    description: str | None = Field(None, min_length=1)
    sow_reference: str | None = Field(None, max_length=255)
    contract_reference: str | None = Field(None, max_length=255)
    started_on: str | None = None
    ended_on: str | None = None
    billing_model: str | None = Field(None, max_length=20)
    fee_amount: float | None = None
    verification_state: str | None = Field(None, max_length=20)
    notes: str | None = None
    use_case_ids: list[int] | None = None


class ThirdPartyServiceResponse(ORMBaseModel):
    """Wire shape — id + all fields + linked use_case_ids, ISO dates.
    Built from ``ThirdPartyService.to_dict()`` (never the ORM object)."""

    id: int
    customer_id: int
    vendor_name: str
    service_category: str
    engagement_status: str
    description: str
    sow_reference: str | None = None
    contract_reference: str | None = None
    started_on: str | None = None
    ended_on: str | None = None
    billing_model: str | None = None
    fee_amount: float | None = None
    verification_state: str
    notes: str | None = None
    created_by: str | None = None
    related_use_case_ids: list[int] = []
    created_at: str
    updated_at: str


class ThirdPartyServiceDocumentResponse(ORMBaseModel):
    """Wire shape for the documents list — NEVER includes file_data (the
    knowledge model's to_dict omits the blob the same way)."""

    id: int
    service_id: int
    customer_id: int
    document_type: str
    file_name: str
    title: str | None = None
    uploaded_by: str | None = None
    created_at: str
