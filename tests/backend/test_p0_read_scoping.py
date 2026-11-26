"""P0 read-scoping regressions: customer-scoped reads and writes of use cases,
score history, projections, exports and the scoring health probe.

Matrix (denied = rep/stranger; allowed = scoped rep or system admin):

- GET /api/use-cases/{id}/         out-of-scope → 404 (no existence oracle)
- PUT /api/use-cases/{id}/         customer_id move → 422 (no fixed customer)
- NULL-customer use cases          reads 404, writes 403 for non-admins
- GET /api/scoring/history/{id}/   out-of-scope use case → 404
- GET /api/customers/{n}/projections/  out-of-scope customer → 404
- unscoped exports (pdf/csv/xlsx)  non-admin → 403; admin unchanged
- GET /api/scoring/health/        unauthenticated → 401
"""

import pytest
from backend.auth import create_access_token
from backend.models.collaboration import ScoreHistory
from backend.models.use_case import Customer, CustomerUser, Projection, UseCase, User

_FAKE_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"

UNASSIGNED = "Unassigned use cases are admin-only"
NOT_FOUND_UC = "Use case not found"
NOT_FOUND_CUSTOMER = "Customer not found"
FULL_PORTFOLIO = "Full-portfolio export requires admin"


def _hdr(username: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}


@pytest.fixture()
def seeded(db_session):
    """Two customers, a rep on A, a stranger on neither, an admin, and
    use cases in A, in B, and unassigned. Returns the ids."""
    admin = User(username="p0_admin", email="p0a@test.local", hashed_password=_FAKE_HASH,
                 role="admin", is_admin=1, approved=1, is_active=1)
    rep = User(username="p0_rep", email="p0r@test.local", hashed_password=_FAKE_HASH,
               role="user", is_admin=0, approved=1, is_active=1)
    stranger = User(username="p0_stranger", email="p0s@test.local", hashed_password=_FAKE_HASH,
                    role="user", is_admin=0, approved=1, is_active=1)
    db_session.add_all([admin, rep, stranger])
    db_session.commit()

    cust_a = Customer(name="P0CustA", description="A")
    cust_b = Customer(name="P0CustB", description="B")
    db_session.add_all([cust_a, cust_b])
    db_session.commit()

    db_session.add(CustomerUser(customer_id=cust_a.id, user_id=rep.id, role="member"))
    db_session.commit()

    uc_a = UseCase(title="P0 in A", customer_id=cust_a.id, status="active", created_by="test")
    uc_b = UseCase(title="P0 in B", customer_id=cust_b.id, status="active", created_by="test")
    uc_none = UseCase(title="P0 unassigned", customer_id=None, status="active", created_by="test")
    db_session.add_all([uc_a, uc_b, uc_none])
    db_session.commit()
    for uc in (uc_a, uc_b, uc_none):
        db_session.refresh(uc)

    for uc in (uc_a, uc_b):
        db_session.add(ScoreHistory(use_case_id=uc.id, score=50.0, scored_by="test",
                                    status="approved", dimension_scores={"speed": 50}))
    db_session.add(Projection(customer_id=cust_a.id, customer_name=cust_a.name,
                              projection_data={"customer_name": cust_a.name, "speed": {}},
                              status="completed"))
    db_session.add(Projection(customer_id=cust_b.id, customer_name=cust_b.name,
                              projection_data={"customer_name": cust_b.name, "speed": {}},
                              status="completed"))
    db_session.commit()

    return {
        "cust_a": cust_a.id, "cust_a_name": cust_a.name,
        "cust_b": cust_b.id, "cust_b_name": cust_b.name,
        "uc_a": uc_a.id, "uc_b": uc_b.id, "uc_none": uc_none.id,
    }


# ── by-id read ───────────────────────────────────────────────────────────

