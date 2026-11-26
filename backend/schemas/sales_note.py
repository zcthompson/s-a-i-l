"""Pydantic schemas for Sales Notes (S-A-I-L).

Only category/title/content are required; author, source, note_date, and
verification_state are optional (unknowns stay NULL). Controlled-vocabulary
fields are length-checked here; the service validates membership (single
source of truth in backend/models/sales_note.py). Related technologies /
use cases are passed as id lists and validated (customer ownership) in the
service layer — cross-customer junctions are rejected.
"""

from datetime import date, datetime

from pydantic import BaseModel, Field


class ORMBaseModel(BaseModel):
    """Base model with from_attributes enabled for SQLAlchemy ORM serialization."""

    model_config = {"from_attributes": True}


class SalesNoteBase(ORMBaseModel):
    """Common Sales Note fields."""

    author: str | None = Field(None, max_length=255)
    source: str | None = Field(None, max_length=255)
    note_date: date | None = None
    category: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    verification_state: str = Field("verified", min_length=1, max_length=20)


class SalesNoteCreate(SalesNoteBase):
    """Schema for creating a Sales Note.

    related_*_ids are optional; omitted (absent or empty) = no related items.
    Ids are validated for customer ownership in the service layer
    (cross-customer junctions are rejected).
    """

    related_technology_ids: list[int] = Field(default_factory=list)
    related_use_case_ids: list[int] = Field(default_factory=list)


class SalesNoteUpdate(ORMBaseModel):
    """Schema for updating a Sales Note (all optional).

    When a related_*_ids list is provided it REPLACES the current set;
    omit it (absent) to leave the current set untouched.
    """

    author: str | None = Field(None, max_length=255)
    source: str | None = Field(None, max_length=255)
    note_date: date | None = None
    category: str | None = Field(None, min_length=1, max_length=50)
    title: str | None = Field(None, min_length=1, max_length=255)
    content: str | None = Field(None, min_length=1)
    verification_state: str | None = Field(None, min_length=1, max_length=20)
    related_technology_ids: list[int] | None = None
    related_use_case_ids: list[int] | None = None


class SalesNote(ORMBaseModel):
    """Response schema for a Sales Note."""

    id: int
    customer_id: int
    author: str | None = None
    source: str | None = None
    note_date: date | None = None
    category: str
    title: str
    content: str
    verification_state: str
    related_technology_ids: list[int] = Field(default_factory=list)
    related_use_case_ids: list[int] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
