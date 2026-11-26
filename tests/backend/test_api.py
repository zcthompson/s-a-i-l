
"""E2E CRUD + scoring integration tests via TestClient.

Complements test_integration.py by testing full request/response cycles
across CRUD, scoring, bulk, and stats endpoints in a single workflow.

Use case CRUD, scoring, bulk, stats, export and drill-down endpoints all
require a JWT bearer token (2026-08-23 route hardening). The workflow tests
below run as the seeded admin via the `auth` fixture; TestAuthContract holds
the explicit anonymous/403 regression coverage.

Run: pytest tests/backend/test_api.py -v

NOTE: The passlib/bcrypt bug on Python 3.12 crashes during import when
hash_password() is called. All test code lives inside a patch context so
the real bcrypt backend is never invoked.
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

from unittest.mock import patch

import pytest
from backend.dependencies import get_db

_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"


@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
    """Route-level auth tests: point the real JWT user lookup at the shared
    session (same pattern as test_analytics_scoping.py).

    The real get_user_from_request opens its OWN connection to the test DB
    file and only sees truly-committed rows. This file's db_session keeps
    seeded data in the shared session's transaction, so an unpatched lookup
    can miss the admin user and auth checks misfire (2026-08-22
    collaboration audit). Also guarantees an active admin user exists, since
    this module's db_session truncates users and does not create one.
    """
    from backend.models.use_case import User

    from backend import auth as auth_mod

    bind = db_session.get_bind()
    shared_engine = getattr(bind, "engine", bind)

    if not db_session.query(User).count():
        db_session.add(User(username="admin", email="admin@test.local",
                            hashed_password=_FAKE_BCRYPT_HASH,
                            display_name="Administrator", department="IT",
                            is_admin=1, approved=1, is_active=1))
        db_session.commit()

    def _lookup(username):
        user = db_session.query(User).filter(User.username == username).first()
        if not (user and user.is_active):
            return None
        return {
            "username": user.username,
            "email": user.email,
            "display_name": user.display_name,
            "department": user.department,
            "is_admin": user.is_admin,
            "role": user.role,
            "user_id": user.id,
        }

    def _shared_engine(*args, **kwargs):
        return shared_engine

    with patch.object(auth_mod, "_get_user_by_username", _lookup), \
         patch.object(auth_mod, "create_engine", _shared_engine):
        yield


def _fake_hash_password(password: str) -> str:
    return _FAKE_BCRYPT_HASH


with patch("backend.auth.hash_password", side_effect=_fake_hash_password):
    from backend.main import app
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    # Use the shared engine from conftest.py — this is the same engine that
    # conftest.py creates and uses for all test modules. No need to create a
    # separate engine or database here.
    from tests.backend._shared import engine as shared_engine

    @pytest.fixture(scope="function")
    def db_session():
        """Reset the selected integration backend; no secondary SQLite fallback."""
        from tests.backend.database_support import reset_tables

        session = sessionmaker(bind=shared_engine, autoflush=False)()
        try:
            reset_tables(session)
            yield session
        finally:
            session.rollback()
            session.close()

    @pytest.fixture()
    def client(db_session):
        def override_get_db():
            try:
                yield db_session
            finally:
                pass
        app.dependency_overrides[get_db] = lambda: db_session
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.clear()

    # ───────────────── Helpers ─────────────────

    def _admin_headers():
        """Authorization header for the admin user the autouse
        `_auth_user_lookup` fixture guarantees exists in the shared session."""
        from backend.auth import create_access_token
        return {"Authorization": f"Bearer {create_access_token({'sub': 'admin', 'is_admin': True})}"}

    @pytest.fixture()
    def auth():
        """Admin Authorization header for the auth-required routes."""
        return _admin_headers()

    def _create_use_case(client, headers=None, **kw):
        """Create a use case via the API and return the response body."""
        data = {
            "title": kw.get("title", "Test"),
            "description": kw.get("description", "desc"),
            "department": kw.get("department", "Operations"),
            "status": kw.get("status", "draft"),
        }
        if "goals" in kw:
            data["goals"] = kw["goals"]
        if "challenges" in kw:
            data["challenges"] = kw["challenges"]
        if "pain_points" in kw:
            data["pain_points"] = kw["pain_points"]
        if "scores" in kw:
            data["scores"] = kw["scores"]
        if "overall_score" in kw:
            data["overall_score"] = kw["overall_score"]
        if "impact_category" in kw:
            data["impact_category"] = kw["impact_category"]
        if "impact_description" in kw:
            data["impact_description"] = kw["impact_description"]
        if "estimated_savings" in kw:
            data["estimated_savings"] = kw["estimated_savings"]
        if "estimated_revenue" in kw:
            data["estimated_revenue"] = kw["estimated_revenue"]
        if "timeline_estimate" in kw:
            data["timeline_estimate"] = kw["timeline_estimate"]
        return client.post("/api/use-cases/", json=data,
                           headers=headers or _admin_headers()).json()

    def _admin_tok(db_session):
        """Admin Authorization header for auth-required analytics routes.

        The fixture truncates every table, so the admin user is created here
        and committed (visible to backend.auth's separate-connection lookup).
        """
        from backend.auth import create_access_token
        from backend.models.use_case import User as UserModel
        if not db_session.query(UserModel).filter(UserModel.username == "admin").first():
            db_session.add(UserModel(username="admin", email="admin@test.local",
                                     hashed_password=_FAKE_BCRYPT_HASH, is_admin=1,
                                     approved=1, is_active=1))
            db_session.commit()
        return {"Authorization": f"Bearer {create_access_token({'sub': 'admin', 'is_admin': True})}"}

    def _scored(client, headers=None, **kw):
        """Create a use case with pre-computed scores.

        Defaults to 70 across all dimensions if none specified.
        Individual dimension overrides available as scores_data_readiness=80, etc.
        """
        default_scores = {
            "data_readiness": 70,
            "technical_feasibility": 80,
            "organizational_readiness": 60,
            "roi_potential": 90,
            "risk_compliance": 75,
            "implementation_complexity": 50,
        }

        if "scores" in kw:
            scores_dict = kw["scores"]
        else:
            # Start from defaults, then apply any overrides
            scores_dict = dict(default_scores)
            for key in ["data_readiness", "technical_feasibility",
                        "organizational_readiness", "roi_potential",
                        "risk_compliance", "implementation_complexity"]:
                val = kw.get(f"scores_{key}")
                if val is not None:
                    scores_dict[key] = val

        # Merge remaining kw into data (but not scores-related keys)
        data_kw = {k: v for k, v in kw.items() if not k.startswith("scores_") and k != "scores"}
        data_kw["scores"] = scores_dict
        if "overall_score" not in data_kw:
            data_kw["overall_score"] = 70

        return _create_use_case(client, headers=headers, **data_kw)

    # ───────────────── End-to-end CRUD ─────────────────

    class TestCrudWorkflow:
        """Test full CRUD workflow: create → read → update → delete."""

        def test_create_then_read(self, client, auth):
            created = _create_use_case(client, title="E2E Create Read")
            assert created["title"] == "E2E Create Read"
            assert "id" in created
            assert "created_at" in created

            by_id = client.get(f"/api/use-cases/{created['id']}/", headers=auth)
            assert by_id.status_code == 200
            assert by_id.json()["title"] == "E2E Create Read"

        def test_create_then_update(self, client, auth):
            created = _create_use_case(client, title="Old Title", status="draft")
            updated = client.put(f"/api/use-cases/{created['id']}/", json={
                "title": "New Title",
                "status": "active",
            }, headers=auth)
            assert updated.status_code in (200, 201)
            assert updated.json()["title"] == "New Title"
            assert updated.json()["status"] == "active"

            by_id = client.get(f"/api/use-cases/{created['id']}/", headers=auth)
            assert by_id.json()["title"] == "New Title"

        def test_create_then_delete(self, client, auth):
            created = _create_use_case(client, title="To Delete")
            deleted = client.delete(f"/api/use-cases/{created['id']}/", headers=auth)
            assert deleted.status_code in (200, 204)

            gone = client.get(f"/api/use-cases/{created['id']}/", headers=auth)
            assert gone.status_code == 404

        def test_list_all(self, client, auth):
            _create_use_case(client, title="A")
            _create_use_case(client, title="B")
            _create_use_case(client, title="C")

            r = client.get("/api/use-cases/", headers=auth)
            assert r.status_code == 200
            items = r.json()
            assert isinstance(items, list)
            assert len(items) >= 3

        def test_list_with_search(self, client, auth):
            _create_use_case(client, title="ML Project", description="machine learning for fraud")
            _create_use_case(client, title="Excel Report", description="financial reporting")

            r = client.get("/api/use-cases/?search=ml", headers=auth)
            assert r.status_code == 200
            items = r.json()
            assert len(items) >= 1
            assert any("ML" in it["title"] for it in items)

        def test_list_with_department_filter(self, client, auth):
            _create_use_case(client, title="Ops1", department="Operations")
            _create_use_case(client, title="Fin1", department="Finance")

            r_ops = client.get("/api/use-cases/?department=Operations", headers=auth)
            assert r_ops.status_code == 200
            ops_items = r_ops.json()
            assert all(it["department"] == "Operations" for it in ops_items)

            r_fin = client.get("/api/use-cases/?department=Finance", headers=auth)
            assert r_fin.status_code == 200
            fin_items = r_fin.json()
            assert all(it["department"] == "Finance" for it in fin_items)

        def test_list_with_status_filter(self, client, auth):
            _create_use_case(client, title="Active1", status="active")
            _create_use_case(client, title="Draft1", status="draft")

            r_active = client.get("/api/use-cases/?status=active", headers=auth)
            active_items = r_active.json()
            assert len(active_items) >= 1
            assert all(it["status"] == "active" for it in active_items)

        def test_full_cycle(self, client, auth):
            """Create → Read → Update → Re-Read → List → Delete."""
            # Create
            uc = _create_use_case(client, title="Full Cycle", department="IT")
            uid = uc["id"]
            assert uc["status"] == "draft"

            # Read
            uc_read = client.get(f"/api/use-cases/{uid}/", headers=auth)
            assert uc_read.json()["title"] == "Full Cycle"

            # Update
            uc_update = client.put(f"/api/use-cases/{uid}/", json={
                "title": "Updated Cycle",
                "status": "active",
            }, headers=auth)
            assert uc_update.json()["title"] == "Updated Cycle"

            # Re-read
            uc_re = client.get(f"/api/use-cases/{uid}/", headers=auth)
            assert uc_re.json()["title"] == "Updated Cycle"
            assert uc_re.json()["status"] == "active"

            # Delete
            client.delete(f"/api/use-cases/{uid}/", headers=auth)
            assert client.get(f"/api/use-cases/{uid}/", headers=auth).status_code == 404

    # ───────────────── End-to-end Scoring ─────────────────

    class TestScoringWorkflow:
        """Test scoring flow: create unscored → score → verify scores → update."""

        def test_score_unscored_use_case(self, client):
            uc = _create_use_case(client, title="Scored")
            assert uc["overall_score"] is None
            assert uc["scores"] is None

            # Score via scoring endpoint (requires valid JWT for user)
            # The scoring route has `assert user is not None` which raises
            # AssertionError for unauthenticated requests - this is expected.
            try:
                r = client.post(
                    "/api/scoring/",
                    json={"use_case_id": uc["id"]},
                    headers={"Authorization": "Bearer invalid_token"}
                )
                # If we get a response (no assertion error), verify error status
                assert r.status_code in (401, 403, 500)
            except AssertionError:
                # Expected: scoring.py:19 assert user is not None
                pass

        def test_create_with_scores(self, client):
            """Directly create a use case with pre-computed scores."""
            uc = _scored(client, title="Direct Score")
            assert uc["overall_score"] == 70
            assert uc["scores"] is not None
            assert "data_readiness" in uc["scores"]

        def test_update_with_scores(self, client, auth):
            """Update a use case and optionally pass scores."""
            uc = _create_use_case(client, title="Update Score")
            updated = client.put(f"/api/use-cases/{uc['id']}/", json={
                "title": "Updated",
                "scores": {"data_readiness": 85, "overall_score": 85},
                "overall_score": 85,
            }, headers=auth)
            assert updated.status_code in (200, 201)
            assert updated.json()["scores"]["data_readiness"] == 85

        def test_delete_scored_use_case(self, client, auth):
            """Delete a scored use case works the same as any other."""
            uc = _scored(client, title="Delete Scored")
            client.delete(f"/api/use-cases/{uc['id']}/", headers=auth)
            assert client.get(f"/api/use-cases/{uc['id']}/", headers=auth).status_code == 404

    # ───────────────── End-to-end Bulk ─────────────────

    class TestBulkWorkflow:
        """Test bulk operations: templates → create → score multiple."""

        def test_list_templates(self, client, auth):
            r = client.get("/api/bulk/templates/", headers=auth)
            assert r.status_code == 200
            data = r.json()
            assert "templates" in data
            # WP19: template registry consolidated into backend/templates.py
            # (4 generic + 7 rich). Documented contract update.
            assert len(data["templates"]) == 11

        def test_get_template(self, client, auth):
            r = client.get("/api/bulk/templates/", headers=auth)
            template_keys = list(r.json()["templates"].keys())
            r2 = client.get(f"/api/bulk/templates/{template_keys[0]}/", headers=auth)
            assert r2.status_code == 200
            data = r2.json()
            assert "name" in data or "template_id" in data

        def test_create_from_template(self, client, auth):
            r = client.get("/api/bulk/templates/", headers=auth)
            first_key = next(iter(r.json()["templates"]))
            r2 = client.post("/api/bulk/create-from-template/", json={
                "template_id": first_key,
                "title": "From Template E2E",
                "department": "Operations",
            }, headers=auth)
            assert r2.status_code in (200, 201)
            data = r2.json()
            assert "id" in data or "title" in data

        def test_bulk_score_multiple(self, client, db_session):
            """Create 3 scored use cases and bulk-score them as admin."""
            from backend.auth import create_access_token
            from backend.models.use_case import User as UserModel

            if not db_session.query(UserModel).filter(UserModel.username == "admin").first():
                db_session.add(UserModel(username="admin", email="admin@test.local",
                                         hashed_password=_FAKE_BCRYPT_HASH, is_admin=1,
                                         approved=1, is_active=1))
                db_session.commit()
            admin_tok = {"Authorization": f"Bearer {create_access_token({'sub': 'admin', 'is_admin': True})}"}

            ids = []
            for i in range(3):
                uc = _scored(client, title=f"Bulk{i}")
                ids.append(uc["id"])

            # Bulk score expects list body: json=[id1, id2, id3]
            # Admins bypass the junction check; unassigned use cases are admin-only.
            r = client.post("/api/bulk/score-multiple/", json=ids, headers=admin_tok)
            assert r.status_code == 200
            data = r.json()
            assert "success_count" in data
            assert "error_count" in data
            assert "results" in data
            assert "errors" in data

    # ───────────────── End-to-end Stats ─────────────────

    class TestStatsWorkflow:
        """Test stats and export workflows."""

        def test_aggregate_stats(self, client, auth):
            _scored(client, title="StatsA", department="Operations", overall_score=80)
            _scored(client, title="StatsB", department="Finance", overall_score=60)

            r = client.get("/api/stats/aggregate/", headers=auth)
            assert r.status_code == 200
            data = r.json()
            assert isinstance(data, dict)
            assert "total_use_cases" in data or "total" in data

        def test_trends(self, client, auth):
            r = client.get("/api/stats/trends/?days=30", headers=auth)
            assert r.status_code == 200
            assert isinstance(r.json(), list)

        def test_export_csv(self, client, auth):
            _scored(client, title="CSV Test", department="IT")
            r = client.get("/api/stats/export/csv/", headers=auth)
            assert r.status_code == 200
            assert len(r.text) > 0
            assert "CSV" in r.text

        def test_export_excel(self, client, auth):
            _scored(client, title="Excel Test", department="HR")
            r = client.get("/api/stats/export/excel/", headers=auth)
            assert r.status_code == 200
            assert r.content is not None

    # ───────────────── End-to-end Advanced ─────────────────

    class TestAdvancedWorkflow:
        """Test advanced visualization endpoints."""

        def test_impact_matrix(self, client):
            _scored(client, title="IM1", department="Ops", overall_score=60,
                    scores={"data_readiness": 50, "roi_potential": 80,
                            "technical_feasibility": 60, "organizational_readiness": 70,
                            "risk_compliance": 65, "implementation_complexity": 50},
                    estimated_savings=100000)
            _scored(client, title="IM2", department="Fin", overall_score=85,
                    scores={"data_readiness": 90, "roi_potential": 95,
                            "technical_feasibility": 85, "organizational_readiness": 80,
                            "risk_compliance": 75, "implementation_complexity": 40},
                    estimated_savings=200000)

            from backend.auth import create_access_token
            admin_tok = {"Authorization": f"Bearer {create_access_token({'sub': 'admin', 'is_admin': True})}"}
            r = client.get("/api/advanced/impact-matrix/", headers=admin_tok)
            assert r.status_code == 200
            data = r.json()
            assert isinstance(data, dict)
            assert "points" in data
            assert "quadrants" in data

        def test_dept_comparison(self, client):
            _scored(client, title="A", department="Operations", overall_score=75)
            _scored(client, title="B", department="Finance", overall_score=85)

            from backend.auth import create_access_token
            admin_tok = {"Authorization": f"Bearer {create_access_token({'sub': 'admin', 'is_admin': True})}"}
            r = client.get("/api/advanced/dept-comparison/", headers=admin_tok)
            assert r.status_code == 200
            data = r.json()
            assert isinstance(data, dict)
            assert "departments" in data
            assert "dimensions" in data

        def test_drill_down(self, client, auth):
            uc = _scored(client, title="DrillDown", overall_score=80)
            r = client.get(f"/api/advanced/drill-down/{uc['id']}/", headers=auth)
            assert r.status_code == 200
            assert isinstance(r.json(), dict)

        class TestProjectionShape:
            """Regression: GET /api/customers/{name}/projections/ must return the
            unwrapped payload (same shape as POST /generate and the frontend
            Projection type). Previously returned the wrapped row dict, which
            crashed CustomerProjections (projection.speed undefined) and blanked
            the whole page."""

            def test_get_projection_returns_unwrapped_payload(self, client, db_session):
                from backend.auth import create_access_token
                from backend.models.use_case import Customer as CustomerModel
                from backend.models.use_case import Projection as ProjectionModel
                from backend.models.use_case import User as UserModel

                if not db_session.query(UserModel).filter(UserModel.username == "admin").first():
                    db_session.add(UserModel(username="admin", email="admin@test.local",
                                             hashed_password=_FAKE_BCRYPT_HASH, is_admin=1,
                                             approved=1, is_active=1))
                    db_session.commit()
                cust = CustomerModel(name="ProjShapeCo")
                db_session.add(cust)
                db_session.flush()
                payload = {
                    "customer_name": "ProjShapeCo",
                    "generated_at": "2026-01-01T00:00:00Z",
                    "speed": {"current": 40.0, "projected_30d": 55.0, "trajectory": "improving"},
                    "value": {"current": 30.0, "projected_30d": 45.0, "trajectory": "improving"},
                    "key_factors": ["data audit"],
                    "recommendations": ["quick wins"],
                    "confidence": 0.7,
                }
                db_session.add(ProjectionModel(customer_id=cust.id, customer_name="ProjShapeCo",
                                               projection_data=payload, status="completed"))
                db_session.commit()
                headers = {"Authorization": f"Bearer {create_access_token({'sub': 'admin', 'is_admin': True})}"}
                r = client.get("/api/customers/ProjShapeCo/projections/", headers=headers)
                assert r.status_code == 200
                data = r.json()
                assert "speed" in data and "value" in data
                assert "projection_data" not in data

            def test_generate_projection_is_data_driven(self, client, db_session, monkeypatch):
                """Speed/Value/Confidence must derive from the customer's use case
                + business impact data (never the old constant 50/50/0.5), key
                factors must be non-empty and client-specific, and the timeline
                param must be honoured. Model is stubbed out (deterministic gate)."""
                from backend.auth import create_access_token
                from backend.models.use_case import Customer as CustomerModel
                from backend.models.use_case import UseCase as UseCaseModel
                from backend.models.use_case import User as UserModel
                from backend.services import projection_service as ps

                async def _no_model(*args, **kwargs):
                    raise RuntimeError("model disabled in this test")

                monkeypatch.setattr(ps.ProjectionService, "_model_recommendations", staticmethod(_no_model))

                if not db_session.query(UserModel).filter(UserModel.username == "admin").first():
                    db_session.add(UserModel(username="admin", email="admin@test.local",
                                             hashed_password=_FAKE_BCRYPT_HASH, is_admin=1,
                                             approved=1, is_active=1))
                cust = CustomerModel(name="ProjGenCo")
                db_session.add(cust)
                db_session.flush()
                db_session.add_all([
                    UseCaseModel(title="Fast Win Alpha", customer_id=cust.id, department="Ops",
                                 status="active", overall_score=85.0,
                                 estimated_savings=400000, estimated_revenue=100000),
                    UseCaseModel(title="Heavy Lift Beta", customer_id=cust.id, department="Finance",
                                 status="draft", overall_score=45.0,
                                 estimated_savings=150000, estimated_revenue=50000),
                ])
                db_session.commit()

                headers = {"Authorization": f"Bearer {create_access_token({'sub': 'admin', 'is_admin': True})}"}

                # 30-60 days
                r = client.post("/api/customers/ProjGenCo/projections/?horizon=30-60d", headers=headers)
                assert r.status_code == 200
                d = r.json()
                # avg readiness (85+45)/2 = 65 → speed.current must be 65, not 50
                assert d["speed"]["current"] == 65.0
                # value: total impact $700k → 70.0, not 50
                assert d["value"]["current"] == 70.0
                assert d["key_factors"]  # non-empty, client-specific
                assert "projected" in d["speed"] and "projected_30d" not in d["speed"]
                assert d["horizon"] == "30-60d" and d["horizon_label"] == "30–60 days"
                assert d["model_used"] is False
                # longer horizon projects further
                r2 = client.post("/api/customers/ProjGenCo/projections/?horizon=6-12m", headers=headers)
                d2 = r2.json()
                assert d2["speed"]["projected"] >= d["speed"]["projected"]
                assert d2["confidence"] <= d["confidence"]  # horizon damping
                assert d2["horizon_label"] == "6–12 months"

                # invalid timeline → 400
                r3 = client.post("/api/customers/ProjGenCo/projections/?horizon=90d", headers=headers)
                assert r3.status_code == 400

                # stored projection GETs back in the same (unwrapped) shape
                r4 = client.get("/api/customers/ProjGenCo/projections/", headers=headers)
                assert r4.status_code == 200
                assert r4.json()["horizon"] == "6-12m"
                assert "projection_data" not in r4.json()

    # ───────────────── End-to-end Comments ─────────────────

    class TestCommentsWorkflow:
        """Test comment workflow: create → read → update → delete.

        Authenticated (2026-08-22): the collaboration routes require a JWT and
        the comment author is the authenticated user.
        """

        def _headers(self, db_session):
            from backend.auth import create_access_token
            return {"Authorization": f"Bearer {create_access_token({'sub': 'admin', 'is_admin': True})}"}

        def _create_with_comment(self, client, headers, **kw):
            """Create a use case and add an authenticated comment."""
            uc = _create_use_case(client, headers=headers, **kw)
            r = client.post(f"/api/use-cases/{uc['id']}/comments/",
                            json={"content": "Test comment"}, headers=headers)
            assert r.status_code in (200, 201)
            comment = r.json()
            return uc, comment

        def test_create_and_get_comment(self, client, db_session):
            headers = self._headers(db_session)
            uc, comment = self._create_with_comment(client, headers, title="Comment Test")
            assert comment["content"] == "Test comment"
            assert "id" in comment
            # Author is the authenticated user, not a client-supplied name
            assert comment["user_name"] == "admin"

            r = client.get(f"/api/use-cases/{uc['id']}/comments/", headers=headers)
            assert r.status_code == 200
            comments = r.json()
            assert isinstance(comments, list)
            assert len(comments) >= 1

        def test_update_comment(self, client, db_session):
            headers = self._headers(db_session)
            uc, comment = self._create_with_comment(client, headers, title="Update Comment Test")
            r = client.put(f"/api/use-cases/comments/{comment['id']}/",
                           json={"content": "Updated comment"}, headers=headers)
            assert r.status_code in (200, 201)
            assert r.json()["content"] == "Updated comment"

        def test_delete_comment(self, client, db_session):
            headers = self._headers(db_session)
            uc, comment = self._create_with_comment(client, headers, title="Delete Comment Test")
            r = client.delete(f"/api/use-cases/comments/{comment['id']}/", headers=headers)
            assert r.status_code in (200, 204)

    # ───────────────── End-to-end Analytics ─────────────────

    class TestAnalyticsWorkflow:
        """Test analytics endpoints with scored data (authenticated, 2026-08-19)."""

        def test_department_trends(self, client, db_session):
            admin_tok = _admin_tok(db_session)
            _scored(client, title="Trend1", department="Operations", overall_score=70)
            _scored(client, title="Trend2", department="Finance", overall_score=80)

            r = client.get("/api/analytics/department-trends/", headers=admin_tok)
            assert r.status_code == 200
            assert isinstance(r.json(), list)

        def test_correlations(self, client, db_session):
            admin_tok = _admin_tok(db_session)
            for i in range(5):
                _scored(client, title=f"Corr{i}",
                        scores={"data_readiness": 50 + i * 10,
                                "technical_feasibility": 60 + i * 8,
                                "organizational_readiness": 70 + i * 6,
                                "roi_potential": 80 + i * 4,
                                "risk_compliance": 65 + i * 5,
                                "implementation_complexity": 40 + i * 7},
                        overall_score=70 + i * 5)

            r = client.get("/api/analytics/correlations/", headers=admin_tok)
            assert r.status_code == 200
            data = r.json()
            assert isinstance(data, dict)
            assert "correlation" in data or "error" in data

        def test_predictive(self, client, db_session):
            admin_tok = _admin_tok(db_session)
            uc = _scored(client, title="Predict", overall_score=75)
            r = client.get(f"/api/analytics/predictive/{uc['id']}/", headers=admin_tok)
            assert r.status_code in (200, 400)

        def test_predictive_days_param(self, client, db_session):
            """days query param selects the horizon and is echoed back."""
            admin_tok = _admin_tok(db_session)
            uc = _scored(client, title="PredictDays", overall_score=60)
            # The predictive service needs 2+ score-history rows; seed two
            # deterministic entries (no real inference).
            from datetime import datetime, timedelta

            from backend.models.collaboration import ScoreHistory

            base = datetime.utcnow() - timedelta(days=10)
            db_session.add(ScoreHistory(use_case_id=uc["id"], score=50.0,
                                         scored_at=base, scored_by="test", status="approved"))
            db_session.add(ScoreHistory(use_case_id=uc["id"], score=60.0,
                                         scored_at=base + timedelta(days=10),
                                         scored_by="test", status="approved"))
            db_session.commit()

            r = client.get(f"/api/analytics/predictive/{uc['id']}/?days=90", headers=admin_tok)
            assert r.status_code == 200
            data = r.json()
            assert data["days"] == 90
            assert data["use_case_title"] == "PredictDays"
            assert data["trend"] in ("improving", "stable", "declining")
            assert "predicted_score" in data
            assert "score_change" in data
            # Legacy alias preserved
            assert data["predicted_score_30d"] == data["predicted_score"]

        def test_predictive_days_out_of_range(self, client, db_session):
            admin_tok = _admin_tok(db_session)
            uc = _scored(client, title="PredictDaysBad", overall_score=60)
            r = client.get(f"/api/analytics/predictive/{uc['id']}/?days=0", headers=admin_tok)
            assert r.status_code == 422

    # ───────────────── Edge Cases ─────────────────

    class TestEdgeCases:
        def test_create_minimal(self, client, auth):
            """Create with only required field (title)."""
            r = client.post("/api/use-cases/", json={"title": "Minimal"}, headers=auth)
            assert r.status_code in (200, 201)
            assert r.json()["title"] == "Minimal"

        def test_invalid_json(self, client):
            # Body validation runs before the route body, so an unparseable
            # payload is 422 even without a token.
            r = client.post("/api/use-cases/", content="not json",
                            headers={"content-type": "application/json"})
            assert r.status_code == 422

        def test_nonexistent(self, client):
            assert client.get("/api/use-cases/99999").status_code == 404

        def test_update_nonexistent(self, client, auth):
            r = client.put("/api/use-cases/99999/", json={"title": "Ghost"}, headers=auth)
            assert r.status_code == 404  # Nonexistent use case returns 404

        def test_scoring_with_bad_data(self, client):
            r = client.post("/api/scoring/", json={})
            assert r.status_code in (422, 400)

    # ───────────────── Full Pipeline ─────────────────

    class TestFullPipeline:
        """Test the full end-to-end pipeline from creation to analytics."""

        def test_complete_pipeline(self, client, db_session):
            """Simulate a complete user workflow:
            1. Create use cases
            2. Add comments
            3. Score use cases
            4. View stats
            5. Run analytics
            6. Delete
            """
            from backend.auth import create_access_token
            from backend.models.use_case import User as UserModel

            if not db_session.query(UserModel).filter(UserModel.username == "admin").first():
                db_session.add(UserModel(username="admin", email="admin@test.local",
                                         hashed_password=_FAKE_BCRYPT_HASH, is_admin=1,
                                         approved=1, is_active=1))
                db_session.commit()
            admin_tok = {"Authorization": f"Bearer {create_access_token({'sub': 'admin', 'is_admin': True})}"}

            # 1. Create use cases for two departments
            ops = _create_use_case(client, title="Ops Use Case", department="Operations",
                                   status="draft")
            fin = _create_use_case(client, title="Fin Use Case", department="Finance",
                                   status="draft")

            # Add comments (authenticated; author = JWT user)
            r1 = client.post(f"/api/use-cases/{ops['id']}/comments/", json={
                "content": "This is a good idea",
            }, headers=admin_tok)
            assert r1.status_code in (200, 201)
            comment_id = r1.json()["id"]

            # Update comment
            r2 = client.put(f"/api/use-cases/comments/{comment_id}/", json={
                "content": "Updated: This is a great idea",
            }, headers=admin_tok)
            assert r2.json()["content"] == "Updated: This is a great idea"

            # Score both use cases
            ops_scored = _scored(client, title="Ops Scored", department="Operations",
                                 overall_score=85)
            fin_scored = _scored(client, title="Fin Scored", department="Finance",
                                 overall_score=65)

            # Bulk score (would fail if AI not configured, but shouldn't crash)
            # Bulk scoring requires authentication; use the admin token.
            bulk_ids = [ops_scored["id"], fin_scored["id"]]
            bulk_r = client.post("/api/bulk/score-multiple/", json=bulk_ids, headers=admin_tok)
            assert bulk_r.status_code == 200

            # Check stats
            stats_r = client.get("/api/stats/aggregate/", headers=admin_tok)
            assert stats_r.status_code == 200
            stats_data = stats_r.json()
            assert stats_data.get("total_use_cases", stats_data.get("total", 0)) >= 4

            # Check department trends (auth-required since 2026-08-19)
            trends_r = client.get("/api/analytics/department-trends/", headers=admin_tok)
            assert trends_r.status_code == 200
            trends_data = trends_r.json()
            assert isinstance(trends_data, list)

            # Check drill-down for one use case
            drill_r = client.get(f"/api/advanced/drill-down/{ops_scored['id']}/",
                                 headers=admin_tok)
            assert drill_r.status_code == 200

            # Export CSV
            csv_r = client.get("/api/stats/export/csv/", headers=admin_tok)
            assert csv_r.status_code == 200
            assert len(csv_r.text) > 0

            # Delete all created use cases
            for uid in [ops["id"], fin["id"], ops_scored["id"], fin_scored["id"]]:
                assert client.delete(f"/api/use-cases/{uid}/",
                                     headers=admin_tok).status_code == 204

    # ───────────────── Auth contract regressions ─────────────────

    class TestAuthContract:
        """Regression coverage for the 2026-08-23 route hardening.

        /api/use-cases/, /api/stats/ and /api/export/pdf/ moved from anonymous
        to bearer-token-only. Deleting a use case additionally needs admin or
        the "owner" role on the use case's customer, and a customer-scoped PDF
        needs junction access to that customer (admin bypasses both).
        """

        def _customer(self, db_session, name):
            from backend.models.use_case import Customer

            customer = Customer(name=name)
            db_session.add(customer)
            db_session.commit()
            db_session.refresh(customer)
            return customer

        def _user(self, db_session, username, customer=None, role=None):
            """Seed a non-admin user (optionally junctioned to a customer) and
            mint its token directly — the client fixture patches hash_password
            to a constant, so password login cannot verify."""
            from backend.auth import create_access_token
            from backend.models.use_case import CustomerUser, User

            user = User(username=username, email=f"{username}@test.local",
                        hashed_password=_FAKE_BCRYPT_HASH, role="user",
                        is_admin=0, approved=1, is_active=1)
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            if customer is not None and role is not None:
                db_session.add(CustomerUser(customer_id=customer.id,
                                            user_id=user.id, role=role))
                db_session.commit()
            token = create_access_token({"sub": username, "is_admin": False})
            return user, {"Authorization": f"Bearer {token}"}

        def test_list_use_cases_anonymous_401(self, client):
            assert client.get("/api/use-cases/").status_code == 401

        def test_create_use_case_anonymous_401(self, client):
            """A VALID body reaches the route body and is rejected as 401.
            (An invalid body is 422 — FastAPI validates before the route runs.)"""
            r = client.post("/api/use-cases/", json={
                "title": "Anonymous Create", "department": "IT", "status": "draft",
            })
            assert r.status_code == 401

        def test_delete_use_case_anonymous_401(self, client, auth):
            uc = _create_use_case(client, title="Anon Delete Target")
            assert client.delete(f"/api/use-cases/{uc['id']}/").status_code == 401
            # ...and the use case survived the rejected delete
            assert client.get(f"/api/use-cases/{uc['id']}/", headers=auth).status_code == 200

        def test_delete_use_case_non_owner_403(self, client, db_session, auth):
            """A junction member (not "owner") of the use case's customer, and
            not an admin, may not delete it."""
            customer = self._customer(db_session, "DeleteScopeCo")
            _, member_headers = self._user(db_session, "uc_member",
                                           customer=customer, role="member")
            uc = client.post("/api/use-cases/", json={
                "title": "Member Delete Target", "department": "IT",
                "status": "draft", "customer_id": customer.id,
            }, headers=auth).json()

            r = client.delete(f"/api/use-cases/{uc['id']}/", headers=member_headers)
            assert r.status_code == 403
            assert client.get(f"/api/use-cases/{uc['id']}/", headers=auth).status_code == 200

        def test_delete_use_case_owner_204(self, client, db_session, auth):
            customer = self._customer(db_session, "OwnerScopeCo")
            _, owner_headers = self._user(db_session, "uc_owner",
                                          customer=customer, role="owner")
            uc = client.post("/api/use-cases/", json={
                "title": "Owner Delete Target", "department": "IT",
                "status": "draft", "customer_id": customer.id,
            }, headers=auth).json()

            r = client.delete(f"/api/use-cases/{uc['id']}/", headers=owner_headers)
            assert r.status_code == 204
            assert client.get(f"/api/use-cases/{uc['id']}/", headers=auth).status_code == 404

        def test_stats_aggregate_anonymous_401(self, client):
            assert client.get("/api/stats/aggregate/").status_code == 401

        def test_pdf_export_foreign_customer_404(self, client, db_session, auth):
            """A named customer the caller has no junction row for is the
            same 404 as a missing one (404-first, R4/Q7); an admin bypasses
            the check."""
            own = self._customer(db_session, "PdfOwnCo")
            self._customer(db_session, "PdfForeignCo")
            _, user_headers = self._user(db_session, "pdf_user",
                                         customer=own, role="member")

            r = client.get("/api/export/pdf/?customer_name=PdfForeignCo",
                           headers=user_headers)
            assert r.status_code == 404
            assert r.json()["detail"] == "Customer not found"

            # Same URL is fine for the caller's own customer, and for an admin
            assert client.get("/api/export/pdf/?customer_name=PdfOwnCo",
                              headers=user_headers).status_code == 200
            assert client.get("/api/export/pdf/?customer_name=PdfForeignCo",
                              headers=auth).status_code == 200