class TestUseCaseReadScope:
    def test_rep_reads_in_scope_use_case(self, client, seeded):
        r = client.get(f"/api/use-cases/{seeded['uc_a']}/", headers=_hdr("p0_rep"))
        assert r.status_code == 200
        assert r.json()["id"] == seeded["uc_a"]

    def test_rep_out_of_scope_use_case_is_404(self, client, seeded):
        r = client.get(f"/api/use-cases/{seeded['uc_b']}/", headers=_hdr("p0_rep"))
        assert r.status_code == 404
        assert r.json()["detail"] == NOT_FOUND_UC

    def test_out_of_scope_matches_missing_body(self, client, seeded):
        """No oracle: out-of-scope and absent ids answer identically."""
        out = client.get(f"/api/use-cases/{seeded['uc_b']}/", headers=_hdr("p0_stranger"))
        missing = client.get("/api/use-cases/999999/", headers=_hdr("p0_stranger"))
        assert out.status_code == missing.status_code == 404
        assert out.json() == missing.json()

    def test_admin_reads_any_use_case(self, client, seeded):
        r = client.get(f"/api/use-cases/{seeded['uc_b']}/", headers=_hdr("p0_admin"))
        assert r.status_code == 200


# ── customer cannot be moved ────────────────────────────────────────

class TestUseCaseCustomerImmutable:
    def test_move_to_other_customer_rejected_for_rep(self, client, db_session, seeded):
        r = client.put(f"/api/use-cases/{seeded['uc_a']}/",
                       json={"customer_id": seeded["cust_b"]}, headers=_hdr("p0_rep"))
        assert r.status_code == 422
        assert r.json()["detail"] == "Use case customer cannot be changed."
        db_session.expire_all()
        assert db_session.get(UseCase, seeded["uc_a"]).customer_id == seeded["cust_a"]

    def test_move_rejected_even_for_admin(self, client, db_session, seeded):
        r = client.put(f"/api/use-cases/{seeded['uc_a']}/",
                       json={"customer_id": seeded["cust_b"]}, headers=_hdr("p0_admin"))
        assert r.status_code == 422
        db_session.expire_all()
        assert db_session.get(UseCase, seeded["uc_a"]).customer_id == seeded["cust_a"]

    def test_assign_unassigned_use_case_to_customer_rejected(self, client, db_session, seeded):
        r = client.put(f"/api/use-cases/{seeded['uc_none']}/",
                       json={"customer_id": seeded["cust_a"]}, headers=_hdr("p0_admin"))
        assert r.status_code == 422
        db_session.expire_all()
        assert db_session.get(UseCase, seeded["uc_none"]).customer_id is None

    def test_same_customer_id_edit_still_allowed(self, client, seeded):
        """The edit form always echoes the current customer_id; that is not a move."""
        r = client.put(f"/api/use-cases/{seeded['uc_a']}/",
                       json={"title": "Renamed in A", "customer_id": seeded["cust_a"]},
                       headers=_hdr("p0_rep"))
        assert r.status_code == 200
        assert r.json()["title"] == "Renamed in A"

    def test_service_update_ignores_customer_id(self, db_session, seeded):
        """Defense in depth: a direct service caller cannot move a use case."""
        from backend.services.use_case_service import UseCaseService

        admin = {"username": "p0_admin", "is_admin": 1}
        UseCaseService.update(db_session, seeded["uc_a"], user=admin,
                              customer_id=seeded["cust_b"], title="Still A")
        db_session.expire_all()
        uc = db_session.get(UseCase, seeded["uc_a"])
        assert uc.customer_id == seeded["cust_a"]
        assert uc.title == "Still A"


# ── unassigned (NULL-customer) use cases are admin-only ─────────────

