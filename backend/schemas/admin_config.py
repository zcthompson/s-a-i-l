"""Pydantic schemas for system configuration management."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# Connection trust model: full = verify chain +
# hostname (default, today's behavior); skip = TLS on, verification off
# (high-risk); ca = verify against an uploaded CA bundle only.
SslVerifyMode = Literal["full", "skip", "ca"]


class ConfigEntry(BaseModel):
    """Individual configuration entry."""
    id: int
    category: str
    key: str
    value_type: str
    value: Any
    description: str | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConfigCreate(BaseModel):
    """Schema for creating a configuration entry."""
    category: str = Field(..., min_length=1, max_length=50)
    key: str = Field(..., min_length=1, max_length=100)
    value_type: str = Field(default="string", pattern="^(string|integer|float|boolean|json)$")
    string_value: str | None = None
    integer_value: int | None = None
    float_value: float | None = None
    boolean_value: bool | None = None
    json_value: Any | None = None
    description: str | None = Field(None, max_length=500)


class ConfigUpdate(BaseModel):
    """Schema for updating a configuration entry."""
    value_type: str | None = Field(default=None, pattern="^(string|integer|float|boolean|json)$")
    string_value: str | None = None
    integer_value: int | None = None
    float_value: float | None = None
    boolean_value: bool | None = None
    json_value: Any | None = None
    description: str | None = Field(None, max_length=500)
    is_active: bool | None = None


class ConfigCategoryResponse(BaseModel):
    """Response for a category of configuration entries."""
    category: str
    entries: list[ConfigEntry]


class SystemConfigSummary(BaseModel):
    """Summary of all system configuration categories."""
    categories: list[ConfigCategoryResponse]
    total_entries: int


# ── Convenience schemas for common config groups ─────────────────────────────

class InferenceConfig(BaseModel):
    """Inference/scoring configuration (admin-editable; DB values override .env)."""
    ai_endpoint: str = ""
    ai_model: str = ""
    api_key: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: float | None = None
    enabled: bool = True
    # Connection trust model (P0b) — applied via services.ssl_trust.
    ssl_verify: SslVerifyMode = "full"
    ssl_ca_bundle: str | None = None


class DoclingConfig(BaseModel):
    """Docling Serve configuration (admin-editable; DB values override .env).

    Docling previously had NO admin surface
    (env-only). ``api_key`` is deliberately absent: it is env/Secret-only,
    never persisted or returned (empty = no Authorization header, current
    behavior).
    """
    server_url: str = ""
    timeout_seconds: float | None = None
    ssl_verify: SslVerifyMode = "full"
    ssl_ca_bundle: str | None = None


class DocumentProcessingConfig(BaseModel):
    """Customer Knowledge document provider (DB overrides .env).

    ``provider`` is ``docling`` or ``azure_document_intelligence``. The Azure
    API key is env/Secret-only; ``api_key_configured`` reports whether it is
    set and is ignored on PUT.
    """
    provider: str = "docling"
    azure_endpoint: str = ""
    azure_timeout_seconds: float | None = None
    azure_ssl_verify: SslVerifyMode = "full"
    azure_ssl_ca_bundle: str | None = None
    api_key_configured: bool = False


class AssessmentConfig(BaseModel):
    """Assessment evaluation configuration."""
    default_dimension_count: int = 5
    scoring_threshold_low: float = 30.0
    scoring_threshold_medium: float = 60.0
    scoring_threshold_high: float = 80.0


class ProjectConfig(BaseModel):
    """Project/application configuration."""
    app_name: str = "Sales Analytics and Intelligence Launchpad"
    version: str = "1.0.0"
    debug: bool = False
    maintenance_mode: bool = False


class IntegrationConfig(BaseModel):
    """Integration configuration summary."""
    slack: dict | None = None
    teams: dict | None = None
    jira: dict | None = None


class EmailConfig(BaseModel):
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    from_address: str = ""
    password_configured: bool = False  # derived; ignored on PUT


class EmailTestResponse(BaseModel):
    ok: bool
    latency_ms: int
    error: str | None = None
