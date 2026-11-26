"""FastAPI application entry point."""

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.auth import AUTH_ENABLED
from backend.config import get_settings
from backend.monitoring import monitoring_router, record_request
from backend.rate_limit import RateLimitMiddleware
from backend.routes.account_brief import router as account_brief_router
from backend.routes.account_impact import router as account_impact_router
from backend.routes.account_memberships import (
    admin_router as ownership_review_router,
)
from backend.routes.account_memberships import (
    router as account_memberships_router,
)
from backend.routes.account_strategy import router as account_strategy_router
from backend.routes.admin_config import router as admin_config_router
from backend.routes.advanced import router as advanced_router
from backend.routes.analytics import router as analytics_router
from backend.routes.auth import router as auth_router
from backend.routes.bulk import router as bulk_router
from backend.routes.comments import router as comments_router
from backend.routes.customer_activity import router as customer_activity_router
from backend.routes.customer_alias import router as customer_alias_router
from backend.routes.customer_contact import router as customer_contact_router
from backend.routes.customer_health import router as customer_health_router
from backend.routes.customer_intelligence import router as customer_intelligence_router
from backend.routes.customer_knowledge import router as customer_knowledge_router
from backend.routes.customer_sales_team import router as customer_sales_team_router
from backend.routes.customer_search import router as customer_search_router
from backend.routes.customer_sharing import router as customer_sharing_router
from backend.routes.customer_stats import router as customer_stats_router
from backend.routes.customer_task import router as customer_task_router
from backend.routes.customer_timeline import router as customer_timeline_router
from backend.routes.customers import router as customers_router
from backend.routes.deals import router as deals_router
from backend.routes.departments import router as departments_router
from backend.routes.export_pdf import router as export_pdf_router
from backend.routes.global_admin import router as global_admin_router
from backend.routes.integrations import router as integrations_router
from backend.routes.intelligence_import import router as intelligence_import_router
from backend.routes.netsuite_import import router as netsuite_import_router
from backend.routes.notifications import router as notifications_router
from backend.routes.projections import router as projections_router
from backend.routes.redhat_opportunity import router as redhat_opportunity_router
from backend.routes.rep_intelligence import router as rep_intelligence_router
from backend.routes.rvtools_import import router as rvtools_import_router
from backend.routes.sales_evaluations import router as sales_evaluations_router
from backend.routes.sales_notes import router as sales_notes_router
from backend.routes.sales_section import router as sales_section_router
from backend.routes.saved_views import router as saved_views_router
from backend.routes.saved_views import worklist_router
from backend.routes.scoring import router as scoring_router
from backend.routes.stats import router as stats_router
from backend.routes.team_rollup import router as team_rollup_router
from backend.routes.technology_dependencies import (
    router as technology_dependencies_router,
)
from backend.routes.technology_inventory import router as technology_inventory_router
from backend.routes.third_party_services import router as third_party_services_router
from backend.routes.use_cases import router as use_cases_router
from backend.services.notification_service import connection_manager
from backend.services.task_notification_evaluator import start_task_evaluator
from backend.version import VERSION


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """App startup/shutdown.

    Captures the main event loop so sync producers (threadpool route
    handlers) can schedule per-recipient WebSocket sends via
    ``asyncio.run_coroutine_threadsafe``.
    """
    from backend.runtime import prepare_runtime
    prepare_runtime()
    connection_manager.set_main_loop(asyncio.get_running_loop())
    evaluator_stop = start_task_evaluator()
    try:
        yield
    finally:
        evaluator_stop.set()

app = FastAPI(
    title="Sales Analytics and Intelligence Launchpad (S-A-I-L)",
    version=VERSION,
    description="AI Readiness Scoring & Use Case Management Platform",
    redirect_slashes=False,
    lifespan=_lifespan,
)

# CORS (A-8 re-recon 2026-11-01: through Settings — .env is loaded above)
_allowed_settings = get_settings()
allowed_origins = _allowed_settings.cors_origins.split(",")
if not allowed_origins or (len(allowed_origins) == 1 and allowed_origins[0] == ""):
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
else:
    app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_credentials=True, allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["*"], expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"])

# Rate limiting
if AUTH_ENABLED:
    app.add_middleware(RateLimitMiddleware)

# Track request timing — the bounded metrics store is
# monitoring.record_request (this module's ``_request_times`` second store
# was dead code — written, never read; re-recon A-6).
@app.middleware("http")
async def track_requests(request: Request, call_next):
    start_time = time.time()
    try:
        response = await call_next(request)
        response_time = time.time() - start_time
        is_error = response.status_code >= 400
        if request.url.path not in {"/health", "/healthz", "/readyz", "/openapi.json", "/docs", "/redoc", "/monitoring"}:
            record_request(request.url.path, response_time, is_error)
        return response
    except Exception:
        import traceback
        traceback.print_exc()
        response_time = time.time() - start_time
        record_request(request.url.path, response_time, True)
        raise

# RBAC write-blocking. Auditors are read-only everywhere (they have no
# legitimate write endpoint). A sales_admin manages users/memberships but may
# not write account content: these are the CONTENT path prefixes blocked for
# mutating verbs (membership/user-admin routes are deliberately absent).
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_SALES_ADMIN_CONTENT_PREFIXES = (
    "/api/netsuite-import",
    "/api/use-cases", "/api/sales-notes", "/api/customer-knowledge",
    "/api/departments", "/api/projections", "/api/technology",
    "/api/third-party-services", "/api/sales-evaluations", "/api/comments",
    "/api/bulk", "/api/scoring",
    "/api/intelligence-import", "/api/rvtools-import", "/api/rep-intelligence",
    "/api/redhat-opportunity-import",
)
_SALES_ADMIN_CUSTOMER_CONTENT = (
    "use-cases", "sales-notes", "knowledge", "departments", "projections",
    "technology", "technology-dependencies", "third-party-services",
    "sales-evaluations", "assessments",
)