class TestUnassignedUseCasesAdminOnly:
    def test_rep_read_is_404(self, client, seeded):
        r = client.get(f"/api/use-cases/{seeded['uc_none']}/", headers=_hdr("p0_rep"))
        assert r.status_code == 404
        assert r.json()["detail"] == NOT_FOUND_UC

    def test_admin_read_allowed(self, client, seeded):
        r = client.get(f"/api/use-cases/{seeded['uc_none']}/", headers=_hdr("p0_admin"))
        assert r.status_code == 200

    def test_rep_create_unassigned_is_403(self, client, db_session, seeded):
        r = client.post("/api/use-cases/", json={
            "title": "Rep unassigned", "department": "IT", "status": "draft",
        }, headers=_hdr("p0_rep"))
        assert r.status_code == 403
        assert r.json()["detail"] == UNASSIGNED
        assert db_session.query(UseCase).filter(UseCase.title == "Rep unassigned").count() == 0

    def test_admin_create_unassigned_allowed(self, client, seeded):
        r = client.post("/api/use-cases/", json={
            "title": "Admin unassigned", "department": "IT", "status": "draft",
        }, headers=_hdr("p0_admin"))
        assert r.status_code == 201

    def test_rep_update_unassigned_is_403(self, client, db_session, seeded):
        r = client.put(f"/api/use-cases/{seeded['uc_none']}/",
                       json={"title": "Rep edit"}, headers=_hdr("p0_rep"))
        assert r.status_code == 403
        assert r.json()["detail"] == UNASSIGNED
        db_session.expire_all()
        assert db_session.get(UseCase, seeded["uc_none"]).title == "P0 unassigned"

    def test_admin_update_unassigned_allowed(self, client, seeded):
        r = client.put(f"/api/use-cases/{seeded['uc_none']}/",
                       json={"title": "Admin edit"}, headers=_hdr("p0_admin"))
        assert r.status_code == 200
        assert r.json()["title"] == "Admin edit"

    def test_rep_delete_unassigned_is_403(self, client, db_session, seeded):
        r = client.delete(f"/api/use-cases/{seeded['uc_none']}/", headers=_hdr("p0_rep"))
        assert r.status_code == 403
        assert r.json()["detail"] == UNASSIGNED
        assert db_session.get(UseCase, seeded["uc_none"]) is not None

    def test_admin_delete_unassigned_allowed(self, client, seeded):
        r = client.delete(f"/api/use-cases/{seeded['uc_none']}/", headers=_hdr("p0_admin"))
        assert r.status_code == 204

    def test_rep_manual_score_unassigned_is_403(self, client, db_session, seeded):
        r = client.post("/api/scoring/manual/", json={
            "use_case_id": seeded["uc_none"], "scores": {"speed": 50}, "overall_score": 50,
        }, headers=_hdr("p0_rep"))
        assert r.status_code == 403
        assert r.json()["detail"] == UNASSIGNED
        db_session.expire_all()
        assert db_session.get(UseCase, seeded["uc_none"]).overall_score is None

    def test_admin_manual_score_unassigned_allowed(self, client, seeded):
        r = client.post("/api/scoring/manual/", json={
            "use_case_id": seeded["uc_none"], "scores": {"speed": 50}, "overall_score": 50,
        }, headers=_hdr("p0_admin"))
        assert r.status_code == 200

    def test_rep_bulk_create_from_template_unassigned_is_403(self, client, db_session, seeded):
        from backend.templates import TEMPLATES

        template_id = next(iter(TEMPLATES))
        r = client.post("/api/bulk/create-from-template/", json={
            "template_id": template_id, "title": "Rep template", "department": "IT",
        }, headers=_hdr("p0_rep"))
        assert r.status_code == 403
        assert r.json()["detail"] == UNASSIGNED
        assert db_session.query(UseCase).filter(UseCase.title == "Rep template").count() == 0

    def test_rep_drill_down_unassigned_is_404(self, client, seeded):
        r = client.get(f"/api/advanced/drill-down/{seeded['uc_none']}/", headers=_hdr("p0_rep"))
        assert r.status_code == 404

    def test_rep_score_history_unassigned_is_404(self, client, seeded):
        r = client.get(f"/api/scoring/history/{seeded['uc_none']}/", headers=_hdr("p0_rep"))
        assert r.status_code == 404


# ── score history ────────────────────────────────────────────────────────

class TestScoreHistoryScope:
    def test_rep_reads_in_scope_history(self, client, seeded):
        r = client.get(f"/api/scoring/history/{seeded['uc_a']}/", headers=_hdr("p0_rep"))
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_rep_out_of_scope_history_is_404(self, client, seeded):
        r = client.get(f"/api/scoring/history/{seeded['uc_b']}/", headers=_hdr("p0_rep"))
        assert r.status_code == 404
        assert r.json()["detail"] == NOT_FOUND_UC

    def test_missing_history_matches_out_of_scope(self, client, seeded):
        out = client.get(f"/api/scoring/history/{seeded['uc_b']}/", headers=_hdr("p0_rep"))
        missing = client.get("/api/scoring/history/999999/", headers=_hdr("p0_rep"))
        assert out.status_code == missing.status_code == 404
        assert out.json() == missing.json()

    def test_admin_reads_any_history(self, client, seeded):
        r = client.get(f"/api/scoring/history/{seeded['uc_b']}/", headers=_hdr("p0_admin"))
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_anonymous_is_401(self, client, seeded):
        r = client.get(f"/api/scoring/history/{seeded['uc_a']}/")
        assert r.status_code == 401


