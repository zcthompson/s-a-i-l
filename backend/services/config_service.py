"""Effective runtime inference settings.

Admin-persisted values in system_config (category='inference', written via
/api/admin/config/inference) override the .env-based Settings at runtime for
scoring, predictions, and projections. Any field left empty in the DB falls
back to the environment value.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models.collaboration import SystemConfig
from backend.services.document_provider import PROVIDER_DOCLING

INFERENCE_KEYS = ("ai_endpoint", "ai_model", "api_key", "temperature", "max_tokens", "timeout", "enabled", "ssl_verify", "ssl_ca_bundle")

EMAIL_KEYS = ("enabled", "smtp_host", "smtp_port", "smtp_username", "smtp_security", "from_address")

DOCLING_KEYS = ("server_url", "timeout_seconds", "ssl_verify", "ssl_ca_bundle")
# docling_api_key is deliberately NOT a persisted/returned key: the Docling
# deployment takes no key today, and the (future) key stays env/Secret-only —
# the same secret treatment as the inference api_key, except docling has no
# env-default display need. The UI shows a "set in .env" note instead.

DOCUMENTS_KEYS = ("provider", "azure_endpoint", "azure_timeout_seconds", "azure_ssl_verify", "azure_ssl_ca_bundle")
# The Azure Document Intelligence API key is likewise env/Secret-only
# (SAIL_AZURE_DI_API_KEY): never persisted, never returned — only the
# derived ``api_key_configured`` flag is exposed.


def get_inference_overrides(db: Session | None) -> dict[str, Any]:
    """Active DB overrides for the 'inference' category (empty/None skipped)."""
    return _get_overrides(db, "inference", INFERENCE_KEYS)


def get_engagement_overrides(db: Session | None) -> dict[str, Any]:
    """Active DB overrides for the 'engagement' category (QBR cadence)."""
    return _get_overrides(db, "engagement", ("qbr_cadence_days",))


def _get_overrides(db: Session | None, category: str, keys: tuple) -> dict[str, Any]:
    """Active DB overrides for a category (empty/None skipped)."""
    if db is None:
        return {}
    rows = db.query(SystemConfig).filter(
        and_(SystemConfig.category == category, SystemConfig.is_active == 1)
    ).all()
    overrides: dict[str, Any] = {}
    for row in rows:
        if row.key not in keys:
            continue
        value = row.to_dict().get("value")
        if value is None or value == "":
            continue
        overrides[str(row.key)] = value
    return overrides


def effective_inference_settings(db: Session | None) -> dict[str, Any]:
    """Merge .env defaults (Settings) with DB overrides; DB wins when set.

    Includes the connection trust model fields (``ssl_verify`` /
    ``ssl_ca_bundle``) consumed by ``AIClient`` via
    ``services.ssl_trust.resolve_verify`` — ``full`` (default) keeps today's
    httpx verification exactly.
    """
    base = get_settings()
    settings: dict[str, Any] = {
        "ai_endpoint": base.ai_endpoint or "",
        "ai_model": base.ai_model or "gemma4-12b",
        "api_key": base.ai_api_key or "",
        "temperature": 0.3,
        "max_tokens": 2000,
        "timeout": 60.0,
        "enabled": True,
        "ssl_verify": base.infer_ssl_verify or "full",
        "ssl_ca_bundle": base.infer_ssl_ca_bundle or "",
    }
    settings.update(get_inference_overrides(db))
    return settings


def effective_docling_settings(db: Session | None) -> dict[str, Any]:
    """Merge .env defaults (Settings) with DB overrides for Docling Serve.

    Mirrors ``effective_inference_settings``:
    ``ssl_verify``/``ssl_ca_bundle`` feed ``DoclingService``'s httpx
    ``verify=``. ``api_key`` is env/Secret-only and never persisted or
    returned here (empty string = no Authorization header, current behavior).
    """
    base = get_settings()
    settings: dict[str, Any] = {
        "server_url": base.docling_server_url or "",
        "timeout_seconds": base.docling_timeout_seconds or 600.0,
        "ssl_verify": base.docling_ssl_verify or "full",
        "ssl_ca_bundle": base.docling_ssl_ca_bundle or "",
        "api_key": "",  # env-only; kept so callers see the shape
    }
    settings.update(_get_overrides(db, "docling", DOCLING_KEYS))
    return settings


def effective_document_settings(db: Session | None) -> dict[str, Any]:
    """Merge .env defaults with DB overrides for the document provider.

    ``provider`` selects the Customer Knowledge converter (``docling`` by
    default) — read by ``document_provider.build_converter`` at job runtime.
    ``api_key_configured`` is derived from the env and never persisted.
    """
    base = get_settings()
    settings: dict[str, Any] = {
        "provider": PROVIDER_DOCLING,
        "azure_endpoint": base.azure_di_endpoint or "",
        "azure_timeout_seconds": 600.0,
        "azure_ssl_verify": "full",
        "azure_ssl_ca_bundle": "",
    }
    settings.update(_get_overrides(db, "documents", DOCUMENTS_KEYS))
    settings["api_key_configured"] = bool(base.azure_di_api_key)
    return settings


def effective_email_settings(db: Session | None) -> dict[str, Any]:
    """Merge env defaults with non-secret email DB overrides."""
    base = get_settings()
    settings: dict[str, Any] = {
        "enabled": base.email_enabled,
        "smtp_host": base.email_smtp_host or "",
        "smtp_port": base.email_smtp_port or 587,
        "smtp_username": base.email_smtp_username or "",
        "smtp_security": base.email_smtp_security or "starttls",
        "from_address": base.email_from_address or "",
    }
    settings.update(_get_overrides(db, "email", EMAIL_KEYS))
    settings["password_configured"] = bool(base.email_smtp_password)
    return settings


# ── SystemConfig CRUD (moved from routes/admin_config.py) ────────────────────


def _apply_config_value(entry: SystemConfig, value: Any) -> None:
    """Store a Python value into the typed column matching its type.

    bool is checked before int (bool is an int subclass). All other value
    columns are cleared so an entry never holds two conflicting values.
    """
    entry.string_value = None
    entry.integer_value = None
    entry.float_value = None
    entry.boolean_value = None
    entry.json_value = None
    if value is None:
        entry.value_type = "string"
    elif isinstance(value, bool):
        entry.value_type = "boolean"
        entry.boolean_value = 1 if value else 0
    elif isinstance(value, int):
        entry.value_type = "integer"
        entry.integer_value = value
    elif isinstance(value, float):
        entry.value_type = "float"
        entry.float_value = value
    elif isinstance(value, (dict, list)):
        entry.value_type = "json"
        entry.json_value = value
    else:
        entry.value_type = "string"
        entry.string_value = str(value)


def get_entry(db: Session, category: str, key: str) -> SystemConfig | None:
    """Active config entry for a category+key, or None."""
    return db.query(SystemConfig).filter(
        and_(
            SystemConfig.category == category,
            SystemConfig.key == key,
            SystemConfig.is_active == 1,
        )
    ).first()


def summarize_configs(db: Session) -> dict[str, Any]:
    """Active entries grouped by category: {category: [entry dicts]} + total."""
    configs = db.query(SystemConfig).filter(SystemConfig.is_active == 1).all()
    categories: dict[str, list] = {}
    for c in configs:
        categories.setdefault(c.category, []).append(c.to_dict())
    return {"categories": categories, "total_entries": len(configs)}


def get_category_entries(db: Session, category: str) -> list[dict]:
    """Active entries for a single category, serialized."""
    configs = db.query(SystemConfig).filter(
        SystemConfig.category == category,
        SystemConfig.is_active == 1,
    ).all()
    return [c.to_dict() for c in configs]


def get_config_values(db: Session, category: str, keys: tuple) -> dict[str, Any]:
    """Non-null values for a fixed set of keys in a category."""
    config: dict[str, Any] = {}
    for key in keys:
        entry = get_entry(db, category, key)
        if entry:
            value = entry.to_dict()["value"]
            if value is not None:
                config[key] = value
    return config


def get_integration_summary(db: Session) -> dict[str, dict[str, Any]]:
    """Integration config values keyed by provider (slack/teams/jira)."""
    config: dict[str, dict[str, Any]] = {}
    for category in ("integration_slack", "integration_teams", "integration_jira"):
        entries = db.query(SystemConfig).filter(
            and_(SystemConfig.category == category, SystemConfig.is_active == 1)
        ).all()
        if entries:
            config[category.split("_")[-1]] = {
                e.key: e.to_dict()["value"] for e in entries
                if e.to_dict()["value"] is not None
            }
    return config


def create_entry(db: Session, category: str, values: dict[str, Any]) -> SystemConfig:
    """Create a new config entry. Raises ValueError if the key exists."""
    key = values["key"]
    if get_entry(db, category, key):
        raise ValueError(f"Config key '{key}' already exists in category '{category}'")
    config = SystemConfig(
        category=category,
        key=key,
        value_type=values.get("value_type"),
        string_value=values.get("string_value"),
        integer_value=values.get("integer_value"),
        float_value=values.get("float_value"),
        boolean_value=1 if values.get("boolean_value") else 0,
        json_value=values.get("json_value"),
        description=values.get("description"),
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def update_entry(db: Session, category: str, key: str,
                 values: dict[str, Any]) -> SystemConfig | None:
    """Apply non-None field updates to an entry. Returns None if not found."""
    config = get_entry(db, category, key)
    if not config:
        return None
    if values.get("value_type") is not None:
        config.value_type = values["value_type"]
    if values.get("string_value") is not None:
        config.string_value = values["string_value"]
    if values.get("integer_value") is not None:
        config.integer_value = values["integer_value"]
    if values.get("float_value") is not None:
        config.float_value = values["float_value"]
    if values.get("boolean_value") is not None:
        config.boolean_value = 1 if values["boolean_value"] else 0
    if values.get("json_value") is not None:
        config.json_value = values["json_value"]
    if values.get("description") is not None:
        config.description = values["description"]
    if values.get("is_active") is not None:
        config.is_active = 1 if values["is_active"] else 0
    db.commit()
    db.refresh(config)
    return config


def soft_delete_entry(db: Session, category: str, key: str) -> bool:
    """Soft-delete an entry (is_active=0). False if not found."""
    config = get_entry(db, category, key)
    if not config:
        return False
    config.is_active = 0
    db.commit()
    return True


def upsert_config_entry(db: Session, category: str, key: str, value: Any) -> None:
    """Create or update an active config entry, storing the value typed."""
    entry = get_entry(db, category, key)
    if entry:
        _apply_config_value(entry, value)
        entry.updated_at = datetime.now(UTC)
    else:
        entry = SystemConfig(category=category, key=key, is_active=1)
        _apply_config_value(entry, value)
        db.add(entry)
    db.commit()
