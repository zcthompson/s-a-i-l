"""Admin configuration management routes.

Provides CRUD operations for system configuration:
- Inference settings (AI endpoint, model, temperature)
- Assessment evaluation settings (scoring thresholds)
- Project configuration (app name, version, debug)
- Integration settings (Slack, Teams, Jira)
- Generic key-value store with type support

All endpoints require admin privileges.
"""

import logging
import re
import time
from email.message import EmailMessage

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.models.use_case import User
from backend.schemas.admin_config import (
    AssessmentConfig,
    ConfigCategoryResponse,
    ConfigCreate,
    ConfigEntry,
    ConfigUpdate,
    DoclingConfig,
    DocumentProcessingConfig,
    EmailConfig,
    EmailTestResponse,
    InferenceConfig,
    IntegrationConfig,
    ProjectConfig,
    SystemConfigSummary,
)
from backend.schemas.auth import LdapSettingsResponse, LdapTestResponse
from backend.services import email_service
from backend.services.config_service import (
    DOCUMENTS_KEYS,
    EMAIL_KEYS,
    create_entry,
    effective_docling_settings,
    effective_document_settings,
    effective_email_settings,
    effective_inference_settings,
    get_category_entries,
    get_config_values,
    get_entry,
    get_integration_summary,
    soft_delete_entry,
    summarize_configs,
    update_entry,
    upsert_config_entry,
)
from backend.services.document_provider import PROVIDER_AZURE, PROVIDER_DOCLING
from backend.services.ldap_provider import LdapConfigError, LdapUnavailable
from backend.services.ldap_settings import (
    effective_ldap_settings,
    validate_effective_ldap_settings,
)
from backend.services.ssl_trust import SSL_VERIFY_MODES, validate_pem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/config", tags=["admin-config"])


def _require_admin(request: Request) -> dict:
    """Return authenticated admin user or raise 401/403."""
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


def _validate_ssl_trust(ssl_verify: str, ssl_ca_bundle: str | None) -> None:
    """Fail fast (422) on an invalid trust-mode or a malformed CA bundle.

    ``ssl_verify`` is enforced by the Pydantic Literal at parse time; this
    guard re-checks the CA bundle PEM (a trust anchor that breaks
    mid-request would be far worse than a save-time 422). ``ca`` mode
    requires a bundle; other modes accept an empty one.
    """
    mode = (ssl_verify or "full").lower()
    if mode not in SSL_VERIFY_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"ssl_verify must be one of {list(SSL_VERIFY_MODES)}",
        )
    if mode == "ca" and not (ssl_ca_bundle or "").strip():
        raise HTTPException(
            status_code=422,
            detail="ssl_verify='ca' requires a CA bundle (PEM certificate(s))",
        )
    try:
        validate_pem(ssl_ca_bundle or "")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── Generic Config CRUD ──────────────────────────────────────────────────────

@router.get("/summary", response_model=SystemConfigSummary)
def get_config_summary(request: Request, db: Session = Depends(get_db)):
    """Get summary of all configuration categories. Admin only."""
    _require_admin(request)
    summary = summarize_configs(db)
    entries = [
        ConfigCategoryResponse(category=cat, entries=entries)
        for cat, entries in summary["categories"].items()
    ]
    return SystemConfigSummary(categories=entries, total_entries=summary["total_entries"])


@router.get("/category/{category}", response_model=ConfigCategoryResponse)
def get_category_config(category: str, request: Request, db: Session = Depends(get_db)):
    """Get all configuration entries for a category. Admin only."""
    _require_admin(request)
    return ConfigCategoryResponse(
        category=category, entries=get_category_entries(db, category)
    )


