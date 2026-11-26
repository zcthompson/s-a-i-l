"""Pydantic schemas for external integration configuration."""

from typing import Any

from pydantic import BaseModel, Field

# ── Integration config schemas ──────────────────────────────────────────────

class SlackConfig(BaseModel):
    """Slack integration configuration."""
    enabled: bool = False
    webhook_url: str | None = None


class TeamsConfig(BaseModel):
    """Microsoft Teams integration configuration."""
    enabled: bool = False
    webhook_url: str | None = None


class JiraConfig(BaseModel):
    """Jira integration configuration."""
    enabled: bool = False
    jira_url: str | None = None
    api_key: str | None = None
    project_key: str | None = None


class IntegrationStatus(BaseModel):
    """Overall integration status response."""
    slack: dict[str, Any] = Field(default_factory=lambda: {"configured": False})
    teams: dict[str, Any] = Field(default_factory=lambda: {"configured": False})
    jira: dict[str, Any] = Field(default_factory=lambda: {"configured": False})


# ── Request schemas ──────────────────────────────────────────────────────────

class SlackSendMessage(BaseModel):
    """Schema for sending a message to Slack."""
    message: str = Field(..., min_length=1, max_length=5000, description="Message body")
    title: str | None = Field("S-A-I-L", max_length=200, description="Message title")


class TeamsSendMessage(BaseModel):
    """Schema for sending a message to Teams."""
    message: str = Field(..., min_length=1, max_length=5000, description="Message body")
    title: str | None = Field("S-A-I-L", max_length=200, description="Message title")


class JiraCreateTicket(BaseModel):
    """Schema for creating a Jira ticket."""
    summary: str = Field(..., min_length=1, max_length=500, description="Ticket summary")
    description: str = Field(..., min_length=1, max_length=32000, description="Ticket description")
    issue_type: str | None = Field("Task", max_length=100, description="Issue type")
    project_key: str | None = Field(None, max_length=50, description="Jira project key")
