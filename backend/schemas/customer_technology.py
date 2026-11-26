"""Pydantic schemas for Technology Inventory (S-A-I-L).

Controlled-vocabulary fields (category, deployment_model, lifecycle_state,
support_state, business_criticality, verification_state) are length-checked
here and validated against the vocabulary lists in
backend/models/customer_technology.py by the service layer — the model
module is the single source of truth for the vocabularies so future
releases can extend them without a migration.
"""

from datetime import date, datetime

from pydantic import BaseModel, Field


class ORMBaseModel(BaseModel):
    """Base model with from_attributes enabled for SQLAlchemy ORM serialization."""

    model_config = {"from_attributes": True}


class CustomerTechnologyCreate(ORMBaseModel):
    """Schema for creating a Technology Inventory item.

    Only ``name`` and ``category`` are required — every other attribute may
    be unknown (None -> NULL), per the "unknowns stay unknown" rule.
    """

    name: str = Field(..., min_length=1, max_length=255)
    vendor: str | None = Field(None, max_length=255)
    category: str = Field(..., min_length=1, max_length=50)
    version_edition: str | None = Field(None, max_length=255)
    deployment_model: str | None = Field(None, max_length=50)
    quantity: int | None = Field(None, ge=1)
    footprint: str | None = Field(None, max_length=255)
    purpose: str | None = None
    lifecycle_state: str | None = Field(None, max_length=50)
    support_state: str | None = Field(None, max_length=50)
    business_criticality: str | None = Field(None, max_length=50)
    source: str | None = Field(None, max_length=255)
    date_observed: date | None = None
    end_of_support_date: date | None = None
    eol_source: str | None = Field(None, max_length=255)
    verification_state: str = Field("unverified", min_length=1, max_length=20)
    confidence: float | None = Field(None, ge=0.0, le=1.0)
    notes: str | None = None


class CustomerTechnologyUpdate(ORMBaseModel):
    """Schema for updating a Technology Inventory item (all optional)."""

    name: str | None = Field(None, min_length=1, max_length=255)
    vendor: str | None = Field(None, max_length=255)
    category: str | None = Field(None, min_length=1, max_length=50)
    version_edition: str | None = Field(None, max_length=255)
    deployment_model: str | None = Field(None, max_length=50)
    quantity: int | None = Field(None, ge=1)
    footprint: str | None = Field(None, max_length=255)
    purpose: str | None = None
    lifecycle_state: str | None = Field(None, max_length=50)
    support_state: str | None = Field(None, max_length=50)
    business_criticality: str | None = Field(None, max_length=50)
    source: str | None = Field(None, max_length=255)
    date_observed: date | None = None
    end_of_support_date: date | None = None
    eol_source: str | None = Field(None, max_length=255)
    verification_state: str | None = Field(None, min_length=1, max_length=20)
    confidence: float | None = Field(None, ge=0.0, le=1.0)
    notes: str | None = None


class CustomerTechnology(ORMBaseModel):
    """Response schema for a Technology Inventory item."""

    id: int
    customer_id: int
    name: str
    vendor: str | None = None
    category: str
    version_edition: str | None = None
    deployment_model: str | None = None
    quantity: int | None = None
    footprint: str | None = None
    purpose: str | None = None
    lifecycle_state: str | None = None
    support_state: str | None = None
    business_criticality: str | None = None
    source: str | None = None
    date_observed: date | None = None
    end_of_support_date: date | None = None
    eol_source: str | None = Field(None, max_length=255)
    verification_state: str
    confidence: float | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
