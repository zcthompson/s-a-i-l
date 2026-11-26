"""Read-only account-impact routes (gcm-p5).

GET /api/customers/{name}/account-impact/ and GET /api/account-impact/portfolio/
call backend/services/account_impact.py and are gated by the resolver's READ
capability: 401 unauthenticated, 404 unknown customer, 403 out of scope,
auditor may read, admin sees everything, scope is never "all" for non-admins.
"""

import pytest

from tests.backend._shared import add_pipeline_batch


def _headers(username: str, is_admin: bool = False) -> dict:
    from backend.auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token({'sub': username, 'is_admin': is_admin})}"}


def _mk_user(db, username, *, sales_role=None):
    from backend.auth import hash_password
    from backend.models.use_case import User

    u = User(
        username=username, email=f"{username}@test.local",
        hashed_password=hash_password(username), display_name=username,
        department="Sales", is_admin=0, approved=1, is_active=1, sales_role=sales_role,
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture()
def impact_world(db_session):
    from backend.models.use_case import Customer, CustomerUser, UseCase

    class W:
        pass

    w = W()
    w.mine = Customer(name="ImpactMine", description="m")
    w.other = Customer(name="ImpactOther", description="o")
    db_session.add_all([w.mine, w.other])
    db_session.flush()
    rep = _mk_user(db_session, "imp_rep", sales_role="rep")
    aud = _mk_user(db_session, "imp_aud", sales_role="auditor")
    _mk_user(db_session, "imp_outsider")
    db_session.add_all([
        CustomerUser(customer_id=w.mine.id, user_id=rep.id, role="owner", granted_by=rep.id),
        CustomerUser(customer_id=w.mine.id, user_id=aud.id, role="auditor", granted_by=rep.id),
        UseCase(title="UC mine", customer_id=w.mine.id, estimated_savings=1000.0, estimated_revenue=500.0),
        UseCase(title="UC other", customer_id=w.other.id, estimated_savings=7.0),
    ])
    db_session.commit()
    return w


def _admin_headers(db_session) -> dict:
    from backend.models.use_case import User

    admin = db_session.query(User).filter(User.is_admin == 1).first()
    return _headers(admin.username, True)


def test_account_impact_requires_auth(client, impact_world):
    assert client.get("/api/customers/ImpactMine/account-impact/").status_code == 401
    assert client.get("/api/account-impact/portfolio/").status_code == 401


def test_account_impact_contract_for_owner(client, impact_world):
    r = client.get("/api/customers/ImpactMine/account-impact/", headers=_headers("imp_rep"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["coverage"] == "quantified"
    assert body["total_impact"]["value"] == 1500.0
    assert body["total_impact"]["perspective"] == "customer_benefit"
    assert body["total_impact"]["realization_basis"] == "estimated"
    assert set(body["measures"]) >= {"customer_benefit_assessment", "service_commitments",
                                     "qualitative_intelligence", "pipeline"}


def test_account_impact_auditor_can_read(client, impact_world):
    r = client.get("/api/customers/ImpactMine/account-impact/", headers=_headers("imp_aud"))
    assert r.status_code == 200


def test_account_impact_out_of_scope_and_unknown_404(client, impact_world):
    h = _headers("imp_rep")
    # 404-first (R4/Q7): out-of-scope is the same 404 as an unknown customer.
    assert client.get("/api/customers/ImpactOther/account-impact/", headers=h).status_code == 404
    assert client.get("/api/customers/NoSuchCustomer/account-impact/", headers=h).status_code == 404
    assert client.get("/api/customers/ImpactMine/account-impact/",
                      headers=_headers("imp_outsider")).status_code == 404


def test_account_impact_admin_reads_any(client, db_session, impact_world):
    r = client.get("/api/customers/ImpactOther/account-impact/", headers=_admin_headers(db_session))
    assert r.status_code == 200
    assert r.json()["total_impact"]["value"] == 7.0


def test_portfolio_scoped_for_rep_and_all_for_admin(client, db_session, impact_world):
    r = client.get("/api/account-impact/portfolio/", headers=_headers("imp_rep"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert [c["customer_name"] for c in body["customers"]] == ["ImpactMine"]
    assert body["total_impact"]["value"] == 1500.0
    assert body["customer_count"] == 1

    ra = client.get("/api/account-impact/portfolio/", headers=_admin_headers(db_session))
    assert ra.status_code == 200
    names = {c["customer_name"] for c in ra.json()["customers"]}
    assert {"ImpactMine", "ImpactOther"} <= names


def test_portfolio_empty_scope_is_empty_not_all(client, impact_world):
    r = client.get("/api/account-impact/portfolio/", headers=_headers("imp_outsider"))
    assert r.status_code == 200
    body = r.json()
    assert body["customers"] == []
    assert body["total_impact"]["value"] is None
    assert body["coverage"] == "not_quantified"
    assert body["pipeline"]["acv"]["total"] is None
    assert body["pipeline"]["tcv"]["total"] is None
    assert body["pipeline"]["acv"]["lines"] == 0


def test_portfolio_pipeline_is_batched_once_and_matches_customer_rows(
    client, db_session, impact_world, monkeypatch,
):
    from backend.models.use_case import Customer, CustomerUser, User
    from backend.services import pipeline_read_model, sales_access
    from sqlalchemy import event

    second = Customer(name="Synthetic Second Readable Account")
    db_session.add(second)
    db_session.flush()
    rep = db_session.query(User).filter_by(username="imp_rep").one()
    db_session.add(CustomerUser(customer_id=second.id, user_id=rep.id, role="member"))
    add_pipeline_batch(db_session, [
        (impact_world.mine, [{"est_acv_usd": 0.1}, {"est_acv_usd": 0.2}]),
        (second, [{"est_acv_usd": 12.34, "est_tcv_usd": 30}, {"est_acv_usd": None}]),
        (impact_world.other, [{"est_acv_usd": 999999, "est_tcv_usd": 999999}]),
    ])
    # An older retained batch must not be added to the selected snapshot.
    add_pipeline_batch(db_session, [(impact_world.mine, [{"est_acv_usd": 10.01, "est_tcv_usd": 20}])])
    db_session.commit()
    expected = pipeline_read_model.pipeline_summaries_for(db_session, [impact_world.mine.id, second.id])
    calls = []
    statements = []
    original = pipeline_read_model.pipeline_summaries_for
    original_scope = sales_access.customer_scope

    def read(db, ids):
        calls.append(list(ids))
        return original(db, ids)

    def record(conn, cursor, statement, parameters, context, executemany):
        if "partner_pipeline" in statement or "intelligence_imports" in statement:
            statements.append(statement)

    # Include an unreadable candidate to pin that batching happens AFTER can(READ).
    monkeypatch.setattr(sales_access, "customer_scope", lambda user, db: (
        original_scope(user, db) | {impact_world.other.id}
    ))
    monkeypatch.setattr(pipeline_read_model, "pipeline_summaries_for", read)
    event.listen(db_session.bind, "before_cursor_execute", record)
    try:
        response = client.get("/api/account-impact/portfolio/", headers=_headers("imp_rep"))
    finally:
        event.remove(db_session.bind, "before_cursor_execute", record)
    assert response.status_code == 200, response.text
    body = response.json()
    assert calls == [sorted(expected)]
    assert len(statements) == 6  # H1 + H3 each batch once; no account-by-account reads
    assert body["customer_count"] == 2
    assert body["total_impact"]["value"] == 1500.0
    assert body["calculation_version"] == "account-impact/2"
    assert body["pipeline"]["calculation_version"] == "pipeline-read-model/1"
    assert body["pipeline"]["acv"] == {
        "total": 22.35, "lines": 3, "accounts_quantified": 1, "accounts_partial": 1,
        "accounts_recorded_zero": 0, "accounts_all_unknown": 0, "accounts_no_data": 0,
    }
    assert body["pipeline"]["tcv"]["total"] == 50.0
    assert {row["customer_id"] for row in body["customers"]} == set(expected)
    assert "ImpactOther" not in response.text
    for row in body["customers"]:
        amounts = expected[row["customer_id"]]["amounts"]
        assert row["pipeline"] == {
            "acv": amounts["acv"]["total"], "tcv": amounts["tcv"]["total"],
            "coverage": amounts["acv"]["coverage"],
        }


def test_portfolio_metadata_batched_and_matches_customer_detail(client, db_session):
    from backend.models.use_case import Customer, CustomerUser
    from sqlalchemy import event

    accounts = [Customer(name=f"Synthetic Metadata Account {i}") for i in range(4)]
    accounts[0].vertical = "Synthetic Vertical"
    accounts[0].branch = "Synthetic Branch"
    accounts[3].sales_area = "321"
    accounts[3].primary_subsidiary = "Synthetic Subsidiary"
    db_session.add_all(accounts)
    db_session.flush()
    first = _mk_user(db_session, "synthetic_first", sales_role="sales_manager")
    first.display_name = "Synthetic First Owner"
    rep = _mk_user(db_session, "synthetic_rep", sales_role="rep")
    rep.display_name = "Synthetic Rep Owner"
    fallback = _mk_user(db_session, "synthetic_fallback")
    fallback.display_name = ""
    second_rep = _mk_user(db_session, "synthetic_second_rep", sales_role="rep")
    db_session.add_all([
        # Exactly one rep wins even when a non-rep owner came first.
        CustomerUser(customer_id=accounts[0].id, user_id=first.id, role="owner"),
        CustomerUser(customer_id=accounts[0].id, user_id=rep.id, role="owner"),
        CustomerUser(customer_id=accounts[1].id, user_id=fallback.id, role="owner"),
        CustomerUser(customer_id=accounts[1].id, user_id=first.id, role="owner"),
        # A rep membership is not an owner.
        CustomerUser(customer_id=accounts[2].id, user_id=rep.id, role="member"),
        # Multiple rep owners fall back to the first owner, including a non-rep.
        CustomerUser(customer_id=accounts[3].id, user_id=first.id, role="owner"),
        CustomerUser(customer_id=accounts[3].id, user_id=rep.id, role="owner"),
        CustomerUser(customer_id=accounts[3].id, user_id=second_rep.id, role="owner"),
    ])
    db_session.commit()
    headers = _admin_headers(db_session)
    ids = [account.id for account in accounts]
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "FROM customer_users JOIN users" in statement:
            statements.append((statement, parameters))

    event.listen(db_session.bind, "before_cursor_execute", record)
    try:
        response = client.get("/api/account-impact/portfolio/", headers=headers)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", record)
    assert response.status_code == 200, response.text
    assert len(statements) == 1
    statement, parameters = statements[0]
    assert "customer_users.customer_id IN" in statement
    assert "ORDER BY customer_users.customer_id, customer_users.id" in statement
    if isinstance(parameters, dict):
        assert sorted(v for v in parameters.values() if isinstance(v, int)) == sorted(ids)
        assert "owner" in parameters.values()
    else:
        assert parameters == (*ids, "owner")
    rows = response.json()["customers"]
    assert [row["customer_id"] for row in rows] == ids
    expected_reps = ["Synthetic Rep Owner", "synthetic_fallback", None, "Synthetic First Owner"]
    fields = ("vertical", "branch", "sales_area", "primary_subsidiary", "primary_rep")
    for account, row, primary_rep in zip(accounts, rows, expected_reps, strict=True):
        assert {field: row[field] for field in fields} == {
            "vertical": account.vertical, "branch": account.branch,
            "sales_area": account.sales_area, "primary_subsidiary": account.primary_subsidiary,
            "primary_rep": primary_rep,
        }
        detail = client.get(f"/api/customers/{account.name}/", headers=headers)
        assert detail.status_code == 200, detail.text
        assert row["primary_rep"] == detail.json()["primary_rep"]


def test_portfolio_my_view_preserves_admin_membership_scope(client, db_session, impact_world):
    from backend.models.use_case import CustomerUser, User

    admin = db_session.query(User).filter(User.is_admin == 1).one()
    db_session.add(CustomerUser(customer_id=impact_world.other.id, user_id=admin.id, role="member"))
    db_session.commit()
    headers = _admin_headers(db_session)
    response = client.get("/api/account-impact/portfolio/?my_view=true", headers=headers)
    assert response.status_code == 200, response.text
    assert [row["customer_id"] for row in response.json()["customers"]] == [impact_world.other.id]
    assert response.json()["customers"][0]["primary_rep"] is None


def test_account_impact_no_sales_read_capability_404(client, db_session, impact_world):
    user = _mk_user(db_session, "synthetic_ps_admin")
    user.role = "ps_admin"
    db_session.commit()
    response = client.get("/api/customers/ImpactMine/account-impact/",
                          headers=_headers(user.username))
    # No sales read capability = out of scope: 404-first (R4/Q7).
    assert response.status_code == 404
