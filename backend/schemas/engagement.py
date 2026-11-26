"""H5 request contracts; audit fields are never accepted as mutable state."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class ActivityFields(BaseModel):
    type: str | None = Field(None, max_length=30)
    occurred_at: datetime | None = None
    occurred_date: date | None = None
    actor: str | None = Field(None, max_length=100)
    source: str | None = Field(None, max_length=255)
    outcome: str | None = None
    contact_ids: list[int] = Field(default_factory=list)


class ActivityCreate(ActivityFields):
    type: str = Field(..., max_length=30)
    actor: str = Field(..., max_length=100)


class ActivityUpdate(ActivityFields):
    pass


class TaskFields(BaseModel):
    title: str | None = Field(None, max_length=255)
    detail: str | None = None
    assignee: str | None = Field(None, max_length=100)
    due_at: datetime | None = None
    due_date: date | None = None
    status: str | None = None
    evidence_note_ids: list[int] = Field(default_factory=list)
    evidence_activity_ids: list[int] = Field(default_factory=list)


class TaskCreate(TaskFields):
    title: str = Field(..., max_length=255)
    status: str = "open"


class TaskUpdate(TaskFields):
    expected_version: int = Field(..., strict=True)


class TaskDelete(BaseModel):
    expected_version: int = Field(..., strict=True)


class TaskPromotion(BaseModel):
    source_type: str
    source_id: int
    title: str | None = Field(None, max_length=255)
    detail: str | None = None
