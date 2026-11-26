"""W1 pins: central-policy basis for scope, reads,
scoring, comments and notifications.

Every surface here moved from a legacy junction check to the central
``sales_access`` basis:

- S1 customer list + in-scope detail → ``customer_scope``;
- S2 metadata update → ``can(CAP_METADATA)``, create/archive round →
  ``can(CAP_EDIT)`` (exact 403 "Not authorized to modify this customer");
- S3 use-case list + stats → ``customer_scope`` (admin unrestricted);
- S4 scoring / manual / bulk → ``can(CAP_EDIT)`` (exact service denial
  "scoring requires edit access to this customer");
- S5 comments → ``can(CAP_READ)`` read, ``can(CAP_NOTES)`` write;
- S6 customer broadcast recipients → junction rows UNION every user with
  central READ on the customer (ONE query).

404-first is preserved (out of scope == missing, byte-identical) and the
list/stats/broadcast surfaces pin fixed query-family counts under scale.

Run: pytest tests/backend/test_part13_dv_wave1.py -v
"""

import os
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import event

from tests.backend.common import _token

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

NOT_AUTHORIZED_TO_MODIFY = "Not authorized to modify this customer"
SCORING_DENIED = "scoring requires edit access to this customer"
SCORING_RESULT = {
    "dimension_scores": [{"name": "Data Readiness", "score": 75, "weight": 0.2, "description": "Ready"}],
    "overall_score": 75,
    "reasoning": "Ready",
    "recommendations": ["Proceed"],
    "scored_at": "2026-10-30T00:00:00+00:00",
}
SCOPE_FAMILIES = ("sales_reporting", "inside_sales_assignments", "sales_ops_assignments",
                  "account_memberships")



def _mk_user(db_session, username: str, sales_role: str | None = None, is_admin: int = 0):
    from backend.models.use_case import User
    user = User(username=username, email=f"{username}@test.local", hashed_password="unused",
                display_name=username, department="Sales", is_admin=is_admin, approved=1,
                is_active=1, role="user", sales_role=sales_role)
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def world(db_session):
    """TeamCo: owned by w1_rep (reports to w1_sm), w1_member junction member,
    w1_coown co_owner membership, w1_opsm sales_ops membership.
    InsideCo: legacy inside-sales assignment for w1_is (no membership).
    OtherCo: owned by w1_out (the outsider for TeamCo).
    w1_jaud holds only an auditor junction on TeamCo — it passes the app-wide
    role write block, so it reaches the central ``can()`` denial (the global
    auditor / sales_admin roles are stopped earlier by that block with its
    own message)."""
    from backend.models.account_membership import AccountMembership
    from backend.models.sales_access import InsideSalesAssignment, SalesReporting
    from backend.models.use_case import Customer, CustomerAssessment, CustomerUser, UseCase

    team, inside, other = Customer(name="DVTeamCo"), Customer(name="DVInsideCo"), Customer(name="DVOtherCo")
    db_session.add_all([team, inside, other])
    db_session.flush()
    rep = _mk_user(db_session, "w1_rep", "rep")
    sm = _mk_user(db_session, "w1_sm", "sales_manager")
    member = _mk_user(db_session, "w1_member", "rep")
    coown = _mk_user(db_session, "w1_coown", "rep")
    opsm = _mk_user(db_session, "w1_opsm", "sales_ops")
    isales = _mk_user(db_session, "w1_is", "inside_sales")
    aud = _mk_user(db_session, "w1_aud", "auditor")
    sad = _mk_user(db_session, "w1_sad", "sales_admin")
    out = _mk_user(db_session, "w1_out", "rep")
    jaud = _mk_user(db_session, "w1_jaud")  # auditor JUNCTION only: in scope, no write
    db_session.add_all([
        CustomerUser(customer_id=team.id, user_id=rep.id, role="owner"),
        CustomerUser(customer_id=team.id, user_id=member.id, role="member"),
        CustomerUser(customer_id=other.id, user_id=out.id, role="owner"),
        CustomerUser(customer_id=team.id, user_id=jaud.id, role="auditor"),
        SalesReporting(rep_user_id=rep.id, manager_user_id=sm.id),
        AccountMembership(customer_id=team.id, user_id=coown.id, role="co_owner"),
        AccountMembership(customer_id=team.id, user_id=opsm.id, role="sales_ops"),
        InsideSalesAssignment(customer_id=inside.id, inside_sales_user_id=isales.id),
    ])
    assessment = CustomerAssessment(customer_id=team.id, name="Round one", created_by="w1_rep")
    db_session.add(assessment)
    db_session.flush()
    uc_team = UseCase(title="DV team UC", customer_id=team.id, department="Eng", status="active",
                      created_by="w1_rep", assessment_id=assessment.id)
    uc_inside = UseCase(title="DV inside UC", customer_id=inside.id, department="Eng",
                        status="active", created_by="seed")
    uc_other = UseCase(title="DV other UC", customer_id=other.id, department="Eng",
                       status="active", created_by="w1_out")
    uc_none = UseCase(title="DV unassigned UC", customer_id=None, department="Eng",
                      status="active", created_by="seed")
    db_session.add_all([uc_team, uc_inside, uc_other, uc_none])
    db_session.commit()
    return {
        "team": team.id, "team_name": team.name, "inside": inside.id, "inside_name": inside.name,
        "other": other.id, "other_name": other.name, "assessment": assessment.id,
        "uc_team": uc_team.id, "uc_inside": uc_inside.id, "uc_other": uc_other.id,
        "uc_none": uc_none.id,
    }


