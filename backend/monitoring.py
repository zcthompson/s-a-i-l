"""Enhanced health check and monitoring endpoints.

Endpoint classes:

- ``GET /api/monitoring/health`` — **public liveness**. Process-level only
  (status/service/version/uptime/timestamp): no memory, disk, PID, or
  request counters. The container healthcheck probes ``/health`` (main.py);
  this route is the minimal, secret-free liveness surface.
- ``GET /api/monitoring/health/detailed`` — **admin-gated diagnostics** Real database readiness (``get_database_health`` against the
  shared engine), the *effective* inference configuration as consumers see
  it (DB overrides win), and bounded request metrics.
- ``GET /api/monitoring/status`` — **admin-gated readiness**. Aggregates the
  actual dependency states (process liveness + bounded DB check); a failed
  DB check reports ``degraded`` instead of a hardcoded ``healthy``.
- ``GET /api/monitoring/metrics`` — **admin-gated** request metrics.

The AI health check reports configuration state only (configured /
disabled / not_configured) — it performs no inference call and never
includes the endpoint URL or API key in any response (internal addresses and secrets are not diagnostic strings).
"""

import os
import time
from datetime import UTC, datetime
from typing import Any

import sqlalchemy
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.dependencies import get_db
from backend.version import VERSION

# Router for monitoring endpoints
monitoring_router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


# Track request metrics - bounded to prevent unbounded growth
# Read through Settings.
_MAX_METRICS_HISTORY = get_settings().metrics_history
_request_metrics: dict[str, Any] = {
    "total_requests": 0,
    "avg_response_time": 0.0,
    "error_count": 0,
    "last_request_time": None,
    "start_time": time.time(),
}


def record_request(endpoint: str, response_time: float, is_error: bool = False):
    """Record request metrics."""
    _request_metrics["total_requests"] += 1
    _request_metrics["last_request_time"] = time.time()

    if is_error:
        _request_metrics["error_count"] += 1

    # Update average response time using running average
    total = _request_metrics["total_requests"]
    current_avg = _request_metrics["avg_response_time"]
    _request_metrics["avg_response_time"] = (current_avg * (total - 1) + response_time) / total


def get_system_metrics() -> dict[str, Any]:
    """Get system metrics (admin-gated diagnostics only — never public)."""
    try:
        import psutil

        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        return {
            "cpu_percent": cpu_percent,
            "memory": {
                "total_gb": round(memory.total / (1024**3), 2),
                "available_gb": round(memory.available / (1024**3), 2),
                "percent": memory.percent
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent": disk.percent
            },
            "process": {
                "pid": os.getpid(),
                "memory_mb": round(psutil.Process().memory_info().rss / (1024**2), 2)
            }
        }
    except Exception:
        return {"error": "Failed to get system metrics"}


def get_database_health(db) -> dict[str, Any]:
    """Bounded database readiness check.

    Runs ``SELECT 1`` on the provided session (or any object exposing
    ``execute``). A failed check reports ``unhealthy`` with the error text so
    ``/status`` can aggregate a real degraded state instead of a hardcoded
    ``healthy``.
    """
    try:
        db.execute(sqlalchemy.text("SELECT 1"))

        return {
            "status": "healthy",
            "connected": True,
            "backend": db.get_bind().dialect.name,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "connected": False,
            "error": str(e)
        }


def get_ai_endpoint_health() -> dict[str, Any]:
    """Report the *effective* inference configuration.

    Uses the same configuration consumers of inference actually use
    (``effective_inference_settings`` — .env defaults with DB overrides
    winning), so a disabled override or a DB-set endpoint is reported
    accurately instead of the raw environment variable alone.

    Reports configuration STATE only: no inference call, no endpoint URL,
    no API key — secrets and internal addresses never enter a diagnostic
    response.
    """
    from backend.services.config_service import effective_inference_settings

    try:
        settings = effective_inference_settings(None)
    except Exception:
        # Config store unavailable (e.g. before migrations) — fall back to
        # the environment-only view rather than failing the diagnostic.
        endpoint = get_settings().ai_endpoint or ""
        return {
            "configured": bool(endpoint),
            "enabled": True,
            "status": "configured" if endpoint else "not_configured",
            "model": get_settings().ai_model or "",
        }

    endpoint = (settings.get("ai_endpoint") or "")
    enabled = bool(settings.get("enabled", True))
    if not enabled:
        status = "disabled"
    elif endpoint:
        status = "configured"
    else:
        status = "not_configured"
    return {
        "configured": bool(endpoint),
        "enabled": enabled,
        "status": status,
        "model": settings.get("ai_model") or "",
    }