# ── projections ──────────────────────────────────────────────────────────

class TestProjectionReadScope:
    def test_member_reads_own_customer_projection(self, client, seeded):
        r = client.get(f"/api/customers/{seeded['cust_a_name']}/projections/",
                       headers=_hdr("p0_rep"))
        assert r.status_code == 200
        assert r.json()["customer_name"] == seeded["cust_a_name"]

    def test_out_of_scope_projection_is_404(self, client, seeded):
        r = client.get(f"/api/customers/{seeded['cust_b_name']}/projections/",
                       headers=_hdr("p0_rep"))
        assert r.status_code == 404
        assert r.json()["detail"] == NOT_FOUND_CUSTOMER

    def test_stranger_out_of_scope_matches_missing_customer(self, client, seeded):
        out = client.get(f"/api/customers/{seeded['cust_a_name']}/projections/",
                         headers=_hdr("p0_stranger"))
        missing = client.get("/api/customers/NoSuchCust/projections/",
                             headers=_hdr("p0_stranger"))
        assert out.status_code == missing.status_code == 404
        assert out.json() == missing.json()

    def test_admin_reads_any_projection(self, client, seeded):
        r = client.get(f"/api/customers/{seeded['cust_b_name']}/projections/",
                       headers=_hdr("p0_admin"))
        assert r.status_code == 200


# ── exports ─────────────────────────────────────────────────────────

class TestFullPortfolioExportAdminOnly:
    @pytest.mark.parametrize("path", [
        "/api/export/pdf/",
        "/api/stats/export/csv/",
        "/api/stats/export/excel/",
    ])
    def test_rep_unscoped_export_is_403(self, client, seeded, path):
        r = client.get(path, headers=_hdr("p0_rep"))
        assert r.status_code == 403
        assert r.json()["detail"] == FULL_PORTFOLIO

    def test_empty_id_list_is_still_unscoped(self, client, seeded):
        """``use_case_ids=,`` parses to no IDs: it is the whole portfolio, not a filter."""
        r = client.get("/api/stats/export/csv/?use_case_ids=,", headers=_hdr("p0_rep"))
        assert r.status_code == 403
        assert r.json()["detail"] == FULL_PORTFOLIO

    @pytest.mark.parametrize("path", [
        "/api/export/pdf/",
        "/api/stats/export/csv/",
        "/api/stats/export/excel/",
    ])
    def test_admin_unscoped_export_unchanged(self, client, seeded, path):
        r = client.get(path, headers=_hdr("p0_admin"))
        assert r.status_code == 200

    def test_rep_customer_scoped_exports_unchanged(self, client, seeded):
        name = seeded["cust_a_name"]
        assert client.get(f"/api/export/pdf/?customer_name={name}",
                          headers=_hdr("p0_rep")).status_code == 200
        assert client.get(f"/api/stats/export/csv/?customer_name={name}",
                          headers=_hdr("p0_rep")).status_code == 200
        assert client.get(f"/api/stats/export/excel/?customer_name={name}",
                          headers=_hdr("p0_rep")).status_code == 200


# ── scoring health probe ───────────────────────────────────────────────

class TestScoringHealthAuth:
    def test_anonymous_is_401(self, client):
        r = client.get("/api/scoring/health/")
        assert r.status_code == 401
        assert r.json()["detail"] == "Authentication required"

    def test_authenticated_shape_unchanged(self, client, seeded):
        r = client.get("/api/scoring/health/", headers=_hdr("p0_rep"))
        assert r.status_code == 200
        assert set(r.json()) == {"configured", "endpoint", "model", "dimensions"}
