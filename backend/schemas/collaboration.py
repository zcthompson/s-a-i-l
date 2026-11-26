"""Pydantic schemas for collaboration features (comments, notifications)."""


from pydantic import BaseModel, Field
from pydantic.config import ConfigDict

# ── Comment schemas ──────────────────────────────────────────────────────────

class CommentCreate(BaseModel):
    """Schema for creating a new comment.

    ``user_name`` is deprecated: the author is always derived from the
    authenticated JWT. The field is accepted-but-ignored for backward
    compatibility with older clients.
    """
    content: str = Field(..., min_length=1, max_length=10000, description="Comment text content")
    user_name: str | None = Field(None, max_length=100, description="Deprecated — ignored; author comes from the JWT")


class CommentUpdate(BaseModel):
    """Schema for updating an existing comment.

    ``user_name`` is deprecated: authorship is the comment's stored author;
    the caller must be that author (or an admin).
    """
    content: str = Field(..., min_length=1, max_length=10000, description="Updated comment text")
    user_name: str | None = Field(None, max_length=100, description="Deprecated — ignored")


class CommentResponse(BaseModel):
    """Schema for comment API responses."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    use_case_id: int
    user_name: str
    content: str
    created_at: str
    updated_at: str


# ── Notification schemas ─────────────────────────────────────────────────────

class NotificationResponse(BaseModel):
    """Schema for notification API responses."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_name: str
    type: str
    message: str
    customer_id: int | None = None
    read: bool
    created_at: str


class NotificationReadRequest(BaseModel):
    """Schema for marking a notification as read."""
    notification_id: int