def _rbac_write_block_reason(request: Request) -> str | None:
    """403 detail when the caller's role may not perform this mutating verb."""
    auth_header = request.headers.get("Authorization", "")
    if request.method not in _MUTATING_METHODS or not auth_header.startswith("Bearer "):
        return None
    from backend.auth import _get_user_by_username, decode_access_token
    payload = decode_access_token(auth_header[7:])
    username = payload.get("sub") if payload else None
    user = _get_user_by_username(username) if username else None
    if not user:
        return None
    from backend.services.sales_access import effective_role
    role = effective_role(user)
    if role == "auditor":
        # own-account actions (e.g. password change) are not account writes
        if request.url.path.startswith("/api/auth/"):
            return None
        return "Auditor role is read-only"
    if role == "sales_admin":
        path = request.url.path
        parts = path.strip("/").split("/")
        content = path.startswith(_SALES_ADMIN_CONTENT_PREFIXES) or (
            len(parts) >= 4 and parts[:2] == ["api", "customers"]
            and parts[3] in _SALES_ADMIN_CUSTOMER_CONTENT
        )
        if content:
            return "Sales admin cannot modify account content"
    return None


@app.middleware("http")
async def rbac_write_block(request: Request, call_next):
    reason = _rbac_write_block_reason(request)
    if reason:
        return JSONResponse(status_code=403, content={"detail": reason})
    return await call_next(request)

# Include monitoring endpoints first (they're public)
app.include_router(monitoring_router)

# Include routes
app.include_router(comments_router)
app.include_router(use_cases_router)
app.include_router(scoring_router)
app.include_router(stats_router)
app.include_router(bulk_router)
app.include_router(advanced_router)
app.include_router(notifications_router)
app.include_router(analytics_router)
app.include_router(export_pdf_router)
app.include_router(integrations_router)
app.include_router(auth_router)
app.include_router(customer_stats_router)
app.include_router(account_brief_router)
app.include_router(account_impact_router)
app.include_router(customer_sharing_router)
app.include_router(customer_sales_team_router)
app.include_router(projections_router)
app.include_router(customers_router)
app.include_router(customer_alias_router)
app.include_router(departments_router)
app.include_router(global_admin_router)
app.include_router(admin_config_router)
app.include_router(sales_section_router)
app.include_router(customer_knowledge_router)
app.include_router(intelligence_import_router)
app.include_router(rep_intelligence_router)
app.include_router(redhat_opportunity_router)
app.include_router(netsuite_import_router)
app.include_router(rvtools_import_router)
app.include_router(sales_evaluations_router)
app.include_router(technology_inventory_router)
app.include_router(technology_dependencies_router)
app.include_router(sales_notes_router)
app.include_router(customer_contact_router)
app.include_router(customer_search_router)
app.include_router(customer_activity_router)
app.include_router(customer_task_router)
app.include_router(deals_router)
app.include_router(saved_views_router)
app.include_router(worklist_router)
app.include_router(team_rollup_router)
app.include_router(account_strategy_router)
app.include_router(third_party_services_router)
app.include_router(customer_intelligence_router)
app.include_router(customer_timeline_router)
app.include_router(customer_health_router)
app.include_router(account_memberships_router)
app.include_router(ownership_review_router)

# Health check
@app.get("/healthz")
def liveness():
    return {"status": "alive", "service": "sail"}


@app.get("/readyz")
def readiness_check():
    from backend.runtime import readiness
    payload, status = readiness()
    return JSONResponse(payload, status_code=status)


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "sail", "version": VERSION, "auth_enabled": AUTH_ENABLED}

# Serve built frontend — SPA with static assets and SPA routing via middleware.
# /assets (hashed JS/CSS bundles) is served by a StaticFiles mount; the SPA
# middleware serves other built files from the dist root (frontend/public
# assets such as /sail_logo.svg) and falls back to index.html for
# client-side routes (deep links) that have no backing file.
#
# Extracted into install_spa_serving() so the exact serving logic can be unit
# tested (tests/backend/test_spa_serving.py) against a synthetic dist without
# touching the shared app / other tests.
def install_spa_serving(app: FastAPI, dist: str) -> None:
    """Mount /assets and register the SPA-routing middleware for one origin."""
    dist_root = Path(dist).resolve()
    assets_dir = dist_root / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir), html=False), name="static")
    index_file = dist_root / "index.html"

    @app.middleware("http")
    async def spa_routing(request: Request, call_next):
        if (request.method == "GET" and
                not request.url.path.startswith("/api/") and
                not request.url.path.startswith("/assets/") and
                request.url.path not in ("/health", "/healthz", "/readyz", "/openapi.json", "/docs", "/redoc", "/monitoring")):
            # A real file at the dist root (Vite copies frontend/public/* there
            # unhashed) is served as-is — otherwise the SPA fallback would hand
            # index.html to asset URLs (a blank <img>). The is_relative_to check
            # keeps path-traversal candidates inside the dist tree.
            candidate = (dist_root / request.url.path.lstrip("/")).resolve()
            if candidate.is_file() and candidate.is_relative_to(dist_root):
                return FileResponse(candidate)
            if index_file.is_file():
                return HTMLResponse(content=index_file.read_text())
        return await call_next(request)


frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(frontend_dist) and os.environ.get("SERVE_FRONTEND", "").lower() in ("1", "true"):
    install_spa_serving(app, frontend_dist)