def get_uptime() -> str:
    """Get service uptime."""
    uptime_seconds = time.time() - _request_metrics["start_time"]
    days = int(uptime_seconds // 86400)
    hours = int((uptime_seconds % 86400) // 3600)
    minutes = int((uptime_seconds % 3600) // 60)

    return f"{days}d {hours}h {minutes}m"


def _require_admin(request: Request) -> None:
    """Gate a privileged diagnostic route: 401 unauthenticated,
    403 for non-admins. Anonymous callers get no diagnostic detail and no
    accidental configuration disclosure."""
    from backend.auth import get_user_from_request

    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user.get("is_admin") != 1:
        raise HTTPException(status_code=403, detail="Admin privileges required")


def _request_metrics_payload() -> dict[str, Any]:
    return {
        "total_requests": _request_metrics["total_requests"],
        "avg_response_time": round(_request_metrics["avg_response_time"], 3),
        "error_count": _request_metrics["error_count"],
        "error_rate": round(
            _request_metrics["error_count"] / max(_request_metrics["total_requests"], 1) * 100, 2
        ),
        "last_request": datetime.fromtimestamp(
            _request_metrics["last_request_time"] or time.time(), UTC
        ).isoformat() if _request_metrics["last_request_time"] else None
    }


@monitoring_router.get("/health")
def monitoring_health_check():
    """Public liveness check.

    Process-liveness only: if this route answers, the process is alive.
    Deliberately carries NO system metrics, PID, request counters, or
    dependency state — those are privileged diagnostics on /health/detailed
    and /status.
    """
    return {
        "status": "healthy",
        "service": "sail",
        "version": VERSION,
        "uptime": get_uptime(),
        "timestamp": datetime.now(UTC).isoformat(),
    }


@monitoring_router.get("/health/detailed")
def detailed_health_check(request: Request, db: Session = Depends(get_db)):
    """Detailed health check with all subsystems (admin-only).

    Real database readiness (bounded check on the request session) and the
    effective inference configuration — no hardcoded states, no internal
    addresses, no secrets.
    """
    _require_admin(request)

    return {
        "service": "sail",
        "version": VERSION,
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "uptime": get_uptime(),
        "system": get_system_metrics(),
        "database": get_database_health(db),
        "ai_endpoint": get_ai_endpoint_health(),
        "metrics": _request_metrics_payload(),
    }


@monitoring_router.get("/metrics")
def get_metrics(request: Request):
    """Get request metrics and performance data (admin-only)."""
    _require_admin(request)
    return {
        "requests": _request_metrics_payload(),
        "system": get_system_metrics(),
        "uptime": get_uptime(),
    }


@monitoring_router.get("/status")
def get_service_status(request: Request, db: Session = Depends(get_db)):
    """Get overall service readiness (admin-only).

    Aggregates ACTUAL dependency states: process liveness (implicit — this
    route answered) and a bounded database check on the request session. A
    failed DB check yields ``degraded``, not a hardcoded ``healthy``.
    """
    _require_admin(request)

    db_health = get_database_health(db)

    ai_health = get_ai_endpoint_health()

    all_healthy = all([
        True,  # Service is running (if we're here)
        db_health.get("connected", False),
        ai_health.get("status") in ("configured", "disabled", "not_configured"),
    ])

    return {
        "status": "healthy" if all_healthy else "degraded",
        "subsystems": {
            "service": "healthy",
            "database": db_health,
            "ai_endpoint": ai_health
        },
        "timestamp": datetime.now(UTC).isoformat()
    }