@pytest.fixture()
def no_ai():
    with patch("backend.clients.ai_client.AIClient.score_use_case",
               new=AsyncMock(return_value=SCORING_RESULT)) as model, \
         patch("backend.services.insight_service.InsightService.trigger_async"):
        yield model


def _same_404(client, username, method, url, missing_url, **kwargs):
    h = _token(username)
    out = getattr(client, method)(url, headers=h, **kwargs)
    miss = getattr(client, method)(missing_url, headers=h, **kwargs)
    assert out.status_code == miss.status_code == 404, (out.status_code, out.text[:160])
    assert out.json() == miss.json()


def _record(db_session):
    engine = db_session.get_bind()
    engine = getattr(engine, "engine", engine)
    statements: list = []

    def rec(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    return engine, statements, rec


def _families(statements, family):
    return sum(1 for s in statements if family in s)


def _names(rows):
    return {r["name"] for r in rows}


# ── S1: customer list + detail ─────────────────────────────────────


def test_s1_list_scope_per_identity(client, world):
    def listed(user):
        r = client.get("/api/customers/", headers=_token(user))
        assert r.status_code == 200, r.text
        return _names(r.json())

    all_three = {world["team_name"], world["inside_name"], world["other_name"]}
    assert listed("w1_sm") == {world["team_name"]}            # team scope (was: nothing)
    assert listed("w1_is") == {world["inside_name"]}          # legacy assignment (was: nothing)
    assert listed("w1_rep") == {world["team_name"]}           # owner unchanged
    assert listed("w1_member") == {world["team_name"]}        # member unchanged
    assert listed("w1_out") == {world["other_name"]}          # no leak
    assert all_three <= listed("w1_aud")                      # reads-all
    assert all_three <= listed("w1_sad")
    r = client.get("/api/customers/", headers=_token("admin", True))
    assert all_three <= _names(r.json())                      # admin preserved


@pytest.mark.parametrize("user", ["w1_sm", "w1_rep", "w1_member", "w1_coown", "w1_aud", "w1_sad", "admin"])
def test_s1_detail_in_scope(client, world, user):
    r = client.get(f"/api/customers/{world['team_name']}/", headers=_token(user, user == "admin"))
    assert r.status_code == 200, r.text
    assert r.json()["name"] == world["team_name"]


def test_s1_detail_inside_sales_assignee_and_outsider_404_first(client, world):
    assert client.get(f"/api/customers/{world['inside_name']}/", headers=_token("w1_is")).status_code == 200
    _same_404(client, "w1_out", "get", f"/api/customers/{world['team_name']}/", "/api/customers/NoSuchDV/")
    _same_404(client, "w1_is", "get", f"/api/customers/{world['team_name']}/", "/api/customers/NoSuchDV/")


def test_s1_list_fixed_query_families_under_scale(client, db_session, world):
    from backend.models.use_case import Customer, CustomerUser, User

    engine, statements, rec = _record(db_session)

    def run():
        statements.clear()
        event.listen(engine, "before_cursor_execute", rec)
        try:
            r = client.get("/api/customers/", headers=_token("w1_sm"))
        finally:
            event.remove(engine, "before_cursor_execute", rec)
        assert r.status_code == 200
        return r.json(), {f: _families(statements, f) for f in ("customer_aliases", *SCOPE_FAMILIES)}

    rows, baseline = run()
    assert len(rows) == 1
    assert baseline["customer_aliases"] == 1
    rep_id = db_session.query(User.id).filter(User.username == "w1_rep").scalar()
    for i in range(4):
        c = Customer(name=f"DVTeamExtra{i}")
        db_session.add(c)
        db_session.flush()
        db_session.add(CustomerUser(customer_id=c.id, user_id=rep_id, role="owner"))
    db_session.commit()
    rows, scaled = run()
    assert len(rows) == 5
    # One query per family regardless of the number of team accounts.
    assert scaled == baseline


# ── S2: metadata update + round create/archive ─────────────────────


@pytest.mark.parametrize("user", ["w1_sm", "w1_opsm", "w1_coown", "w1_rep"])
def test_s2_metadata_update_granted(client, world, user):
    r = client.put(f"/api/customers/{world['team_name']}/", headers=_token(user),
                   json={"description": f"by {user}"})
    assert r.status_code == 200, r.text
    assert r.json()["description"] == f"by {user}"


@pytest.mark.parametrize("user", ["w1_member", "w1_jaud", "w1_sad"])
def test_s2_metadata_update_denied_exact_403(client, world, user):
    r = client.put(f"/api/customers/{world['team_name']}/", headers=_token(user), json={"description": "x"})
    assert (r.status_code, r.json()["detail"]) == (403, NOT_AUTHORIZED_TO_MODIFY)


def test_s2_global_auditor_write_blocked(client, world):
    r = client.put(f"/api/customers/{world['team_name']}/", headers=_token("w1_aud"), json={"description": "x"})
    assert (r.status_code, r.json()["detail"]) == (403, "Auditor role is read-only")


def test_s2_admin_preserved_and_outsider_404_first(client, world):
    r = client.put(f"/api/customers/{world['team_name']}/", headers=_token("admin", True),
                   json={"description": "admin"})
    assert r.status_code == 200
    base, missing = f"/api/customers/{world['team_name']}/", "/api/customers/NoSuchDV/"
    _same_404(client, "w1_out", "put", base, missing, json={"description": "x"})
    _same_404(client, "w1_out", "post", base + "assessments/", missing + "assessments/", json={"name": "R2"})
    _same_404(client, "w1_out", "post", f"{base}assessments/{world['assessment']}/archive/",
              f"{missing}assessments/{world['assessment']}/archive/")


@pytest.mark.parametrize("user", ["w1_sm", "w1_opsm", "w1_coown"])
def test_s2_archive_then_create_round_granted(client, world, user):
    base = f"/api/customers/{world['team_name']}/assessments/"
    r = client.post(f"{base}{world['assessment']}/archive/", headers=_token(user))
    assert r.status_code == 200, r.text
    r = client.post(base, headers=_token(user), json={"name": f"R2 {user}"})
    assert r.status_code == 201, r.text


@pytest.mark.parametrize("user", ["w1_jaud"])
def test_s2_round_writes_denied_exact_403(client, world, user):
    base = f"/api/customers/{world['team_name']}/assessments/"
    r = client.post(f"{base}{world['assessment']}/archive/", headers=_token(user))
    assert (r.status_code, r.json()["detail"]) == (403, NOT_AUTHORIZED_TO_MODIFY)
    r = client.post(base, headers=_token(user), json={"name": "R2"})
    assert (r.status_code, r.json()["detail"]) == (403, NOT_AUTHORIZED_TO_MODIFY)


@pytest.mark.parametrize("user", ["w1_aud", "w1_sad"])
def test_s2_global_read_roles_round_writes_403(client, world, user):
    base = f"/api/customers/{world['team_name']}/assessments/"
    assert client.post(f"{base}{world['assessment']}/archive/", headers=_token(user)).status_code == 403
    assert client.post(base, headers=_token(user), json={"name": "R2"}).status_code == 403


def test_s2_member_round_writes_unchanged(client, world):
    base = f"/api/customers/{world['team_name']}/assessments/"
    r = client.post(f"{base}{world['assessment']}/archive/", headers=_token("w1_member"))
    assert r.status_code == 200, r.text


# ── S3: use-case list + stats ──────────────────────────────────────


def _uc_titles(client, user):
    r = client.get("/api/use-cases/", headers=_token(user, user == "admin"))
    assert r.status_code == 200, r.text
    return {u["title"] for u in r.json()}


def test_s3_use_case_list_scope(client, world):
    assert _uc_titles(client, "w1_sm") == {"DV team UC"}
    assert _uc_titles(client, "w1_is") == {"DV inside UC"}
    assert _uc_titles(client, "w1_rep") == {"DV team UC"}
    assert _uc_titles(client, "w1_out") == {"DV other UC"}
    assigned = {"DV team UC", "DV inside UC", "DV other UC"}
    assert _uc_titles(client, "w1_aud") == assigned
    assert _uc_titles(client, "w1_sad") == assigned
    assert assigned | {"DV unassigned UC"} <= _uc_titles(client, "admin")
    # An explicit customer filter is constrained to the scope, never widened.
    r = client.get(f"/api/use-cases/?customer_id={world['other']}", headers=_token("w1_sm"))
    assert r.json() == []


def test_s3_use_case_stats_scope(client, db_session, world):
    def total(user):
        r = client.get("/api/use-cases/stats/", headers=_token(user, user == "admin"))
        assert r.status_code == 200, r.text
        return r.json()["total_use_cases"]

    assert total("w1_sm") == 1
    assert total("w1_is") == 1
    assert total("w1_rep") == 1
    assert total("w1_aud") == 3
    assert total("w1_sad") == 3
    assert total("admin") == 4
    _mk_user(db_session, "w1_empty", "rep")
    db_session.commit()
    assert total("w1_empty") == 0
    assert client.get("/api/use-cases/", headers=_token("w1_empty")).json() == []


def test_s3_list_and_stats_fixed_query_families_under_scale(client, db_session, world):
    from backend.models.use_case import Customer, CustomerUser, UseCase, User

    engine, statements, rec = _record(db_session)

    def run(url):
        statements.clear()
        event.listen(engine, "before_cursor_execute", rec)
        try:
            r = client.get(url, headers=_token("w1_sm"))
        finally:
            event.remove(engine, "before_cursor_execute", rec)
        assert r.status_code == 200
        return {f: _families(statements, f) for f in ("from use_cases", *SCOPE_FAMILIES)}

    base_list, base_stats = run("/api/use-cases/"), run("/api/use-cases/stats/")
    rep_id = db_session.query(User.id).filter(User.username == "w1_rep").scalar()
    for i in range(4):
        c = Customer(name=f"DVUcExtra{i}")
        db_session.add(c)
        db_session.flush()
        db_session.add_all([
            CustomerUser(customer_id=c.id, user_id=rep_id, role="owner"),
            UseCase(title=f"DV extra {i}", customer_id=c.id, department="Eng",
                    status="active", created_by="seed"),
        ])
    db_session.commit()
    assert run("/api/use-cases/") == base_list
    assert run("/api/use-cases/stats/") == base_stats
    assert len(_uc_titles(client, "w1_sm")) == 5


# ── S4: scoring / manual / bulk ────────────────────────────────────


@pytest.mark.parametrize("user", ["w1_sm", "w1_opsm", "w1_coown", "w1_member"])
def test_s4_score_and_manual_score_granted(client, world, no_ai, user):
    h = _token(user)
    r = client.post("/api/scoring/", headers=h, json={"use_case_id": world["uc_team"]})
    assert r.status_code == 200, r.text
    r = client.post("/api/scoring/manual/", headers=h,
                    json={"use_case_id": world["uc_team"], "scores": {}, "overall_score": 50.0})
    assert r.status_code == 200, r.text


def test_s4_bulk_score_team_manager(client, world, no_ai):
    r = client.post("/api/bulk/score-multiple/", headers=_token("w1_sm"), json=[world["uc_team"]])
    assert r.status_code == 200, r.text
    assert (r.json()["success_count"], r.json()["error_count"]) == (1, 0)


def test_s4_service_gate_exact_message_and_admin(db_session, world):
    from backend.models.use_case import UseCase
    from backend.services.scoring import ScoringService

    uc = db_session.query(UseCase).filter(UseCase.id == world["uc_team"]).one()
    # A sales_admin reads all but holds no CAP_EDIT; the service gate itself
    # carries the exact new message.
    sad = {"username": "w1_sad", "user_id": 0, "is_admin": 0, "role": "user",
           "sales_role": "sales_admin", "customer_ids": [], "junction_roles": {}}
    with pytest.raises(ValueError, match=f"^{SCORING_DENIED}$"):
        ScoringService.assert_scoring_access(db_session, sad, uc)
    ScoringService.assert_scoring_access(db_session, {"username": "admin", "is_admin": 1}, uc)


@pytest.mark.parametrize("user", ["w1_jaud", "w1_aud", "w1_sad"])
def test_s4_read_only_roles_denied(client, world, no_ai, user):
    h = _token(user)
    r = client.post("/api/scoring/", headers=h, json={"use_case_id": world["uc_team"]})
    assert r.status_code == 403
    if user == "w1_jaud":
        assert r.json()["detail"] == NOT_AUTHORIZED_TO_MODIFY
    r = client.post("/api/scoring/manual/", headers=h,
                    json={"use_case_id": world["uc_team"], "scores": {}, "overall_score": 50.0})
    assert r.status_code == 403
    no_ai.assert_not_called()


def test_s4_bulk_auditor_junction_and_outsider(client, world, no_ai):
    # The bulk path surfaces the service gate's exact new message.
    r = client.post("/api/bulk/score-multiple/", headers=_token("w1_jaud"), json=[world["uc_team"]])
    assert r.json()["errors"][0]["error"] == SCORING_DENIED
    r = client.post("/api/bulk/score-multiple/", headers=_token("w1_out"), json=[world["uc_team"]])
    assert r.json()["errors"][0]["error"] == f"Use case {world['uc_team']} not found"


def test_s4_outsider_404_first_and_unassigned_admin_only(client, world, no_ai):
    h = _token("w1_out")
    body = {"scores": {}, "overall_score": 50.0}
    out = client.post("/api/scoring/manual/", headers=h, json={"use_case_id": world["uc_team"], **body})
    miss = client.post("/api/scoring/manual/", headers=h, json={"use_case_id": 999999, **body})
    assert out.status_code == miss.status_code == 404
    assert out.json()["detail"] == f"Use case {world['uc_team']} not found"
    r = client.post("/api/scoring/", headers=h, json={"use_case_id": world["uc_team"]})
    assert (r.status_code, r.json()["detail"]) == (404, f"Use case {world['uc_team']} not found")
    # G6: can(CAP_EDIT, None) is admin-only — unchanged vs the old rule.
    r = client.post("/api/scoring/manual/", headers=_token("w1_sm"),
                    json={"use_case_id": world["uc_none"], "scores": {}, "overall_score": 50.0})
    assert (r.status_code, r.json()["detail"]) == (403, "Unassigned use cases are admin-only")
    r = client.post("/api/scoring/manual/", headers=_token("admin", True),
                    json={"use_case_id": world["uc_none"], "scores": {}, "overall_score": 50.0})
    assert r.status_code == 200, r.text
    no_ai.assert_not_called()


def test_s4_unrelated_rep_denied(client, world, no_ai):
    # w1_out owns OtherCo; TeamCo is outside its scope → 404-first, and an
    # in-scope member with no write holds nothing on a foreign account.
    r = client.post("/api/scoring/", headers=_token("w1_rep"), json={"use_case_id": world["uc_other"]})
    assert r.status_code == 404


# ── S5: comments ───────────────────────────────────────────────────


@pytest.mark.parametrize("user", ["w1_sm", "w1_aud", "w1_sad", "w1_jaud", "w1_member", "admin"])
def test_s5_comment_read_granted(client, world, user):
    r = client.get(f"/api/use-cases/{world['uc_team']}/comments/", headers=_token(user, user == "admin"))
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("user", ["w1_sm", "w1_coown", "w1_member"])
def test_s5_comment_write_granted(client, world, user):
    r = client.post(f"/api/use-cases/{world['uc_team']}/comments/", headers=_token(user),
                    json={"content": f"note by {user}"})
    assert r.status_code == 201, r.text


@pytest.mark.parametrize("user", ["w1_aud", "w1_sad", "w1_jaud"])
def test_s5_read_only_roles_cannot_comment(client, world, user):
    r = client.post(f"/api/use-cases/{world['uc_team']}/comments/", headers=_token(user),
                    json={"content": "x"})
    assert r.status_code == 403


def test_s5_outsider_404_first(client, world):
    _same_404(client, "w1_out", "get", f"/api/use-cases/{world['uc_team']}/comments/",
              "/api/use-cases/999999/comments/")
    _same_404(client, "w1_out", "post", f"/api/use-cases/{world['uc_team']}/comments/",
              "/api/use-cases/999999/comments/", json={"content": "x"})
    r = client.get(f"/api/use-cases/notifications/?customer_id={world['team']}", headers=_token("w1_out"))
    assert (r.status_code, r.json()["detail"]) == (404, "Customer not found")
    r = client.get(f"/api/use-cases/notifications/?customer_id={world['team']}", headers=_token("w1_sm"))
    assert r.status_code == 200


# ── S6: broadcast recipients ───────────────────────────────────────


def _broadcast(db_session, customer_id, exclude_user=None):
    from backend.services.collaboration_service import CollaborationService
    with patch("backend.services.collaboration_service.notify_user"):
        return CollaborationService.broadcast_to_customer(
            db_session, customer_id, "status_change", "Status changed", exclude_user=exclude_user)


def test_s6_recipients_are_every_central_reader(db_session, world):
    rows = _broadcast(db_session, world["team"], exclude_user="w1_rep")
    names = [r["user_name"] for r in rows]
    assert len(names) == len(set(names))  # deduped by user
    assert set(names) == {"admin", "w1_sm", "w1_member", "w1_coown", "w1_opsm", "w1_aud", "w1_sad",
                          "w1_jaud"}
    assert all(r["message"] == "Status changed" and r["type"] == "status_change"
               and r["customer_id"] == world["team"] for r in rows)
    inside = {r["user_name"] for r in _broadcast(db_session, world["inside"])}
    assert "w1_is" in inside and "w1_out" not in inside and "w1_sm" not in inside


def test_s6_comment_notifies_team_manager_and_membership(client, db_session, world):
    from backend.models.collaboration import Notification
    r = client.post(f"/api/use-cases/{world['uc_team']}/comments/", headers=_token("w1_rep"),
                    json={"content": "hello"})
    assert r.status_code == 201, r.text
    db_session.expire_all()
    got = {n.user_name: n.message for n in db_session.query(Notification)
           .filter(Notification.type == "comment_added").all()}
    assert {"w1_sm", "w1_coown", "w1_member"} <= set(got)
    assert "w1_rep" not in got and "w1_out" not in got and "w1_is" not in got
    assert got["w1_sm"] == "w1_rep commented on use case 'DV team UC'."


def test_s6_orphan_junction_row_creates_no_unknown_notification(db_session, world):
    from backend.models.use_case import CustomerUser
    if db_session.bind.dialect.name == "postgresql":
        from sqlalchemy.exc import IntegrityError
        db_session.add(CustomerUser(customer_id=world["other"], user_id=987654, role="member"))
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()
        names = {r["user_name"] for r in _broadcast(db_session, world["other"])}
        assert "unknown" not in names and "w1_out" in names
        return
    db_session.add(CustomerUser(customer_id=world["other"], user_id=987654, role="member"))
    db_session.commit()
    names = {r["user_name"] for r in _broadcast(db_session, world["other"])}
    assert "unknown" not in names and "w1_out" in names


def test_s6_broadcast_is_one_recipient_query_under_scale(db_session, world):
    from backend.models.account_membership import AccountMembership

    engine, statements, rec = _record(db_session)

    def selects():
        statements.clear()
        event.listen(engine, "before_cursor_execute", rec)
        try:
            _broadcast(db_session, world["team"])
        finally:
            event.remove(engine, "before_cursor_execute", rec)
        return sum(1 for s in statements if s.lstrip().startswith(("select", "with")))

    baseline = selects()
    # Fixed count regardless of recipient scale: ONE recipient query (the
    # fan-out, which carries the recipient emails for EL email delivery) +
    # ONE email-settings read (read once per broadcast, never per recipient).
    assert baseline == 2
    for i in range(5):
        u = _mk_user(db_session, f"w1_extra{i}", "rep")
        db_session.add(AccountMembership(customer_id=world["team"], user_id=u.id, role="co_owner"))
    db_session.commit()
    assert selects() == baseline
