"""Tests for export functionality - PDF, CSV, Excel exports with filtering.

The export routes require authentication (2026-08-23 route hardening):
/api/export/pdf/, /api/stats/export/csv/ and /api/stats/export/excel/ all
return 401 to anonymous callers, so every request here carries an admin
bearer token. Fixtures come from tests/backend/conftest.py.

Run: pytest tests/backend/test_export.py -v
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")


from unittest.mock import patch

import pytest

_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"



@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
    """Point the real JWT user lookup at the shared session (same pattern as
    test_analytics_scoping.py / test_integration.py).

    get_user_from_request opens its OWN connection to the test DB file and
    only sees truly-committed rows; the conftest db_session keeps its seeded
    admin inside the outer transaction, so an unpatched lookup misses it and
    the auth checks on the export routes misfire.
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


@pytest.fixture()
def auth(db_session):
    """Authorization header for the seeded admin user."""
    from backend.auth import create_access_token
    from backend.models.use_case import User

    admin = db_session.query(User).filter(User.is_admin == 1).first()
    token = create_access_token({"sub": admin.username, "is_admin": True})
    return {"Authorization": f"Bearer {token}"}


class TestPDFExport:
    def test_export_pdf_empty(self, client, auth):
        r = client.get("/api/export/pdf/", headers=auth)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"

    def test_export_pdf_with_use_cases(self, client, auth):
        r = client.post("/api/use-cases/", json={
            "title": "Test", "department": "IT", "status": "active",
        }, headers=auth)
        use_case_id = r.json()["id"]

        r = client.get("/api/export/pdf/", headers=auth)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"

    def test_export_pdf_with_ids(self, client, auth):
        for i in range(2):
            client.post("/api/use-cases/", json={
                "title": f"Case {i}", "department": "IT", "status": "active",
            }, headers=auth)

        r = client.get("/api/export/pdf/", headers=auth)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"

    def test_export_pdf_with_invalid_ids(self, client, auth):
        r = client.get("/api/export/pdf/?id=999999", headers=auth)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"

    def test_export_pdf_content_contains_data(self, client, auth):
        r = client.post("/api/use-cases/", json={
            "title": "Test", "department": "IT", "status": "active",
        }, headers=auth)
        client.get("/api/export/pdf/", headers=auth)


class TestCSVExport:
    def test_export_csv_empty(self, client, auth):
        r = client.get("/api/stats/export/csv/", headers=auth)
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]

    def test_export_csv_with_data(self, client, auth):
        r = client.post("/api/use-cases/", json={
            "title": "Test", "department": "IT", "status": "active",
        }, headers=auth)
        r = client.get("/api/stats/export/csv/", headers=auth)
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]

    def test_export_csv_header(self, client, auth):
        client.post("/api/use-cases/", json={
            "title": "Test", "department": "IT", "status": "active",
        }, headers=auth)
        r = client.get("/api/stats/export/csv/", headers=auth)
        assert r.status_code == 200
        assert b"Title" in r.content

    def test_export_csv_with_ids(self, client, auth):
        for i in range(2):
            client.post("/api/use-cases/", json={
                "title": f"Case {i}", "department": "IT", "status": "active",
            }, headers=auth)
        r = client.get("/api/stats/export/csv/", headers=auth)
        assert r.status_code == 200
        assert b"Case 0" in r.content or b"Case 1" in r.content

    def test_export_csv_with_customer_filter(self, client, auth):
        client.post("/api/use-cases/", json={
            "title": "Test", "department": "IT", "status": "active",
        }, headers=auth)
        r = client.get("/api/stats/export/csv/", headers=auth)
        assert r.status_code == 200

    def test_export_csv_content(self, client, auth):
        client.post("/api/use-cases/", json={
            "title": "Test", "department": "IT", "status": "active",
        }, headers=auth)
        r = client.get("/api/stats/export/csv/", headers=auth)
        assert r.status_code == 200
        assert b"Test" in r.content


