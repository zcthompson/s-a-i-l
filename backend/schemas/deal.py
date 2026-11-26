"""Deal and pipeline-stage request contracts (audit fields are never client-set)."""

from datetime import date

from pydantic import BaseModel, Field


class DealContactLink(BaseModel):
    contact_id: int
    role: str | None = Field(None, max_length=30)


class VendorEvidence(BaseModel):
    import_id: int = Field(..., gt=0)
    opportunity_number: str = Field(..., min_length=1, max_length=255)


class DealPromotion(BaseModel):
    attention_id: str | None = Field(None, max_length=255)
    vendor: VendorEvidence | None = None


class DealFields(BaseModel):
    name: str | None = Field(None, max_length=255)
    owner_user_id: int | None = None
    stage_id: int | None = None
    close_date: date | None = None
    amount_minor: int | None = Field(None, ge=0)
    currency: str | None = Field(None, min_length=3, max_length=3)
    amount_basis: str | None = None
    probability: int | None = Field(None, ge=0, le=100)
    deal_type: str | None = None
    next_step: str | None = None
    next_step_date: date | None = None
    closed_reason: str | None = None
    vendor_evidence: list[VendorEvidence] | None = None
    contacts: list[DealContactLink] | None = None
    task_ids: list[int] | None = None
    activity_ids: list[int] | None = None
    note_ids: list[int] | None = None
    technology_ids: list[int] | None = None


class DealCreate(DealFields):
    name: str = Field(..., max_length=255)


class DealUpdate(DealFields):
    expected_version: int = Field(..., strict=True)


class DealDelete(BaseModel):
    expected_version: int = Field(..., strict=True)


class StageCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(..., min_length=1, max_length=100)
    stage_class: str
    position: int
    default_probability: int | None = Field(None, ge=0, le=100)


class StageUpdate(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=100)
    position: int | None = None
    active: bool | None = None
    default_probability: int | None = Field(None, ge=0, le=100)
    # Required when retiring a stage that still holds open deals.
    remap_to_stage_id: int | None = None
