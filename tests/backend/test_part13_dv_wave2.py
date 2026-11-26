"""Part 13 DV wave — W2 pins: central-policy basis for cross-account read
surfaces and import reads (DV4 / DV11 route reads / DV12).

Every surface here moved from a legacy junction check to the central
``sales_access`` basis (operator ruling R1):

- S7 sales evaluations / departments / analytics / advanced / technology
  inventory + dependencies → ``can(CAP_READ, customer_id)`` per customer
  (404-first kept, byte-identical to a missing record) and
  ``customer_scope`` for the unscoped analytics / advanced aggregates;
- S7 sales section → ``can(CAP_READ)`` with the documented 403-first
  ordering kept (BE-04, ruling F3);
- S8 RVTools route reads (list / detail / customer dashboard) →
  ``customer_scope`` (admin → all; ruling C2.6); the manager route gate is
  unchanged (ruling C2.5);
- S9 pipeline import detail → ``customer_scope`` (admin → all); the F12
  totals cover exactly that scope.

Run: pytest tests/backend/test_part13_dv_wave2.py -v
"""

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from tests.backend.common import _mk_user

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

NOT_AUTHORIZED_TO_MODIFY = "Not authorized to modify this customer"
SCOPE_FAMILIES = ("sales_reporting", "inside_sales_assignments", "sales_ops_assignments",
                  "account_memberships")
READERS = ["w2_sm", "w2_rep", "w2_aud", "w2_sad", "w2_jaud", "w2_ops", "admin"]


