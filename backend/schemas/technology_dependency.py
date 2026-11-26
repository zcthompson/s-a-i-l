"""Pydantic schemas for Technology Dependencies (S-A-I-L).

``relationship_type`` and ``verification_state`` are length-checked here
and validated against the vocabulary lists in
backend/models/technology_dependency.py by the service layer — the model
module is the single source of truth for the vocabularies (same convention
as the Technology Inventory schemas).
"""

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator


class ORMBaseModel(BaseModel):
    """Base model with from_attributes enabled for SQLAlchemy ORM serialization."""

    model_config = {"from_attributes": True}


class TechnologyDependencyCreate(ORMBaseModel):
    """Schema for creating a technology dependency.

    ``source_id`` / ``target_id`` / ``relationship_type`` are required —
    everything else may be unknown (None -> NULL). The service layer
    enforces that both referenced technologies exist, belong to the same
    customer, are not identical, and that the mirrored direction of the
    same logical relationship is not re-created (canonical orientation).
    """

    source_id: int
    target_id: int
    relationship_type: str = Field(..., min_length=1, max_length=50)
    verification_state: str = Field("verified", min_length=1, max_length=20)
    confidence: float | None = Field(None, ge=0.0, le=1.0)
    source_provenance: str | None = Field(None, max_length=255)
    date_observed: date | None = None
    notes: str | None = None


class TechnologyDependencyUpdate(ORMBaseModel):
    """Schema for updating a technology dependency (all optional)."""

    source_id: int | None = None
    target_id: int | None = None
    relationship_type: str | None = Field(None, min_length=1, max_length=50)
    verification_state: str | None = Field(None, min_length=1, max_length=20)
    confidence: float | None = Field(None, ge=0.0, le=1.0)
    source_provenance: str | None = Field(None, max_length=255)
    date_observed: date | None = None
    notes: str | None = None


class TechnologyDependency(ORMBaseModel):
    """Response schema for a technology dependency (denormalized ends).

    ``source_name`` / ``target_name`` (and their vendors) are populated by
    the ``from_orm`` validator below — the relationship endpoints inline so
    the graph projection and UI never need a second round-trip. When a
    caller builds the model from a plain ``to_dict()`` payload (which
    already carries the denormalized fields), the validator is a no-op.
    """

    id: int
    customer_id: int
    source_id: int
    source_name: str | None = None
    source_vendor: str | None = None
    target_id: int
    target_name: str | None = None
    target_vendor: str | None = None
    relationship_type: str
    verification_state: str
    confidence: float | None = None
    source_provenance: str | None = None
    date_observed: date | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _denormalize_orm_endpoints(cls, data):
        """Populate source/target names from the ORM relationship objects
        (FastAPI from_attributes passes the ORM instance, whose ``source``
        / ``target`` are the eager-loaded CustomerTechnology ends)."""
        if isinstance(data, dict):
            return data
        source = getattr(data, "source", None)
        target = getattr(data, "target", None)
        data.source_name = source.name if source is not None else None
        data.source_vendor = source.vendor if source is not None else None
        data.target_name = target.name if target is not None else None
        data.target_vendor = target.vendor if target is not None else None
        return data