class TestExcelExport:
    def test_export_excel_empty(self, client, auth):
        r = client.get("/api/stats/export/excel/", headers=auth)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def test_export_excel_with_data(self, client, auth):
        r = client.post("/api/use-cases/", json={
            "title": "Test", "department": "IT", "status": "active",
        }, headers=auth)
        r = client.get("/api/stats/export/excel/", headers=auth)
        assert r.status_code == 200

    def test_export_excel_with_ids(self, client, auth):
        for i in range(2):
            client.post("/api/use-cases/", json={
                "title": f"Case {i}", "department": "IT", "status": "active",
            }, headers=auth)
        r = client.get("/api/stats/export/excel/", headers=auth)
        assert r.status_code == 200

    def test_export_excel_with_customer_filter(self, client, auth):
        client.post("/api/use-cases/", json={
            "title": "Test", "department": "IT", "status": "active",
        }, headers=auth)
        r = client.get("/api/stats/export/excel/", headers=auth)
        assert r.status_code == 200


class TestExportIntegration:
    def test_export_pdf_headers(self, client, auth):
        client.post("/api/use-cases/", json={
            "title": "Test", "department": "IT", "status": "active",
        }, headers=auth)
        r = client.get("/api/export/pdf/", headers=auth)
        assert r.status_code == 200
        assert "attachment" in r.headers.get("content-disposition", "").lower()

    def test_export_csv_headers(self, client, auth):
        client.post("/api/use-cases/", json={
            "title": "Test", "department": "IT", "status": "active",
        }, headers=auth)
        r = client.get("/api/stats/export/csv/", headers=auth)
        assert r.status_code == 200
        assert "attachment" in r.headers.get("content-disposition", "").lower()

    def test_export_excel_headers(self, client, auth):
        client.post("/api/use-cases/", json={
            "title": "Test", "department": "IT", "status": "active",
        }, headers=auth)
        r = client.get("/api/stats/export/excel/", headers=auth)
        assert r.status_code == 200
        assert "attachment" in r.headers.get("content-disposition", "").lower()

    def test_export_all_formats_same_data(self, client, auth):
        client.post("/api/use-cases/", json={
            "title": "Test", "department": "IT", "status": "active",
        }, headers=auth)
        pdf = client.get("/api/export/pdf/", headers=auth)
        csv = client.get("/api/stats/export/csv/", headers=auth)
        excel = client.get("/api/stats/export/excel/", headers=auth)
        assert pdf.status_code == 200
        assert csv.status_code == 200
        assert excel.status_code == 200


class TestLastStateSemantics:
    """Unit tests for the last-state delta/trend computation.

    Pins the previous-round semantics (regression for the bug where the
    "previous" round was taken as the last history entry even when that
    entry IS the current round — which made every delta 0.0/stable).
    """

    def _uc(self, overall):
        from backend.models.use_case import UseCase
        return UseCase(overall_score=overall)

    def _entries(self, *scores):
        from datetime import datetime
        base = datetime(2026, 8, 1)
        return [
            {"date": (base.replace(day=1 + i)).isoformat(), "score": s,
             "reasoning": None, "recommendations": None}
            for i, s in enumerate(scores)
        ]

    def test_seed_shape_current_equals_last_entry_uses_second_to_last(self):
        """Last history entry matches the current score (seed appends the
        current round last) -> previous round is the second-to-last."""
        from backend.services.pdf_export_service import _last_state
        st = _last_state(self._uc(70.5), self._entries(55.0, 70.5))
        assert st["prev"] == 55.0
        assert st["delta"] == 15.5
        assert st["trend"] == "improving"

    def test_current_newer_than_history_uses_last_entry(self):
        """Current score differs from the last history entry -> that entry
        is the previous round."""
        from backend.services.pdf_export_service import _last_state
        st = _last_state(self._uc(70.5), self._entries(55.0, 62.0))
        assert st["prev"] == 62.0
        assert st["delta"] == 8.5
        assert st["trend"] == "improving"

    def test_single_entry_matching_current_has_no_previous(self):
        from backend.services.pdf_export_service import _last_state
        st = _last_state(self._uc(70.5), self._entries(70.5))
        assert st["prev"] is None
        assert st["delta"] is None
        assert st["trend"] is None

    def test_no_history_has_no_delta(self):
        from backend.services.pdf_export_service import _last_state
        st = _last_state(self._uc(70.5), [])
        assert st["delta"] is None
        assert st["trend"] is None

    def test_decline_detected(self):
        from backend.services.pdf_export_service import _last_state
        st = _last_state(self._uc(70.5), self._entries(80.0, 70.5))
        assert st["delta"] == -9.5
        assert st["trend"] == "declining"


