"""Container bootstrap and public, sanitized readiness checks."""
import logging
import os
from tempfile import NamedTemporaryFile

from sqlalchemy import text

from backend.config import get_settings
from backend.database import create_engine
from backend.storage import prepare_directories

logger = logging.getLogger(__name__)


def prepare_runtime():
    settings = get_settings()
    root = prepare_directories(settings)
    workers = os.environ.get("WEB_CONCURRENCY", os.environ.get("UVICORN_WORKERS", "1"))
    if settings.database_url.startswith("sqlite") and settings.sqlite_network_fs and workers != "1":
        logger.warning("SQLite network storage requires exactly one application worker")
    return root


def readiness() -> tuple[dict, int]:
    settings = get_settings()
    backend = "postgres" if settings.database_url.startswith(("postgres:", "postgresql")) else "sqlite"
    result = {"status": "ready", "database_backend": backend,
              "database": "unavailable", "files": "unavailable", "docling": "unavailable"}
    try:
        with create_engine(settings.database_url).connect() as connection:
            connection.execute(text("SELECT 1"))
        result["database"] = "ok"
    except Exception:
        pass  # Public readiness must not disclose a DSN, paths or driver errors.
    try:
        root = prepare_directories(settings)
        with NamedTemporaryFile(prefix=".sail-ready-", dir=root, delete=True):
            pass
        result["files"] = "ok"
    except (OSError, ValueError):
        pass
    try:
        from backend.services.docling_service import DoclingService
        DoclingService().health(timeout_seconds=1)
        result["docling"] = "ok"
    except Exception:
        pass
    ready = result["database"] == "ok" and result["files"] == "ok"
    result["status"] = "ready" if ready else "unavailable"
    return result, 200 if ready else 503


if __name__ == "__main__":
    prepare_runtime()
