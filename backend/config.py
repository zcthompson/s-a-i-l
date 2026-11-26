"""Application configuration — reads from environment and config file."""


from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # AI Inference
    ai_endpoint: str = ""
    ai_api_key: str = ""
    # Default mirrors the dev .env (nemotron-lightning) so every environment
    # that lacks explicit config still delegates to the project's designated
    # model.
    ai_model: str = "nemotron-lightning"

    # Database
    database_url: str = Field(default="sqlite:///./sail.db", validation_alias=AliasChoices("DATABASE_URL", "SAIL_DATABASE_URL"))
    db_sslmode: str | None = Field(default=None, validation_alias=AliasChoices("DB_SSLMODE", "SAIL_DB_SSLMODE"))
    db_pool_size: int = Field(default=5, ge=1, validation_alias=AliasChoices("DB_POOL_SIZE", "SAIL_DB_POOL_SIZE"))
    db_max_overflow: int = Field(default=5, ge=0, validation_alias=AliasChoices("DB_MAX_OVERFLOW", "SAIL_DB_MAX_OVERFLOW"))
    sqlite_network_fs: bool = Field(default=False, validation_alias=AliasChoices("SQLITE_NETWORK_FS", "SAIL_SQLITE_NETWORK_FS"))
    files_dir: str = ""
    run_migrations_on_start: bool = Field(default=False, validation_alias=AliasChoices("RUN_MIGRATIONS_ON_START", "SAIL_RUN_MIGRATIONS_ON_START"))
    docling_startup_grace_seconds: float = Field(default=300, ge=0, validation_alias=AliasChoices("DOCLING_STARTUP_GRACE_SECONDS", "SAIL_DOCLING_STARTUP_GRACE_SECONDS"))


    # Docling Serve — document normalization for Customer Knowledge uploads
    # The hostname is
    # deliberately configurable: the backend container reaches Docling on the
    # host LAN IP (same path as AI_ENDPOINT), never on 127.0.0.1. An empty
    # api_key means no Authorization header is sent (current deployment
    # requires no key).
    docling_server_url: str = Field(default="http://docling.example.internal:5001", validation_alias=AliasChoices("DOCLING_URL", "SAIL_DOCLING_SERVER_URL"))
    docling_api_key: str = ""
    docling_timeout_seconds: float = Field(default=600.0, gt=0, validation_alias=AliasChoices("DOCLING_TIMEOUT_SECONDS", "SAIL_DOCLING_TIMEOUT_SECONDS"))

    # Azure Document Intelligence — alternative Customer Knowledge document
    # provider. The endpoint is the env default for the
    # admin-editable SystemConfig 'documents' category; the API key is
    # env/Secret-only (never persisted or returned). Env:
    #   SAIL_AZURE_DI_ENDPOINT / SAIL_AZURE_DI_API_KEY
    azure_di_endpoint: str = ""
    azure_di_api_key: str = ""

    # ── Connection trust model (SSL/TLS) ────────
    # Every outbound connection (inference, docling, and — from P1 — LDAP)
    # resolves its httpx ``verify=`` through services.ssl_trust.resolve_verify.
    # full = verify chain+hostname (default, today's behavior); skip = TLS on
    # but verification off (high-risk); ca = verify against an uploaded CA
    # bundle. Env is the default source; the admin Application-Settings UI can
    # override per-connection via SystemConfig. Env values:
    #   SAIL_INFER_SSL_VERIFY / SAIL_INFER_SSL_CA_BUNDLE
    #   SAIL_DOCLING_SSL_VERIFY / SAIL_DOCLING_SSL_CA_BUNDLE
    infer_ssl_verify: str = "full"
    infer_ssl_ca_bundle: str = ""
    docling_ssl_verify: str = "full"
    docling_ssl_ca_bundle: str = ""

    # ── Email notifications (SMTP) ─────────────────────────────────────
    # Env is the default source; the admin Application-Settings UI persists
    # overrides in SystemConfig category 'email' and they win at runtime.
    # The SMTP password is env/Secret-only — never persisted, never returned;
    # only the derived `password_configured` flag is exposed.
    email_enabled: bool = False
    email_smtp_host: str = ""
    email_smtp_port: int = Field(default=587, ge=1, le=65535)
    email_smtp_username: str = ""
    email_smtp_password: str = ""
    email_smtp_security: str = "starttls"
    email_from_address: str = ""

    # ── LDAP/AD directory auth ──────────────────────────────
    # Env is the source for the SECRET (service bind password) — the rest
    # live in SystemConfig category 'auth_ldap' (non-secret, admin-editable)
    # and override these env defaults via effective_ldap_settings().
    # Plan §3.4: 636 (ldaps://) and 389 (ldap:// + start_tls) are both
    # first-class; trust model reuses the P0b ssl_verify/ca bundle seam.
    auth_ldap_enabled: bool = False
    auth_ldap_server_uri: str = ""
    auth_ldap_service_bind_dn: str = ""
    auth_ldap_service_bind_password: str = ""
    auth_ldap_user_search_base_dn: str = ""
    auth_ldap_user_search_filter: str = ""
    auth_ldap_start_tls: bool = False
    auth_ldap_require_tls: bool = True
    auth_ldap_ssl_verify: str = "full"
    auth_ldap_ssl_ca_bundle: str = ""
    auth_ldap_timeout_seconds: float = 5.0
    auth_ldap_email_attr: str = "mail"
    auth_ldap_display_name_attr: str = "displayName"
    auth_ldap_department_attr: str = "department"
    auth_ldap_external_id_attr: str = "objectGUID"
    auth_ldap_auto_approve: bool = True
    auth_ldap_default_role: str = "user"
    auth_ldap_login_disabled: bool = False
    # Local self-registration (default true = today's behavior; the admin
    # Application-Settings area can hide the Register form when the
    # directory is the intended onboarding path).
    auth_ldap_local_register_enabled: bool = True

    # ── JWT / authentication (backend/auth.py;
    # moved from raw import-time os.environ reads into Settings) ──────────
    jwt_secret: str = ""
    api_keys: str = ""
    # A-10 (operator ruling 2026-11-01): the explicit auth feature switch.
    # "" (unset) = legacy behavior — auth ON iff api_keys is non-empty.
    # "1"/"true"/"yes"/"on" → ON; "0"/"false"/"no"/"off" → OFF. Any other
    # value fails at import (see auth.resolve_auth_enabled).
    auth_enabled: str = ""
    token_expire_minutes: int = 1440
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15
    min_password_length: int = 12
    require_uppercase: bool = False
    require_lowercase: bool = False
    require_digit: bool = False
    require_special: bool = False

    # ── Rate limiting / network (backend/rate_limit.py, backend/main.py) ──
    cors_origins: str = ""
    rate_limit_requests: int = 10000
    rate_limit_window: int = 3600
    login_rate_limit_requests: int = 10
    login_rate_limit_window: int = 3600
    register_rate_limit_requests: int = 5
    register_rate_limit_window: int = 3600
    trusted_proxies: str = ""
    max_upload_bytes: int = 10 * 1024 * 1024
    metrics_history: int = 1000

    # ── Integration env fallbacks (services/integration_service.py;
    # SAIL_-prefixed names are canonical; the
    # unprefixed legacy names survive as aliases at the read site) ───────
    slack_webhook_url: str = ""
    teams_webhook_url: str = ""
    jira_url: str = ""
    jira_api_key: str = ""
    jira_project_key: str = ""

    # .env loading is done via load_dotenv() in backend/main.py (app),
    # tests/backend/conftest.py (tests), and alembic/env.py (migrations).
    # Do NOT set env_file here: this pydantic-settings version injects every
    # dotenv variable into validation, and extra_forbidden rejects the
    # non-Settings keys (SERVE_FRONTEND — unprefixed by deployment
    # convention, deliberately kept as an import-time raw read in
    # backend/main.py).
    model_config = {"env_prefix": "SAIL_"}


def get_settings() -> Settings:
    """Return fresh settings instance — always reads environment variables.

    Previously cached with @lru_cache() but that prevented test environments
    from overriding SAIL_DATABASE_URL after import time. Removing the
    cache ensures settings always reflect the current environment.
    """
    return Settings()