def _token(username: str) -> dict:
    from backend.auth import create_access_token
    token = create_access_token({"sub": username, "is_admin": username == "admin"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def world(db_session):
    """TeamCo: owned by w2_rep (reports to w2_sm); w2_jaud holds an auditor
    junction only; w2_ops holds a sales-ops assignment. InsideCo: legacy
    inside-sales assignment for w2_is. OtherCo: owned by w2_out (the
    outsider for TeamCo). w2_sm2 is a sales_manager with no team."""
    from backend.models.customer_technology import CustomerTechnology
    from backend.models.sales_access import (
        InsideSalesAssignment,
        SalesOpsAssignment,
        SalesReporting,
    )
    from backend.models.sales_evaluation import SalesEvaluation
    from backend.models.technology_dependency import TechnologyDependency
    from backend.models.use_case import Customer, CustomerUser, Department, UseCase

    team, inside, other = Customer(name="W2TeamCo"), Customer(name="W2InsideCo"), Customer(name="W2OtherCo")
    db_session.add_all([team, inside, other])
    db_session.flush()
    rep = _mk_user(db_session, "w2_rep", "rep")
    sm = _mk_user(db_session, "w2_sm", "sales_manager")
    _mk_user(db_session, "w2_sm2", "sales_manager")
    isales = _mk_user(db_session, "w2_is", "inside_sales")
    ops = _mk_user(db_session, "w2_ops", "sales_ops")
    _mk_user(db_session, "w2_aud", "auditor")
    _mk_user(db_session, "w2_sad", "sales_admin")
    out = _mk_user(db_session, "w2_out", "rep")
    jaud = _mk_user(db_session, "w2_jaud")  # auditor JUNCTION only: in scope, no write
    db_session.add_all([
        CustomerUser(customer_id=team.id, user_id=rep.id, role="owner"),
        CustomerUser(customer_id=other.id, user_id=out.id, role="owner"),
        CustomerUser(customer_id=team.id, user_id=jaud.id, role="auditor"),
        SalesReporting(rep_user_id=rep.id, manager_user_id=sm.id),
        InsideSalesAssignment(customer_id=inside.id, inside_sales_user_id=isales.id),
        SalesOpsAssignment(customer_id=team.id, user_id=ops.id),
    ])
    db_session.flush()
    dept = Department(name="W2Eng", customer_id=team.id)
    evaluation = SalesEvaluation(customer_id=team.id, evaluation_name="W2 eval", status="draft")
    tech_a = CustomerTechnology(customer_id=team.id, name="RHEL", category="operating_system")
    tech_b = CustomerTechnology(customer_id=team.id, name="OpenShift", category="container_platform")
    db_session.add_all([dept, evaluation, tech_a, tech_b])
    db_session.flush()
    dep = TechnologyDependency(customer_id=team.id, source_id=tech_a.id, target_id=tech_b.id,
                               relationship_type="runs_on")
    uc_team = UseCase(title="W2 team UC", customer_id=team.id, department="Eng",
                      status="active", created_by="w2_rep")
    uc_none = UseCase(title="W2 unassigned UC", customer_id=None, department="Eng",
                      status="active", created_by="seed")
    db_session.add_all([dep, uc_team, uc_none])
    db_session.commit()
    return {
        "team": team.id, "team_name": team.name, "inside": inside.id,
        "inside_name": inside.name, "other": other.id, "other_name": other.name,
        "dept": dept.id,
        "evaluation": evaluation.id, "tech": tech_a.id, "dep": dep.id,
        "uc_team": uc_team.id, "uc_none": uc_none.id,
    }


def _same_404(client, username, url, missing_url, method="get", **kwargs):
    """Out of scope == missing: the same 404 status and byte-identical body."""
    h = _token(username)
    out = getattr(client, method)(url, headers=h, **kwargs)
    miss = getattr(client, method)(missing_url, headers=h, **kwargs)
    assert out.status_code == miss.status_code == 404, (out.status_code, out.text[:160])
    assert out.json() == miss.json()


def _count_families(db_session, call):
    engine = db_session.get_bind()
    engine = getattr(engine, "engine", engine)
    statements: list = []

    def rec(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", rec)
    try:
        response = call()
    finally:
        event.remove(engine, "before_cursor_execute", rec)
    assert response.status_code == 200, response.text
    return {f: sum(1 for s in statements if f in s) for f in SCOPE_FAMILIES}


def _grow_team(db_session, n: int, per_customer=None) -> None:
    """Add ``n`` more team accounts owned by w2_rep (row-scale axis, the
    W1/H2 pin pattern); ``per_customer(customer_id)`` seeds surface rows."""
    from backend.models.use_case import Customer, CustomerUser, User

    rep_id = db_session.query(User.id).filter(User.username == "w2_rep").scalar()
    for i in range(n):
        c = Customer(name=f"W2Scale{i}")
        db_session.add(c)
        db_session.flush()
        db_session.add(CustomerUser(customer_id=c.id, user_id=rep_id, role="owner"))
        if per_customer is not None:
            per_customer(c.id)
    db_session.commit()


# ── S7 sales evaluations ────────────────────────────────────────────────


@pytest.mark.parametrize("user", READERS)
def test_s7_sales_evaluations_read_central(client, world, user):
    r = client.get(f"/api/sales-evaluations/?customer_id={world['team']}", headers=_token(user))
    assert r.status_code == 200, r.text
    assert [e["id"] for e in r.json()] == [world["evaluation"]]
    r = client.get(f"/api/sales-evaluations/{world['evaluation']}", headers=_token(user))
    assert r.status_code == 200, r.text


def test_s7_sales_evaluations_inside_sales_and_outsider_404_first(client, world):
    r = client.get(f"/api/sales-evaluations/?customer_id={world['inside']}", headers=_token("w2_is"))
    assert r.status_code == 200 and r.json() == []
    for user in ("w2_out", "w2_is", "w2_sm2"):
        _same_404(client, user, f"/api/sales-evaluations/?customer_id={world['team']}",
                  "/api/sales-evaluations/?customer_id=999999")
        _same_404(client, user, f"/api/sales-evaluations/{world['evaluation']}",
                  "/api/sales-evaluations/999999")


def test_s7_sales_evaluations_write_stays_edit_gated(client, world):
    # A read grant is not a write grant: junction auditor + sales_ops 403.
    for user in ("w2_jaud", "w2_ops"):
        r = client.put(f"/api/sales-evaluations/{world['evaluation']}",
                       json={"status": "final"}, headers=_token(user))
        assert r.status_code == 403 and r.json()["detail"] == NOT_AUTHORIZED_TO_MODIFY
    r = client.put(f"/api/sales-evaluations/{world['evaluation']}",
                   json={"evaluation_name": "W2 eval (SM)"}, headers=_token("w2_sm"))
    assert r.status_code == 200, r.text


# ── S7 sales section (403-first kept, ruling F3) ────────────────────────


@pytest.mark.parametrize("user", READERS)
def test_s7_sales_section_read_central(client, world, user):
    for leaf in ("knowledge", "readiness", "usecases"):
        r = client.get(f"/api/sales/customers/{world['team']}/{leaf}", headers=_token(user))
        assert r.status_code == 200, (leaf, r.text)


def test_s7_sales_section_403_first_kept(client, world):
    r = client.get(f"/api/sales/customers/{world['inside']}/knowledge", headers=_token("w2_is"))
    assert r.status_code == 200
    for user in ("w2_out", "w2_is", "w2_sm2"):
        for cid in (world["team"], 999999):  # out of scope AND missing: 403 first
            r = client.get(f"/api/sales/customers/{cid}/knowledge", headers=_token(user))
            assert r.status_code == 403
            assert r.json() == {"detail": "Not authorized for this customer"}
    # reads-all roles pass the gate, so a missing customer is the BE-04 404
    r = client.get("/api/sales/customers/999999/knowledge", headers=_token("w2_aud"))
    assert r.status_code == 404 and r.json() == {"detail": "Customer not found"}


# ── S7 departments ──────────────────────────────────────────────────────


@pytest.mark.parametrize("user", READERS)
def test_s7_departments_read_central(client, world, user):
    r = client.get(f"/api/departments/?customer_name={world['team_name']}", headers=_token(user))
    assert r.status_code == 200 and [d["id"] for d in r.json()] == [world["dept"]]
    r = client.get(f"/api/departments/{world['dept']}/", headers=_token(user))
    assert r.status_code == 200, r.text


def test_s7_departments_outsider_404_first(client, world):
    for user in ("w2_out", "w2_is", "w2_sm2"):
        _same_404(client, user, f"/api/departments/?customer_name={world['team_name']}",
                  "/api/departments/?customer_name=NoSuchW2")
        _same_404(client, user, f"/api/departments/{world['dept']}/", "/api/departments/999999/")


# ── S7 analytics (caller-based central READ, ruling C1) ─────────────────


@pytest.mark.parametrize("user", READERS)
def test_s7_analytics_explicit_customer_read_central(client, world, user):
    for path in ("department-trends", "correlations"):
        r = client.get(f"/api/analytics/{path}/?customer_id={world['team']}", headers=_token(user))
        assert r.status_code == 200, (path, r.text)
    r = client.get(f"/api/analytics/readiness-insight/?customer_id={world['team']}", headers=_token(user))
    assert r.status_code == 200, r.text


def test_s7_analytics_outsider_404_first(client, world):
    for user in ("w2_out", "w2_is", "w2_sm2"):
        _same_404(client, user, f"/api/analytics/department-trends/?customer_id={world['team']}",
                  "/api/analytics/department-trends/?customer_id=999999")
        _same_404(client, user, f"/api/analytics/readiness-insight/?customer_id={world['team']}",
                  "/api/analytics/readiness-insight/?customer_id=999999")
        _same_404(client, user, f"/api/analytics/predictive/{world['uc_team']}/",
                  "/api/analytics/predictive/999999/")


def test_s7_analytics_unscoped_uses_customer_scope(client, world):
    from backend.services.analytics_service import AnalyticsService

    seen = []
    real = AnalyticsService.get_department_trends

    def spy(db, **kwargs):
        seen.append(kwargs)
        return real(db, **kwargs)

    with patch.object(AnalyticsService, "get_department_trends", side_effect=spy):
        for user in ("w2_sm", "w2_is", "w2_rep", "w2_out", "w2_sm2", "w2_ops", "admin"):
            assert client.get("/api/analytics/department-trends/", headers=_token(user)).status_code == 200
        client.get("/api/analytics/department-trends/", headers=_token("w2_aud"))
    sm, isales, rep, out, sm2, ops, admin, aud = seen
    assert sm == {"customer_ids": [world["team"]]}          # team scope (was: nothing)
    assert isales == {"customer_ids": [world["inside"]]}    # assignment (was: nothing)
    assert rep == {"customer_ids": [world["team"]]}         # owner unchanged
    assert out == {"customer_ids": [world["other"]]}        # no leak
    assert sm2 == {"customer_ids": []}                      # empty scope = no data
    assert ops == {"customer_ids": [world["team"]]}         # sales-ops assignment
    assert admin == {}                                      # admin unrestricted (G5)
    assert {world["team"], world["inside"], world["other"]} <= set(aud["customer_ids"])


def test_s7_analytics_predictive_unassigned_g6(client, world):
    """G6/F5: unassigned use case = ``can(CAP_READ, None)`` → admin only.
    Delta vs the old ``is_admin`` rule: none (same 403, same message)."""
    for user in ("w2_sm", "w2_rep", "w2_aud", "w2_sad", "w2_is", "w2_out"):
        r = client.get(f"/api/analytics/predictive/{world['uc_none']}/", headers=_token(user))
        assert r.status_code == 403
        assert r.json() == {"detail": "Use case has no customer assignment"}
    r = client.get(f"/api/analytics/predictive/{world['uc_none']}/", headers=_token("admin"))
    assert r.status_code not in (403, 404)


def test_s7_analytics_generate_prediction_gates(client, world):
    """G6/F5 for /predictions/generate/: unassigned → ``can(CAP_EDIT, None)``
    (admin only, unchanged); team UC passes for SM; outsider 404-first."""
    with patch("backend.services.prediction_service.AIPredictionService.generate",
               new=AsyncMock(return_value={"ok": True})):
        url = "/api/analytics/predictions/generate/?use_case_id={}"
        r = client.post(url.format(world["uc_none"]), headers=_token("w2_sm"))
        assert r.status_code == 403 and r.json()["detail"] == NOT_AUTHORIZED_TO_MODIFY
        assert client.post(url.format(world["uc_none"]), headers=_token("admin")).status_code == 200
        assert client.post(url.format(world["uc_team"]), headers=_token("w2_sm")).status_code == 200
        r = client.post(url.format(world["uc_team"]), headers=_token("w2_jaud"))
        assert r.status_code == 403 and r.json()["detail"] == NOT_AUTHORIZED_TO_MODIFY
        _same_404(client, "w2_out", url.format(world["uc_team"]), url.format(999999), method="post")


def test_s7_analytics_unscoped_fixed_query_families(client, db_session, world):
    call = lambda: client.get("/api/analytics/department-trends/", headers=_token("w2_sm"))  # noqa: E731
    base = _count_families(db_session, call)
    _grow_team(db_session, 6)
    assert _count_families(db_session, call) == base


# ── S7 advanced ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("user", READERS)
def test_s7_advanced_read_central(client, world, user):
    for path in ("impact-matrix", "dept-comparison"):
        r = client.get(f"/api/advanced/{path}/?customer_id={world['team']}", headers=_token(user))
        assert r.status_code == 200, (path, r.text)
    # in scope: never the scope 404 (an unscored use case is the service's own 404)
    r = client.get(f"/api/advanced/drill-down/{world['uc_team']}/", headers=_token(user))
    assert r.json().get("detail") != f"Use case {world['uc_team']} not found"


def test_s7_advanced_outsider_404_first(client, world):
    for user in ("w2_out", "w2_is", "w2_sm2"):
        _same_404(client, user, f"/api/advanced/impact-matrix/?customer_id={world['team']}",
                  "/api/advanced/impact-matrix/?customer_id=999999")
        r = client.get(f"/api/advanced/drill-down/{world['uc_team']}/", headers=_token(user))
        assert r.status_code == 404
        assert r.json() == {"detail": f"Use case {world['uc_team']} not found"}


def test_s7_advanced_unscoped_uses_customer_scope(client, db_session, world):
    from backend.services.advanced_visualizations import AdvancedVisualizationsService

    seen = []
    real = AdvancedVisualizationsService.get_impact_matrix

    def spy(db, **kwargs):
        seen.append(kwargs)
        return real(db, **kwargs)

    with patch.object(AdvancedVisualizationsService, "get_impact_matrix", side_effect=spy):
        for user in ("w2_sm", "w2_is", "w2_sm2", "admin"):
            assert client.get("/api/advanced/impact-matrix/", headers=_token(user)).status_code == 200
    assert seen == [{"customer_ids": [world["team"]]}, {"customer_ids": [world["inside"]]},
                    {"customer_ids": []}, {}]

    call = lambda: client.get("/api/advanced/impact-matrix/", headers=_token("w2_sm"))  # noqa: E731
    base = _count_families(db_session, call)
    _grow_team(db_session, 6)
    assert _count_families(db_session, call) == base


# ── S7 technology inventory + dependencies ──────────────────────────────


@pytest.mark.parametrize("user", READERS)
def test_s7_technology_read_central(client, world, user):
    h = _token(user)
    r = client.get(f"/api/customers/{world['team']}/technology/", headers=h)
    assert r.status_code == 200 and len(r.json()) == 2
    assert client.get(f"/api/technology/{world['tech']}/", headers=h).status_code == 200
    r = client.get(f"/api/customers/{world['team']}/technology-dependencies/", headers=h)
    assert r.status_code == 200 and [d["id"] for d in r.json()] == [world["dep"]]
    assert client.get(f"/api/technology-dependencies/{world['dep']}/", headers=h).status_code == 200


def test_s7_technology_outsider_404_first(client, world):
    for user in ("w2_out", "w2_is", "w2_sm2"):
        _same_404(client, user, f"/api/customers/{world['team']}/technology/",
                  "/api/customers/999999/technology/")
        _same_404(client, user, f"/api/technology/{world['tech']}/", "/api/technology/999999/")
        _same_404(client, user, f"/api/customers/{world['team']}/technology-dependencies/",
                  "/api/customers/999999/technology-dependencies/")
        _same_404(client, user, f"/api/technology-dependencies/{world['dep']}/",
                  "/api/technology-dependencies/999999/")


def test_s7_technology_write_stays_edit_gated(client, world):
    for user in ("w2_jaud", "w2_ops"):
        r = client.put(f"/api/technology/{world['tech']}/", json={"vendor": "X"}, headers=_token(user))
        assert r.status_code == 403 and r.json()["detail"] == NOT_AUTHORIZED_TO_MODIFY
    r = client.put(f"/api/technology/{world['tech']}/", json={"vendor": "Red Hat"},
                   headers=_token("w2_sm"))
    assert r.status_code == 200, r.text


# ── S8 RVTools route reads (ruling C2.6) + manager gate (C2.5) ──────────


@pytest.fixture()
def rvtools(db_session, world):
    from backend.models.rvtools_import import RvToolsImport

    def mk(customer_id, name):
        batch = RvToolsImport(customer_id=customer_id, file_name=name, file_sha256="0" * 64,
                              file_data=b"x", host_count=0, vm_count=0, datastore_count=0,
                              license_count=0, imported_by="admin")
        db_session.add(batch)
        db_session.flush()
        return batch.id

    ids = {"team": mk(world["team"], "team.xlsx"), "other": mk(world["other"], "other.xlsx")}
    db_session.commit()
    ids["mk"] = mk
    return ids


def test_s8_rvtools_reads_use_customer_scope(client, world, rvtools):
    r = client.get("/api/rvtools-import/", headers=_token("w2_sm"))
    assert r.status_code == 200
    assert [row["import_id"] for row in r.json()] == [rvtools["team"]]  # team (was: nothing)
    assert client.get(f"/api/rvtools-import/{rvtools['team']}/", headers=_token("w2_sm")).status_code == 200
    r = client.get(f"/api/rvtools-import/{rvtools['other']}/", headers=_token("w2_sm"))
    assert r.status_code == 404 and r.json() == {"detail": "Import not found"}
    r = client.get("/api/rvtools-import/", headers=_token("admin"))
    assert {row["import_id"] for row in r.json()} == {rvtools["team"], rvtools["other"]}
    r = client.get("/api/rvtools-import/", headers=_token("w2_sad"))
    assert {row["import_id"] for row in r.json()} == {rvtools["team"], rvtools["other"]}
    assert client.get("/api/rvtools-import/", headers=_token("w2_sm2")).json() == []


def test_s8_rvtools_customer_dashboard_scope(client, world, rvtools):
    for user in ("w2_sm", "w2_rep", "w2_aud", "w2_sad", "w2_ops", "w2_jaud", "admin"):
        r = client.get(f"/api/customers/{world['team_name']}/rvtools/", headers=_token(user))
        assert r.status_code == 200 and r.json()["import_id"] == rvtools["team"], (user, r.text)
    r = client.get(f"/api/customers/{world['inside_name']}/rvtools/", headers=_token("w2_is"))
    assert r.status_code == 200 and r.json()["import_id"] is None
    for user in ("w2_out", "w2_is", "w2_sm2"):
        _same_404(client, user, f"/api/customers/{world['team_name']}/rvtools/",
                  "/api/customers/NoSuchW2/rvtools/")


def test_s8_rvtools_manager_gate_unchanged(client, world):
    for user in ("w2_rep", "w2_ops", "w2_is"):
        r = client.post("/api/rvtools-import/", headers=_token(user),
                        data={"customer_name": world["team_name"]},
                        files={"file": ("x.xlsx", b"x")})
        assert r.status_code == 403 and r.json() == {"detail": "Manager access required"}
    # sales_admin is stopped upstream by the app-wide content write block (C2.4)
    r = client.post("/api/rvtools-import/", headers=_token("w2_sad"),
                    data={"customer_name": world["team_name"]}, files={"file": ("x.xlsx", b"x")})
    assert r.status_code == 403 and r.json()["detail"] == "Sales admin cannot modify account content"


def test_s8_rvtools_target_central_gate(client, db_session, world):
    # DV11 (ruling R1): _target gates on the central scope +
    # CAP_INTEL_UPLOADS — the old junction gate 404'd a manager on their
    # own team account. (Service-level: the HTTP flow parses the workbook
    # before _target, so the gate itself is the unit under test.)
    from backend.models.use_case import CustomerUser, User
    from backend.services.rvtools_import_service import _target

    def udict(username):
        u = db_session.query(User).filter(User.username == username).first()
        rows = db_session.query(CustomerUser).filter(CustomerUser.user_id == u.id).all()
        return {"username": u.username, "user_id": u.id, "is_admin": u.is_admin,
                "role": u.role, "sales_role": u.sales_role,
                "customer_ids": [r.customer_id for r in rows],
                "junction_roles": {r.customer_id: r.role for r in rows}}

    # SM on a team account: gate passes (was 404 under the junction basis)
    # (Part 14 import remediation: _target returns (customer, matched_by);
    # the 404 detail is "No matching customer name or alias".)
    customer, matched_by = _target(db_session, udict("w2_sm"), world["team_name"])
    assert customer.id == world["team"] and matched_by == "name"
    # SM out of scope: 404, byte-identical to a missing name (404-first)
    with pytest.raises(HTTPException) as exc:
        _target(db_session, udict("w2_sm"), world["other_name"])
    assert exc.value.status_code == 404 and exc.value.detail == "No matching customer name or alias"
    with pytest.raises(HTTPException) as exc2:
        _target(db_session, udict("w2_sm"), "NoSuchW2")
    assert exc2.value.detail == exc.value.detail
    # admin preserved (any customer, no scope filter)
    customer, matched_by = _target(db_session, udict("admin"), world["other_name"])
    assert customer.id == world["other"] and matched_by == "name"


def test_s8_rvtools_list_fixed_query_families(client, db_session, world, rvtools):
    call = lambda: client.get("/api/rvtools-import/", headers=_token("w2_sm"))  # noqa: E731
    base = _count_families(db_session, call)
    _grow_team(db_session, 6, lambda cid: rvtools["mk"](cid, f"scale{cid}.xlsx"))
    assert len(call().json()) == 7
    assert _count_families(db_session, call) == base


# ── S9 pipeline import detail (F12 totals over the central scope) ───────


@pytest.fixture()
def pipeline(db_session, world):
    from backend.models.intelligence_import import IntelligenceImport, PartnerPipeline

    batch = IntelligenceImport(file_name="p.csv", file_sha256="0" * 64, file_data=b"x",
                               total_rows=3, matched_accounts=3, matched_rows=3,
                               unmatched_accounts=0, unmatched_report="[]", imported_by="admin")
    db_session.add(batch)
    db_session.flush()
    for i, (cid, name, acv) in enumerate(((world["team"], world["team_name"], 100.0),
                                          (world["inside"], world["inside_name"], 20.0),
                                          (world["other"], "W2OtherCo", 3.0)), 1):
        db_session.add(PartnerPipeline(import_id=batch.id, customer_id=cid,
                                       customer_account_name=name, est_acv_usd=acv, source_row=i))
    db_session.commit()
    return batch.id


def _detail(client, user, import_id):
    r = client.get(f"/api/intelligence-import/{import_id}/", headers=_token(user))
    assert r.status_code == 200, r.text
    return r.json()


def test_s9_pipeline_detail_uses_customer_scope(client, world, pipeline):
    sm = _detail(client, "w2_sm", pipeline)  # team accounts (was: empty)
    assert [m["customer_id"] for m in sm["matched"]] == [world["team"]]
    assert sm["matched"][0]["est_acv_total"] == 100.0  # F12: totals == the visible scope only
    assert [row["customer_id"] for row in sm["pipeline_rows"]] == [world["team"]]
    assert sm["visible_customer_count"] == 1 and sm["matched_out_of_scope"] == 2

    none = _detail(client, "w2_sm2", pipeline)  # empty scope = nothing
    assert none["matched"] == [] and none["pipeline_rows"] == []
    assert none["matched_out_of_scope"] == 3

    for user in ("admin", "w2_sad"):  # admin -> None; sales_admin reads all
        full = _detail(client, user, pipeline)
        assert {m["customer_id"] for m in full["matched"]} == {world["team"], world["inside"], world["other"]}
        assert sum(m["est_acv_total"] for m in full["matched"]) == 123.0
    assert _detail(client, "admin", pipeline)["matched_out_of_scope"] == 0


def test_s9_pipeline_detail_manager_gate_unchanged(client, world, pipeline):
    for user in ("w2_rep", "w2_out", "w2_is", "w2_ops", "w2_aud"):
        r = client.get(f"/api/intelligence-import/{pipeline}/", headers=_token(user))
        assert r.status_code == 403 and r.json() == {"detail": "Manager access required"}


def test_s9_pipeline_detail_fixed_query_families(client, db_session, world, pipeline):
    from backend.models.intelligence_import import PartnerPipeline

    call = lambda: client.get(f"/api/intelligence-import/{pipeline}/", headers=_token("w2_sm"))  # noqa: E731
    base = _count_families(db_session, call)
    _grow_team(db_session, 6, lambda cid: db_session.add(PartnerPipeline(
        import_id=pipeline, customer_id=cid, customer_account_name=f"W2Scale{cid}")))
    assert len(call().json()["matched"]) == 7
    assert _count_families(db_session, call) == base
