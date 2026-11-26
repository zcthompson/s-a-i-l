"""Tests for assessment-scoped report exports (PDF/CSV/Excel).

The export routes (``/api/export/pdf/``, ``/api/stats/export/csv/``,
``/api/stats/export/excel/``) accept ``assessment_id`` to export exactly
one customer assessment round — active or archived (archived rounds are
read-only but remain exportable). Regression coverage:

- scoping: an assessment export contains only that round's use cases;
- access: foreign assessments are denied (403), unknown 404, customer
  mismatch 400, anonymous 401;
- Excel internal consistency: the breakdown sheets (Department Breakdown,
  Status Distribution, Top Use Cases, Impact Summary) are computed from
  the same scoped query set as the Use Cases sheet (previously they were
  computed on unfiltered global queries, so a scoped report mixed in
  global rows).

Data is seeded through the real routes (admin) so assessment rounds are
created via the established lifecycle (auto-create active round on first
use case; archive; new round on next use case).

Run: pytest tests/backend/test_assessment_export.py -v
"""

import io
import os
import uuid

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

from unittest.mock import patch

import pytest
from openpyxl import load_workbook

_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"



@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
    """Point the real JWT user lookup at the shared session (same pattern
    as test_export.py / test_analytics_scoping.py)."""
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
def admin_auth(db_session):
    """Authorization header for the seeded admin user."""
    from backend.auth import create_access_token
    from backend.models.use_case import User

    admin = db_session.query(User).filter(User.is_admin == 1).first()
    token = create_access_token({"sub": admin.username, "is_admin": True})
    return {"Authorization": f"Bearer {token}"}


def _member_token(db_session, username):
    """Seed a non-admin user and return its auth headers."""
    from backend.auth import create_access_token
    from backend.models.use_case import User

    existing = db_session.query(User).filter(User.username == username).first()
    if not existing:
        db_session.add(User(username=username, email=f"{username}@test.local",
                            hashed_password=_FAKE_BCRYPT_HASH,
                            display_name="Member", department="IT",
                            is_admin=0, role="member", approved=1, is_active=1))
        db_session.commit()
    token = create_access_token({"sub": username, "is_admin": False})
    return {"Authorization": f"Bearer {token}"}