@router.get("/category/{category}/{key}", response_model=ConfigEntry)
def get_config_entry(
    category: str,
    key: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get a specific configuration entry by category and key. Admin only."""
    _require_admin(request)
    config = get_entry(db, category, key)
    if not config:
        raise HTTPException(status_code=404, detail="Config entry not found")
    return config.to_dict()


@router.post("/category/{category}", response_model=ConfigEntry, status_code=201)
def create_config_entry(
    category: str,
    data: ConfigCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a new configuration entry. Admin only."""
    _require_admin(request)
    try:
        config = create_entry(db, category, data.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return config.to_dict()


@router.put("/category/{category}/{key}", response_model=ConfigEntry)
def update_config_entry(
    category: str,
    key: str,
    data: ConfigUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update an existing configuration entry. Admin only."""
    _require_admin(request)
    config = update_entry(db, category, key, data.model_dump())
    if not config:
        raise HTTPException(status_code=404, detail="Config entry not found")
    return config.to_dict()


@router.delete("/category/{category}/{key}", status_code=204)
def delete_config_entry(
    category: str,
    key: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Soft-delete a configuration entry by setting is_active=0. Admin only."""
    _require_admin(request)
    if not soft_delete_entry(db, category, key):
        raise HTTPException(status_code=404, detail="Config entry not found")


# ── Convenience Endpoints ────────────────────────────────────────────────────

@router.get("/inference", response_model=InferenceConfig)
def get_inference_config(request: Request, db: Session = Depends(get_db)):
    """Get the effective inference/scoring configuration. Admin only.

    Returns the runtime-effective values: DB overrides (system_config,
    category 'inference') layered over the .env-based Settings, including the
    connection trust model fields (``ssl_verify`` / ``ssl_ca_bundle``).
    """
    _require_admin(request)
    eff = effective_inference_settings(db)
    return InferenceConfig(
        ai_endpoint=eff["ai_endpoint"] or "",
        ai_model=eff["ai_model"] or "",
        api_key=eff["api_key"] or None,
        temperature=eff["temperature"],
        max_tokens=eff["max_tokens"],
        timeout=eff["timeout"],
        enabled=bool(eff["enabled"]),
        ssl_verify=eff.get("ssl_verify") or "full",
        ssl_ca_bundle=eff.get("ssl_ca_bundle") or None,
    )


@router.put("/inference", response_model=InferenceConfig)
def update_inference_config(
    data: InferenceConfig,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update inference/scoring configuration. Admin only.

    ``None`` values are skipped (leave the current setting unchanged).
    Empty strings are also skipped for string fields — the override layer
    treats empty values as "unset" (fall back to the .env default), so
    persisting them would be a silent no-op at runtime and confusing in
    the stored entries.
    """
    _require_admin(request)
    _validate_ssl_trust(data.ssl_verify, data.ssl_ca_bundle)
    for key, value in data.model_dump().items():
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        upsert_config_entry(db, "inference", key, value)
    return get_inference_config(request, db)


# ── Docling Serve configuration (P0b — previously env-only, no UI) ──────────


@router.get("/docling", response_model=DoclingConfig)
def get_docling_config(request: Request, db: Session = Depends(get_db)):
    """Get the effective Docling Serve configuration. Admin only.

    Runtime-effective: DB overrides (category 'docling') over the .env
    Settings. ``api_key`` is env/Secret-only and intentionally NOT part of
    this surface (it is never persisted or returned).
    """
    _require_admin(request)
    eff = effective_docling_settings(db)
    return DoclingConfig(
        server_url=eff["server_url"] or "",
        timeout_seconds=eff["timeout_seconds"],
        ssl_verify=eff.get("ssl_verify") or "full",
        ssl_ca_bundle=eff.get("ssl_ca_bundle") or None,
    )


@router.put("/docling", response_model=DoclingConfig)
def update_docling_config(
    data: DoclingConfig,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update Docling Serve configuration. Admin only.

    Same empty-string-skip semantics as /inference. A malformed CA bundle or
    invalid ``ssl_verify`` mode 422s immediately (``ssl_trust.validate_pem``)
    instead of breaking conversions mid-request.
    """
    _require_admin(request)
    _validate_ssl_trust(data.ssl_verify, data.ssl_ca_bundle)
    for key, value in data.model_dump().items():
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        upsert_config_entry(db, "docling", key, value)
    return get_docling_config(request, db)


# ── Document processing provider ──────────────────────────────


@router.get("/documents", response_model=DocumentProcessingConfig)
def get_document_processing_config(request: Request, db: Session = Depends(get_db)):
    """Get the effective Customer Knowledge document provider config. Admin only.

    Runtime-effective: DB overrides (category 'documents') over the .env
    Settings, read by the normalization worker per job. The Azure API key is
    env/Secret-only — only ``api_key_configured`` is reported.
    """
    _require_admin(request)
    eff = effective_document_settings(db)
    return DocumentProcessingConfig(
        provider=eff["provider"] or PROVIDER_DOCLING,
        azure_endpoint=eff["azure_endpoint"] or "",
        azure_timeout_seconds=eff["azure_timeout_seconds"],
        azure_ssl_verify=eff.get("azure_ssl_verify") or "full",
        azure_ssl_ca_bundle=eff.get("azure_ssl_ca_bundle") or None,
        api_key_configured=bool(eff["api_key_configured"]),
    )


@router.put("/documents", response_model=DocumentProcessingConfig)
def update_document_processing_config(
    data: DocumentProcessingConfig,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update the document provider config. Admin only.

    Same empty-string-skip semantics as /docling. ``api_key_configured`` in
    the body is ignored (derived from the env). Switching the provider never
    reprocesses existing documents.
    """
    _require_admin(request)
    if data.provider not in (PROVIDER_DOCLING, PROVIDER_AZURE):
        raise HTTPException(
            status_code=422,
            detail=f"provider must be one of: {PROVIDER_DOCLING}, {PROVIDER_AZURE}",
        )
    if data.azure_endpoint and not data.azure_endpoint.startswith("https://"):
        raise HTTPException(status_code=422, detail="azure_endpoint must be an HTTPS endpoint (https://)")
    if data.azure_timeout_seconds is not None and not 1 <= data.azure_timeout_seconds <= 3600:
        raise HTTPException(status_code=422, detail="azure_timeout_seconds must be between 1 and 3600")
    _validate_ssl_trust(data.azure_ssl_verify, data.azure_ssl_ca_bundle)
    values = data.model_dump()
    for key in DOCUMENTS_KEYS:
        value = values[key]
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        upsert_config_entry(db, "documents", key, value)
    return get_document_processing_config(request, db)


# ── Email notifications (SMTP) ──


@router.get("/email", response_model=EmailConfig)
def get_email_config(request: Request, db: Session = Depends(get_db)):
    """Return effective, non-secret email settings. Admin only."""
    _require_admin(request)
    eff = effective_email_settings(db)
    return EmailConfig(
        enabled=eff["enabled"], smtp_host=eff["smtp_host"] or "",
        smtp_port=int(eff["smtp_port"]), smtp_username=eff["smtp_username"] or "",
        smtp_security=eff.get("smtp_security") or "starttls",
        from_address=eff["from_address"] or "",
        password_configured=bool(eff["password_configured"]),
    )


@router.put("/email", response_model=EmailConfig)
def update_email_config(data: EmailConfig, request: Request, db: Session = Depends(get_db)):
    """Validate before persisting non-empty, non-secret settings. Admin only."""
    _require_admin(request)
    if not 1 <= data.smtp_port <= 65535:
        raise HTTPException(422, "smtp_port must be between 1 and 65535")
    if data.smtp_security not in ("starttls", "ssl", "none"):
        raise HTTPException(422, "smtp_security must be one of: starttls, ssl, none")
    if data.from_address and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", data.from_address):
        raise HTTPException(422, "from_address must be a valid email address")
    values = data.model_dump()
    for key in EMAIL_KEYS:
        value = values[key]
        if value is None or (isinstance(value, str) and value == ""):
            continue
        upsert_config_entry(db, "email", key, value)
    return get_email_config(request, db)


@router.post("/email/test", response_model=EmailTestResponse)
def test_email_connection(request: Request, db: Session = Depends(get_db)):
    """Send a connection test to the admin's own profile address."""
    admin = _require_admin(request)
    user = db.query(User).filter(User.username == admin["username"]).first()
    if user is None or not user.email:
        raise HTTPException(422, "Your profile has no email address set")
    eff = effective_email_settings(db)
    if not (eff["enabled"] and (eff["smtp_host"] or "").strip() and (eff["from_address"] or "").strip()):
        return EmailTestResponse(ok=False, latency_ms=0, error="Email is not configured")
    start = time.monotonic()
    try:
        msg = EmailMessage()
        msg["Subject"] = "S-A-I-L: Connection test"
        msg["From"] = eff["from_address"].strip()
        msg["To"] = user.email
        msg.set_content("This is a connection test from S-A-I-L (Sales Analytics and Intelligence Launchpad).\n\n"
                        "If you received this email, the SMTP configuration works.")
        email_service.send_message(eff, msg)
    except email_service.smtplib.SMTPAuthenticationError:
        logger.warning("email connection test failed: SMTP authentication error")
        error = "SMTP authentication failed"
    except email_service.smtplib.SMTPException:
        logger.warning("email connection test failed: SMTP error")
        error = "Email send failed"
    except Exception:
        logger.warning("email connection test failed: connection error")
        error = "SMTP connection failed"
    else:
        error = None
    return EmailTestResponse(ok=error is None, latency_ms=int((time.monotonic() - start) * 1000), error=error)


# ── LDAP/AD directory authentication ──────────────────────────────


@router.get("/auth_ldap", response_model=LdapSettingsResponse)
def get_ldap_settings(request: Request, db: Session = Depends(get_db)):
    """Get the effective directory-auth settings. Admin only.

    Non-secret values only — the service bind password has no field here and
    is never persisted or returned (§3.6 rule 3).
    """
    _require_admin(request)
    eff = effective_ldap_settings(db)
    return LdapSettingsResponse(
        enabled=eff.enabled,
        server_uri=eff.server_uri,
        service_bind_dn=eff.service_bind_dn,
        user_search_base_dn=eff.user_search_base_dn,
        user_search_filter=eff.user_search_filter,
        start_tls=eff.start_tls,
        require_tls=eff.require_tls,
        ssl_verify=eff.ssl_verify,  # type: ignore[arg-type]
        ssl_ca_bundle=eff.ssl_ca_bundle or None,
        timeout_seconds=eff.timeout_seconds,
        email_attr=eff.email_attr,
        display_name_attr=eff.display_name_attr,
        department_attr=eff.department_attr,
        external_id_attr=eff.external_id_attr,
        auto_approve=eff.auto_approve,
        default_role=eff.default_role,
        login_disabled=eff.login_disabled,
        local_register_enabled=eff.local_register_enabled,
    )


@router.put("/auth_ldap", response_model=LdapSettingsResponse)
def update_ldap_settings(
    data: LdapSettingsResponse,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update directory-auth settings. Admin only.

    Persists the NON-SECRET values to SystemConfig category ``auth_ldap``
    (env is the secret source — the bind password is not a field). The
    EFFECTIVE result (env → existing DB → this payload) is validated BEFORE
    anything is written, so a misconfiguration 422s atomically — a bad
    save can never persist a broken directory config (§3.6 rules 2/4/5).
    """
    _require_admin(request)
    _validate_ssl_trust(data.ssl_verify, data.ssl_ca_bundle)

    # Preview: apply this payload to the current effective settings, then
    # validate. (upsert commits per-entry, so validation must come first.)
    from dataclasses import replace

    preview = effective_ldap_settings(db)
    updates = {
        k: v
        for k, v in data.model_dump().items()
        if v is not None and v != ""
    }
    try:
        preview = replace(preview, **updates)
        validate_effective_ldap_settings(preview)
    except LdapConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    for key in updates:
        upsert_config_entry(db, "auth_ldap", key, updates[key])
    return get_ldap_settings(request, db)


@router.post("/auth_ldap/test", response_model=LdapTestResponse)
def test_ldap_connection(request: Request, db: Session = Depends(get_db)):
    """Probe the directory: service-account bind (+ StartTLS when set).

    Read-only, single guarded call (plan §4 P2 — the UX-audit #14 confirm
    pattern applies to anything that could spam the directory; a bind is not
    a spam vector). Returns ``{ok, latency_ms}`` — never user data, never
    secrets; errors are fixed short messages (§3.6 rule 3).
    """
    _require_admin(request)
    from backend.services import ldap_provider

    eff = effective_ldap_settings(db)
    if not eff.enabled:
        return LdapTestResponse(
            ok=False,
            error="Directory authentication is not enabled (auth_ldap.enabled)",
        )
    start = time.monotonic()
    try:
        ldap_provider._service_bind_ok(eff)
    except (LdapUnavailable, LdapConfigError) as exc:
        return LdapTestResponse(
            ok=False,
            latency_ms=int((time.monotonic() - start) * 1000),
            error=str(exc) or "Directory unreachable",
        )
    return LdapTestResponse(
        ok=True, latency_ms=int((time.monotonic() - start) * 1000)
    )


@router.get("/assessment", response_model=AssessmentConfig)
def get_assessment_config(request: Request, db: Session = Depends(get_db)):
    """Get assessment evaluation configuration. Admin only."""
    _require_admin(request)
    return AssessmentConfig(**get_config_values(
        db, "assessment",
        ("default_dimension_count", "scoring_threshold_low",
         "scoring_threshold_medium", "scoring_threshold_high"),
    ))


@router.put("/assessment", response_model=AssessmentConfig)
def update_assessment_config(
    data: AssessmentConfig,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update assessment evaluation configuration. Admin only."""
    _require_admin(request)
    for key, value in data.model_dump().items():
        upsert_config_entry(db, "assessment", key, value)
    return get_assessment_config(request, db)


@router.get("/project", response_model=ProjectConfig)
def get_project_config(request: Request, db: Session = Depends(get_db)):
    """Get project/application configuration. Admin only."""
    _require_admin(request)
    return ProjectConfig(**get_config_values(
        db, "project",
        ("app_name", "version", "debug", "maintenance_mode"),
    ))


@router.put("/project", response_model=ProjectConfig)
def update_project_config(
    data: ProjectConfig,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update project/application configuration. Admin only."""
    _require_admin(request)
    for key, value in data.model_dump().items():
        upsert_config_entry(db, "project", key, value)
    return get_project_config(request, db)


@router.get("/integration", response_model=IntegrationConfig)
def get_integration_config(request: Request, db: Session = Depends(get_db)):
    """Get integration configuration summary. Admin only."""
    _require_admin(request)
    return IntegrationConfig(**get_integration_summary(db))


@router.put("/integration/{integration}", response_model=IntegrationConfig)
def update_integration_config(
    integration: str,
    data: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update integration configuration. Admin only."""
    _require_admin(request)
    category = f"integration_{integration}"
    for key, value in data.items():
        upsert_config_entry(db, category, key, value)
    return get_integration_config(request, db)
