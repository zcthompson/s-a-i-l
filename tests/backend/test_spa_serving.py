"""SPA static-serving regression tests (single-container topology).

The single-container deployment serves the built SPA + /api + /health from one
origin. ``backend.main.install_spa_serving(app, dist)`` mounts a StaticFiles
layer for ``/assets`` and registers an SPA-routing middleware that:

- serves real files at the dist root (Vite copies ``frontend/public/*`` there
  unhashed, e.g. ``/sail_logo.svg``), and
- falls back to ``index.html`` for client-side routes (deep links) with no
  backing file, and
- leaves ``/api/*``, ``/health``, ``/openapi.json`` and the docs paths to the
  app's own routes.

Without the file check, the 2026-09-15 single-container migration caused the
login-screen logo to render blank: ``/sail_logo.svg`` was swallowed by
the SPA fallback and served as ``index.html`` (1129 bytes of HTML where a JPEG
was expected). These tests pin the fix by driving the real serving logic on a
throwaway FastAPI app — no reload, no shared-app pollution.

Run: pytest tests/backend/test_spa_serving.py -v
"""

import tempfile
from pathlib import Path

import pytest
from backend.main import install_spa_serving
from fastapi import FastAPI
from fastapi.testclient import TestClient

LOGO_BYTES = b"\xff\xd8\xff\xe0fakejpegcontent"
INDEX_HTML = b"<!DOCTYPE html><html><body>S-A-I-L SPA</body></html>"
BUNDLE_JS = b"console.log('spa')"


@pytest.fixture
def spa_app():
    """TestClient over a throwaway app with the real SPA logic installed
    against a synthetic dist (index.html + root-level logo + one asset) and a
    real /health + /api/customers/ handler (to prove the exclusions still
    reach the app's own routes)."""
    app = FastAPI()

    @app.get("/health")
    def _health():
        return {"status": "healthy"}

    @app.get("/api/customers/")
    def _api_customers():
        return {"customers": []}

    with tempfile.TemporaryDirectory() as tmp:
        dist = Path(tmp) / "dist"
        assets = dist / "assets"
        assets.mkdir(parents=True)
        (dist / "index.html").write_bytes(INDEX_HTML)
        (dist / "sail_logo.svg").write_bytes(LOGO_BYTES)
        (assets / "index-abc.js").write_bytes(BUNDLE_JS)

        install_spa_serving(app, str(dist))
        with TestClient(app) as c:
            yield c


class TestSpaServing:
    def test_public_asset_at_dist_root_served_as_file(self, spa_app):
        """The login-screen logo: a Vite public/ asset at the dist root must be
        served as its original bytes (image/svg+xml), NOT the SPA index.html
        fallback. This is the regression that blanked the logo on 0.2.1."""
        r = spa_app.get("/sail_logo.svg")
        assert r.status_code == 200
        assert r.content == LOGO_BYTES
        assert r.headers["content-type"].startswith("image/svg+xml")

    def test_deep_link_without_backing_file_falls_back_to_index(self, spa_app):
        """Client-side routes (/customers, /settings) must return index.html so
        the SPA router can handle them — preserving deep-link behaviour."""
        for path in ("/customers", "/settings", "/"):
            r = spa_app.get(path)
            assert r.status_code == 200
            assert r.content == INDEX_HTML
            assert r.headers["content-type"].startswith("text/html")

    def test_assets_mount_serves_hashed_bundle(self, spa_app):
        """/assets/* (the StaticFiles mount) is unaffected by the SPA file
        check — hashed bundles serve as before."""
        r = spa_app.get("/assets/index-abc.js")
        assert r.status_code == 200
        assert r.content == BUNDLE_JS
        assert r.headers["content-type"].startswith("text/javascript")

    def test_api_and_health_reach_the_app_routes(self, spa_app):
        """/api/* and /health must fall through to the app's own handlers (not
        be swallowed by the SPA middleware) — the exclusions still work."""
        r = spa_app.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "healthy"}
        r = spa_app.get("/api/customers/")
        assert r.status_code == 200
        assert r.json() == {"customers": []}

    def test_path_traversal_does_not_escape_the_dist_root(self, spa_app):
        """A dist-root candidate that resolves outside the dist tree must NOT be
        served as a file — the is_relative_to check guards against traversal."""
        # Encoded traversal /..%2f..%2fetc%2fpasswd resolves to /etc/passwd,
        # which is NOT relative to the dist tree → falls back to the SPA
        # index.html. Never the raw file contents.
        r = spa_app.get("/..%2f..%2fetc%2fpasswd")
        assert b"root:" not in r.content
        assert r.content in (INDEX_HTML, b"")