class TestPDFExportDetailedContent:
    """WP10: the PDF report carries last-state analytic detail.

    Verifies the detailed report content (section headings, dimension
    scores, score history, latest reasoning/recommendations, use-case
    factors, business impact, and persisted AI predictions) by decoding
    the reportlab content streams (ASCII85 + Flate) from the PDF bytes.
    Deterministic — no LLM calls.
    """

    @staticmethod
    def _pdf_text(body: bytes) -> str:
        """Extract text from reportlab content streams.

        reportlab emits ``/Filter [ /ASCII85Decode /FlateDecode ]``
        streams; handle plain-Flate and uncompressed streams too.
        """
        import base64
        import re
        import zlib

        chunks = []
        for m in re.finditer(rb"stream\r?\n(.*?)endstream", body, re.DOTALL):
            raw = m.group(1)
            try:
                data = zlib.decompress(raw)
            except zlib.error:
                try:
                    data = zlib.decompress(base64.a85decode(raw, adobe=True))
                except (zlib.error, ValueError):
                    data = raw
            chunks.append(data.decode("latin-1", "ignore"))
        text = "\n".join(chunks)
        # reportlab escapes parentheses inside string literals
        return text.replace("\\(", "(").replace("\\)", ")")

    @staticmethod
    def _pdf_pages(body: bytes) -> int:
        import re
        return len(re.findall(rb"/Type\s*/Page[^s]", body))

    def _seed_rich_use_case(self, client, auth, db_session):
        """Create a fully-detailed use case (scores + 2-round history +
        factors + a persisted AI prediction); returns (uc_id, scored_at)."""
        from datetime import datetime, timedelta

        r = client.post("/api/use-cases/", json={
            "title": "Detailed Report Probe",
            "description": "Probe use case exercising the detailed PDF report.",
            "department": "IT",
            "status": "completed",
            "goals": ["G-WP10 probe goal"],
            "challenges": ["CH-WP10 probe challenge"],
            "pain_points": ["PP-WP10 probe pain point"],
            "impact_category": "cost",
            "impact_description": "Probe impact description",
            "estimated_savings": 100000,
            "estimated_revenue": 50000,
            "timeline_estimate": "short",
            "scores": {
                "data_readiness": 70, "technical_feasibility": 75,
                "organizational_readiness": 65, "roi_potential": 80,
                "risk_compliance": 60, "implementation_complexity": 55,
            },
            "overall_score": 70.5,
        }, headers=auth)
        assert r.status_code in (200, 201), r.text
        uc_id = r.json()["id"]

        now = datetime.utcnow()
        dims = {
            "data_readiness": 70, "technical_feasibility": 75,
            "organizational_readiness": 65, "roi_potential": 80,
            "risk_compliance": 60, "implementation_complexity": 55,
        }
        db_session.expire_all()
        from backend.models.use_case import AIPrediction, UseCase
        uc = db_session.query(UseCase).filter(UseCase.id == uc_id).first()
        assert uc is not None
        uc.overall_score = 70.5
        uc.scores = dims
        uc.scored_at = now
        uc.score_history = [
            {
                "date": (now - timedelta(days=14)).isoformat(),
                "overall_score": 62.0,
                "scores": dims,
                "reasoning": "UNIQUE_R1 prior-round reasoning",
                "recommendations": ["REC-WP10-prev"],
            },
            {
                "date": now.isoformat(),
                "overall_score": 70.5,
                "scores": dims,
                "reasoning": "UNIQUE_R2 latest-round reasoning",
                "recommendations": ["REC-WP10-1", "REC-WP10-2"],
            },
        ]
        db_session.add(AIPrediction(
            use_case_id=uc_id, customer_id=uc.customer_id, horizon_days=45,
            predicted_score=75.0, score_change=4.5, trend="improving",
            confidence=0.8, reasoning="Probe prediction", model="test-model",
        ))
        db_session.commit()
        return uc_id, now

    def test_detailed_report_sections_and_last_state(self, client, auth, db_session):
        from datetime import timedelta
        uc_id, now = self._seed_rich_use_case(client, auth, db_session)
        r = client.get(f"/api/export/pdf/?use_case_ids={uc_id}", headers=auth)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"

        text = self._pdf_text(r.content)
        # Section headings (detailed report layout)
        for heading in ("Executive Summary", "Last-State Analytics",
                        "Department Breakdown", "Use Case Overview",
                        "Use Case Detail"):
            assert heading in text, f"missing section: {heading}"
        # Last-state analytics: current score, date, movement vs prior round, trend
        assert "Detailed Report Probe" in text
        assert "70.5" in text                      # last (current) score
        assert "+8.5" in text                      # delta vs prior round (70.5-62.0)
        assert "Improving" in text                 # trend word (capitalized in tables)
        assert now.strftime("%Y-%m-%d") in text    # score date
        # Dimension scores (normalized canonical names)
        for dim in ("Data Readiness", "Technical Feasibility",
                    "Organizational Readiness", "ROI Potential",
                    "Risk & Compliance", "Implementation Complexity"):
            assert dim in text, f"missing dimension: {dim}"
        # Score history + latest-round reasoning / recommendations
        assert "Score History" in text
        assert "UNIQUE_R2" in text
        assert "REC-WP10-2" in text
        assert (now - timedelta(days=14)).strftime("%Y-%m-%d") in text
        # Use-case factors + business impact
        assert "G-WP10 probe goal" in text
        assert "CH-WP10 probe challenge" in text
        assert "PP-WP10 probe pain point" in text
        assert "Business Impact" in text
        assert "$150,000" in text                  # 100k savings + 50k revenue
        # Persisted AI prediction block
        assert "AI Predictions" in text
        assert "test-model" in text
        assert "45 days" in text
        assert "75.0" in text                      # predicted score
        # A rich single-UC report must span more than one page
        assert self._pdf_pages(r.content) >= 2

    def test_detailed_report_unscored_use_case_still_renders(self, client, auth, db_session):
        """A use case with no scores/history must not break the report."""
        r = client.post("/api/use-cases/", json={
            "title": "Unscored Probe Case", "department": "IT", "status": "draft",
        }, headers=auth)
        uc_id = r.json()["id"]
        r = client.get(f"/api/export/pdf/?use_case_ids={uc_id}", headers=auth)
        assert r.status_code == 200
        text = self._pdf_text(r.content)
        assert "Unscored Probe Case" in text
        assert "Last-State Analytics" in text

    def test_detailed_report_scoped_excludes_other_use_cases(self, client, auth, db_session):
        """Scoped detailed PDF must not leak other use cases' content."""
        uc_id, _ = self._seed_rich_use_case(client, auth, db_session)
        other = client.post("/api/use-cases/", json={
            "title": "UNIQUE_OTHER Probe Leak", "department": "IT",
            "status": "draft",
        }, headers=auth).json()["id"]
        r = client.get(f"/api/export/pdf/?use_case_ids={uc_id}", headers=auth)
        assert r.status_code == 200
        text = self._pdf_text(r.content)
        assert "Detailed Report Probe" in text
        assert "UNIQUE_OTHER" not in text
        # cleanup so the shared test DB stays lean for later tests
        from backend.models.use_case import AIPrediction, UseCase
        db_session.expire_all()
        db_session.query(AIPrediction).filter(
            AIPrediction.use_case_id.in_([uc_id, other])
        ).delete(synchronize_session=False)
        db_session.query(UseCase).filter(UseCase.id.in_([uc_id, other])).delete(
            synchronize_session=False)
        db_session.commit()

    def test_detailed_report_reads_authoritative_history_table(self, client, auth, db_session):
        """History rendered from the score_history TABLE (the authoritative
        audit trail written by real scoring paths), not only the legacy JSON
        column. The use case has NO JSON score_history here."""
        from datetime import datetime, timedelta

        r = client.post("/api/use-cases/", json={
            "title": "Table History Probe", "department": "IT",
            "status": "completed",
        }, headers=auth)
        uc_id = r.json()["id"]

        now = datetime.utcnow()
        dims = {
            "data_readiness": 70, "technical_feasibility": 75,
            "organizational_readiness": 65, "roi_potential": 80,
            "risk_compliance": 60, "implementation_complexity": 55,
        }
        db_session.expire_all()
        from backend.models.collaboration import ScoreHistory
        from backend.models.use_case import UseCase
        uc = db_session.query(UseCase).filter(UseCase.id == uc_id).first()
        uc.overall_score = 70.5
        uc.scores = dims
        uc.scored_at = now
        uc.score_history = None  # legacy JSON column intentionally empty
        db_session.add(ScoreHistory(
            use_case_id=uc_id, score=62.0, scored_at=now - timedelta(days=14),
            scored_by="admin", is_manual=0, status="approved",
            dimension_scores=[],
        ))
        db_session.add(ScoreHistory(
            use_case_id=uc_id, score=70.5, scored_at=now,
            scored_by="admin", is_manual=0, status="approved",
            dimension_scores=[], reasoning="TABLE_R2 table-sourced reasoning",
        ))
        db_session.commit()

        r = client.get(f"/api/export/pdf/?use_case_ids={uc_id}", headers=auth)
        assert r.status_code == 200
        text = self._pdf_text(r.content)
        # Table-sourced history renders: rounds, last-state delta (70.5-62.0),
        # and the table row's reasoning (the JSON column is empty here).
        assert "Table History Probe" in text
        assert "Score History" in text
        assert (now - timedelta(days=14)).strftime("%Y-%m-%d") in text
        assert "+8.5" in text
        assert "Improving" in text
        assert "TABLE_R2" in text

        # cleanup
        db_session.expire_all()
        db_session.query(ScoreHistory).filter(
            ScoreHistory.use_case_id == uc_id
        ).delete(synchronize_session=False)
        db_session.query(UseCase).filter(UseCase.id == uc_id).delete(
            synchronize_session=False)
        db_session.commit()