def _build_two_rounds(client, auth, customer_name):
    """Create a customer with an archived round (1 UC) and an active round (1 UC).

    Returns (customer_id, active_assessment_id, archived_assessment_id,
    {\"archived\": uc_id, \"active\": uc_id}).
    """
    r = client.post("/api/customers/",
                    json={"name": customer_name, "description": "export test"},
                    headers=auth)
    assert r.status_code == 201, r.text
    customer_id = r.json()["id"]

    r = client.post("/api/use-cases/", json={
        "title": f"{customer_name} Round1 UC", "department": "IT",
        "status": "active", "customer_id": customer_id,
        "overall_score": 70.0, "estimated_savings": 1000.0,
        "estimated_revenue": 2000.0,
    }, headers=auth)
    assert r.status_code == 201, r.text
    uc_round1 = r.json()["id"]

    r = client.get(f"/api/customers/{customer_name}/assessments/", headers=auth)
    assert r.status_code == 200, r.text
    rounds = r.json()
    assert len(rounds) == 1 and rounds[0]["status"] == "active"
    round1_id = rounds[0]["id"]

    r = client.post(f"/api/customers/{customer_name}/assessments/{round1_id}/archive/",
                    headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "archived"

    r = client.post("/api/use-cases/", json={
        "title": f"{customer_name} Round2 UC", "department": "HR",
        "status": "active", "customer_id": customer_id,
        "overall_score": 55.0, "estimated_savings": 500.0,
        "estimated_revenue": 500.0,
    }, headers=auth)
    assert r.status_code == 201, r.text
    uc_round2 = r.json()["id"]

    r = client.get(f"/api/customers/{customer_name}/assessments/", headers=auth)
    assert r.status_code == 200, r.text
    rounds = r.json()
    active = [x for x in rounds if x["status"] == "active"]
    archived = [x for x in rounds if x["status"] == "archived"]
    assert len(active) == 1 and len(archived) == 1
    return customer_id, active[0]["id"], archived[0]["id"], {
        "archived": uc_round1, "active": uc_round2,
    }


def _csv_rows(text):
    return [line for line in text.splitlines() if line.strip()]


class TestAssessmentScopedExport:
    def test_csv_scopes_to_archived_assessment(self, client, admin_auth):
        name = f"AssessCsvArch{uuid.uuid4().hex[:8]}"
        _, active_id, archived_id, ucs = _build_two_rounds(client, admin_auth, name)

        r = client.get(f"/api/stats/export/csv/?assessment_id={archived_id}",
                       headers=admin_auth)
        assert r.status_code == 200
        rows = _csv_rows(r.text)
        assert len(rows) == 2  # header + exactly the archived round's UC
        assert str(ucs["archived"]) in rows[1]
        assert f"{name} Round2 UC" not in r.text
        # scoped attachment filename carries the customer slug
        assert "assessment_report" in r.headers["content-disposition"]
        assert name.lower().replace(" ", "_") in r.headers["content-disposition"]

    def test_csv_scopes_to_active_assessment(self, client, admin_auth):
        name = f"AssessCsvAct{uuid.uuid4().hex[:8]}"
        _, active_id, archived_id, ucs = _build_two_rounds(client, admin_auth, name)

        r = client.get(f"/api/stats/export/csv/?assessment_id={active_id}",
                       headers=admin_auth)
        assert r.status_code == 200
        rows = _csv_rows(r.text)
        assert len(rows) == 2
        assert str(ucs["active"]) in rows[1]
        assert f"{name} Round1 UC" not in r.text

    def test_csv_assessment_with_explicit_ids_intersects(self, client, admin_auth):
        name = f"AssessCsvInt{uuid.uuid4().hex[:8]}"
        _, active_id, archived_id, ucs = _build_two_rounds(client, admin_auth, name)

        # Explicit IDs outside the assessment scope are dropped.
        r = client.get(
            f"/api/stats/export/csv/?assessment_id={archived_id}&use_case_ids={ucs['active']}",
            headers=admin_auth)
        assert r.status_code == 200
        rows = _csv_rows(r.text)
        assert len(rows) == 1  # header only — the UC does not belong to the round

        # IDs inside the round are kept.
        r = client.get(
            f"/api/stats/export/csv/?assessment_id={archived_id}&use_case_ids={ucs['archived']}",
            headers=admin_auth)
        assert r.status_code == 200
        rows = _csv_rows(r.text)
        assert len(rows) == 2
        assert str(ucs["archived"]) in rows[1]

    def test_pdf_assessment_report(self, client, admin_auth):
        name = f"AssessPdf{uuid.uuid4().hex[:8]}"
        _, active_id, archived_id, ucs = _build_two_rounds(client, admin_auth, name)

        r = client.get(f"/api/export/pdf/?assessment_id={archived_id}", headers=admin_auth)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 2000
        assert "assessment_report" in r.headers["content-disposition"]

    def test_excel_assessment_report_sheets_scoped(self, client, admin_auth):
        name = f"AssessXls{uuid.uuid4().hex[:8]}"
        _, active_id, archived_id, ucs = _build_two_rounds(client, admin_auth, name)

        r = client.get(f"/api/stats/export/excel/?assessment_id={archived_id}",
                       headers=admin_auth)
        assert r.status_code == 200
        wb = load_workbook(io.BytesIO(r.content))
        assert wb.sheetnames == ["Use Cases", "Department Breakdown",
                                 "Status Distribution", "Top Use Cases",
                                 "Impact Summary"]

        # Use Cases sheet: exactly the archived round's UC (data starts row 4)
        ws = wb["Use Cases"]
        data_rows = [row for row in ws.iter_rows(min_row=4, values_only=True)
                     if row[0] is not None]
        assert len(data_rows) == 1
        assert data_rows[0][0] == ucs["archived"]

        # Department Breakdown sheet: only the scoped department (IT),
        # never global departments from other customers.
        ws2 = wb["Department Breakdown"]
        depts = [row[0] for row in ws2.iter_rows(min_row=4, values_only=True)
                 if row[0] is not None]
        assert depts == ["IT"]

        # Impact Summary sheet: totals reflect the scoped set only.
        ws5 = wb["Impact Summary"]
        metrics = {row[0]: row[1] for row in ws5.iter_rows(min_row=4, values_only=True)
                   if row[0] is not None}
        assert metrics["Total Use Cases"] == 1
        assert metrics["Total Savings"] == 1000.0
        assert metrics["Total Revenue"] == 2000.0

    def test_excel_unscoped_global_report_internally_consistent(self, client, admin_auth):
        """Global export (no scope): breakdown sheets must cover exactly the
        same rows as the Use Cases sheet (they are computed from one
        scoped query set)."""
        name = f"AssessGlb{uuid.uuid4().hex[:8]}"
        _, active_id, archived_id, ucs = _build_two_rounds(client, admin_auth, name)

        r = client.get("/api/stats/export/excel/", headers=admin_auth)
        assert r.status_code == 200
        wb = load_workbook(io.BytesIO(r.content))
        ws = wb["Use Cases"]
        use_case_rows = [row for row in ws.iter_rows(min_row=4, values_only=True)
                         if row[0] is not None]

        ws5 = wb["Impact Summary"]
        metrics = {row[0]: row[1] for row in ws5.iter_rows(min_row=4, values_only=True)
                   if row[0] is not None}
        assert metrics["Total Use Cases"] == len(use_case_rows)

        ws2 = wb["Department Breakdown"]
        dept_counts = [row[1] for row in ws2.iter_rows(min_row=4, values_only=True)
                       if row[0] is not None]
        assert sum(int(c) for c in dept_counts) == len(use_case_rows)


class TestAssessmentExportAccess:
    def test_foreign_assessment_404(self, client, admin_auth, db_session):
        name = f"AssessLk3{uuid.uuid4().hex[:8]}"
        _, active_id, archived_id, _ = _build_two_rounds(client, admin_auth, name)
        headers = _member_token(db_session, "export_stranger")

        r = client.get(f"/api/stats/export/csv/?assessment_id={archived_id}",
                       headers=headers)
        # 404-first (R4/Q7): a foreign assessment is the same 404 as a missing one.
        assert r.status_code == 404
        assert r.json()["detail"] == "Assessment not found"

    def test_junction_member_allowed_200(self, client, admin_auth, db_session):
        from backend.models.use_case import CustomerUser, User

        name = f"AssessLkOk{uuid.uuid4().hex[:8]}"
        customer_id, active_id, archived_id, _ = _build_two_rounds(
            client, admin_auth, name)

        member = (
            db_session.query(User)
            .filter(User.username == "export_member_ok")
            .first()
        )
        if not member:
            member = User(username="export_member_ok",
                          email="export_member_ok@test.local",
                          hashed_password=_FAKE_BCRYPT_HASH,
                          display_name="Member", department="IT",
                          is_admin=0, role="member", approved=1, is_active=1)
            db_session.add(member)
            db_session.commit()
        # Junction row must be visible to the route's own session: with the
        # engine-bound conftest fixture session, db_session.commit() is a
        # real DBAPI COMMIT (no connection().commit() needed — see
        # test_collaboration_auth._seed note).
        if not db_session.query(CustomerUser).filter(
                CustomerUser.customer_id == customer_id,
                CustomerUser.user_id == member.id).first():
            db_session.add(CustomerUser(customer_id=customer_id,
                                        user_id=member.id, role="owner"))
            db_session.commit()

        token_headers = _member_token(db_session, "export_member_ok")
        r = client.get(f"/api/stats/export/csv/?assessment_id={archived_id}",
                       headers=token_headers)
        assert r.status_code == 200

    def test_unknown_assessment_404(self, client, admin_auth):
        r = client.get("/api/stats/export/csv/?assessment_id=999999",
                       headers=admin_auth)
        assert r.status_code == 404

    def test_assessment_customer_mismatch_400(self, client, admin_auth):
        name = f"AssessMis{uuid.uuid4().hex[:8]}"
        other = f"AssessMisOther{uuid.uuid4().hex[:8]}"
        _, active_id, archived_id, _ = _build_two_rounds(client, admin_auth, name)
        r = client.post("/api/customers/", json={"name": other}, headers=admin_auth)
        assert r.status_code == 201

        r = client.get(
            f"/api/stats/export/csv/?assessment_id={archived_id}&customer_name={other}",
            headers=admin_auth)
        assert r.status_code == 400

    def test_unknown_customer_name_404(self, client, admin_auth):
        r = client.get("/api/stats/export/csv/?customer_name=NoSuchCustomerXyz",
                       headers=admin_auth)
        assert r.status_code == 404

    def test_anonymous_export_401(self, client):
        r = client.get("/api/stats/export/csv/?assessment_id=1")
        assert r.status_code == 401
        r = client.get("/api/export/pdf/?assessment_id=1")
        assert r.status_code == 401
        r = client.get("/api/stats/export/excel/?assessment_id=1")
        assert r.status_code == 401