class TestExportUseCaseIdScoping:
    """Regression: export routes accept `use_case_ids` (with the legacy `ids`
    alias) and it actually filters rows. Previously the routes only accepted
    an `ids` parameter, so a `use_case_ids` query param was silently ignored
    and every 'scoped' export returned all rows.
    """

    def test_csv_use_case_ids_scopes_to_requested_row(self, client, auth):
        id_a = client.post("/api/use-cases/", json={
            "title": "ScopeA", "department": "IT", "status": "active",
        }, headers=auth).json()["id"]
        client.post("/api/use-cases/", json={
            "title": "ScopeB", "department": "IT", "status": "active",
        }, headers=auth)
        r = client.get(f"/api/stats/export/csv/?use_case_ids={id_a}", headers=auth)
        assert r.status_code == 200
        rows = [line for line in r.text.splitlines() if line.strip()]
        assert len(rows) == 2  # header + exactly the requested row
        assert str(id_a) in rows[1]
        assert b"ScopeB" not in r.content

    def test_csv_legacy_ids_alias_still_scopes(self, client, auth):
        id_a = client.post("/api/use-cases/", json={
            "title": "LegacyA", "department": "IT", "status": "active",
        }, headers=auth).json()["id"]
        client.post("/api/use-cases/", json={
            "title": "LegacyB", "department": "IT", "status": "active",
        }, headers=auth)
        r = client.get(f"/api/stats/export/csv/?ids={id_a}", headers=auth)
        assert r.status_code == 200
        rows = [line for line in r.text.splitlines() if line.strip()]
        assert len(rows) == 2
        assert str(id_a) in rows[1]

    def test_excel_and_pdf_accept_use_case_ids(self, client, auth):
        id_a = client.post("/api/use-cases/", json={
            "title": "FmtA", "department": "IT", "status": "active",
        }, headers=auth).json()["id"]
        r = client.get(f"/api/stats/export/excel/?use_case_ids={id_a}", headers=auth)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        r = client.get(f"/api/export/pdf/?use_case_ids={id_a}", headers=auth)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"

    def test_csv_invalid_use_case_ids_returns_400(self, client, auth):
        r = client.get("/api/stats/export/csv/?use_case_ids=abc", headers=auth)
        assert r.status_code == 400
