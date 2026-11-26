"""Synthetic contracts: honest components, bounded reads and scoped actions."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from backend.auth import create_access_token
from backend.models.customer_engagement import CustomerActivity, CustomerTask
from backend.models.customer_technology import CustomerTechnology
from backend.models.intelligence_import import IntelligenceImport, PartnerPipeline
from backend.models.sales_note import SalesNote
from backend.models.use_case import Customer, User
from backend.services import account_health as health
from backend.services import customer_intelligence as intelligence
from backend.services.customer_contact_service import contact_coverage_for
from backend.services.customer_engagement_service import promote_task
from fastapi import HTTPException
from sqlalchemy import event

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
ADMIN = {"username": "admin", "is_admin": 1}


def headers(username="admin"):
    return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}


@pytest.fixture
def accounts(db_session):
    rows = [Customer(name=f"Synthetic E5 {i}") for i in range(2)]
    db_session.add_all(rows)
    db_session.commit()
    return rows


@contextmanager
def statements(db):
    sql = []
    def record(conn, cursor, statement, parameters, context, executemany):
        sql.append(statement)
    event.listen(db.bind, "before_cursor_execute", record)
    try:
        yield sql
    finally:
        event.remove(db.bind, "before_cursor_execute", record)


def tech(db, cid, **values):
    row = CustomerTechnology(customer_id=cid, name="Synthetic technology", category="software", **values)
    db.add(row)
    db.flush()
    return row


def batch(db, cid, amounts):
    row = IntelligenceImport(file_name="synthetic.csv", file_sha256="e" * 64, file_data=b"synthetic",
                             total_rows=len(amounts), matched_accounts=1, matched_rows=len(amounts),
                             unmatched_accounts=0, unmatched_report="[]", imported_by="admin",
                             created_at=NOW.replace(tzinfo=None))
    db.add(row)
    db.flush()
    for i, (acv, tcv) in enumerate(amounts):
        db.add(PartnerPipeline(import_id=row.id, customer_id=cid, customer_account_name="Synthetic",
                               opportunity_number=f"e5-{i}", opportunity_name="Synthetic renewal",
                               current_contract_end_date=NOW.date(), est_acv_usd=acv, est_tcv_usd=tcv))
    db.flush()
    return row


def test_empty_shape_nulls_determinism_and_query_budget(db_session, accounts):
    cid = accounts[0].id
    with statements(db_session) as sql:
        result = health.health_components_for(db_session, ADMIN, cid, NOW)
    assert len(sql) <= 14
    assert result == health.health_components_for(db_session, ADMIN, cid, NOW)
    assert set(result) == {"customer_id", "calc_version", "as_of", "components"}
    assert result["calc_version"] == "account-health/1"
    components = result["components"]
    assert set(components) == {"engagement", "renewals", "buying_coverage", "tasks", "eol", "data_freshness"}
    assert components["engagement"] == {"last_contacted": None, "days_since": None,
        "basis": contact_coverage_for(db_session, cid)["last_contacted_basis"]}
    assert components["renewals"]["exposure"] == {"acv": None, "tcv": None, "coverage": "no_data"}
    assert set(components["renewals"]) == {"snapshot", "counts", "exposure", "basis"}
    assert set(components["buying_coverage"]) == {"contacts_recorded", "economic_buyer_recorded",
                                                "champion_recorded", "roles", "gaps"}
    assert components["tasks"] == {"open": 0, "in_progress": 0, "overdue": 0, "basis": health.TASK_BASIS}
    assert components["eol"] == {"dated_count": 0, "items": []}
    assert set(components["data_freshness"]) == {"pipeline_import", "rep_import", "rvtools_import",
                                               "latest_note", "latest_activity"}
    assert all(value is None for value in components["data_freshness"].values())
    def assert_no_score(value):
        if isinstance(value, dict):
            assert not {"score", "overall", "health_score"} & value.keys()
            for child in value.values():
                assert_no_score(child)
    assert_no_score(result)


@pytest.mark.parametrize("amounts, expected", [
    ([(0, 0)], {"acv": 0.0, "tcv": 0.0, "coverage": "complete"}),
    ([(10.12, 20.23), (2.34, 4.56)], {"acv": 12.46, "tcv": 24.79, "coverage": "complete"}),
    ([(10, 20), (None, None)], {"acv": 10.0, "tcv": 20.0, "coverage": "partial"}),
    ([(None, None)], {"acv": None, "tcv": None, "coverage": "partial"}),
])
def test_renewal_exposure_and_populated_budget(db_session, accounts, amounts, expected):
    cid = accounts[0].id
    imported = batch(db_session, cid, amounts)
    imported_id = imported.id
    tech(db_session, cid, end_of_support_date=NOW.date())
    db_session.commit()
    with statements(db_session) as sql:
        result = health.health_components_for(db_session, ADMIN, cid, NOW)
    assert len(sql) <= 14
    assert result["components"]["renewals"]["exposure"] == expected
    assert result["components"]["renewals"]["snapshot"]["import_id"] == imported_id
    assert result["components"]["data_freshness"]["pipeline_import"].startswith("2026-11-04T12:00:00")
    assert health.health_components_for(db_session, ADMIN, accounts[1].id, NOW)["components"]["renewals"]["snapshot"] is None


def test_partial_lines_within_one_opportunity_stay_partial(db_session, accounts):
    cid = accounts[0].id
    imported = batch(db_session, cid, [(10, 20), (None, None)])
    db_session.query(PartnerPipeline).filter_by(import_id=imported.id).update({"opportunity_number": "same"})
    db_session.commit()
    result = health.health_components_for(db_session, ADMIN, cid, NOW)
    assert result["components"]["renewals"]["exposure"] == {"acv": 10, "tcv": 20, "coverage": "partial"}


def test_engagement_tasks_due_boundaries_and_freshness(db_session, accounts):
    cid = accounts[0].id
    db_session.add(SalesNote(customer_id=cid, category="meeting", title="Synthetic note", content="Synthetic",
                             note_date=NOW.date() - timedelta(days=4)))
    db_session.add(CustomerActivity(customer_id=cid, type="call", occurred_at=(NOW - timedelta(days=2)).replace(tzinfo=None),
                                    actor="admin", created_by="admin"))
    for status, day, instant in [("open", NOW.date(), None), ("open", NOW.date()-timedelta(days=1), None),
                                  ("in_progress", None, NOW.replace(tzinfo=None)),
                                  ("in_progress", None, (NOW-timedelta(seconds=1)).replace(tzinfo=None)),
                                  ("completed", NOW.date()-timedelta(days=5), None)]:
        db_session.add(CustomerTask(customer_id=cid, title="Synthetic task", created_by="admin", status=status,
                                    due_date=day, due_at=instant))
    db_session.commit()
    result = health.health_components_for(db_session, ADMIN, cid, NOW)["components"]
    assert result["engagement"]["days_since"] == 2
    assert result["engagement"]["basis"] == contact_coverage_for(db_session, cid)["last_contacted_basis"]
    assert result["tasks"] == {"open": 2, "in_progress": 2, "overdue": 2, "basis": health.TASK_BASIS}
    assert result["data_freshness"]["latest_note"] == "2026-10-31"
    assert result["data_freshness"]["latest_activity"].startswith("2026-11-02T12:00:00")


def test_eol_order_total_and_cap(db_session, accounts):
    cid = accounts[0].id
    ids = []
    for criticality in (None, "low", "medium", "high", "critical", "critical"):
        ids.append(tech(db_session, cid, end_of_support_date=NOW.date(), business_criticality=criticality).id)
    first = tech(db_session, cid, end_of_support_date=NOW.date()-timedelta(days=1)).id
    tech(db_session, accounts[1].id, end_of_support_date=NOW.date()-timedelta(days=2))
    db_session.commit()
    result = health.health_components_for(db_session, ADMIN, cid, NOW)["components"]["eol"]
    assert result["dated_count"] == 7
    assert [item["id"] for item in result["items"]] == [first, ids[4], ids[5], ids[3], ids[2]]
    assert set(result["items"][0]) == {"id", "name", "vendor", "end_of_support_date", "eol_source",
                                      "lifecycle_state", "business_criticality"}


def test_health_authorizes_before_components(client, db_session, accounts):
    outsider = User(username="e5_outsider", email="e5@test.local", hashed_password="unused",
                    approved=1, is_active=1, is_admin=0)
    db_session.add(outsider)
    db_session.commit()
    cid = accounts[0].id
    with statements(db_session) as sql:
        with pytest.raises(HTTPException) as exc:
            health.health_components_for(db_session, {"username": outsider.username}, cid, NOW)
    assert exc.value.status_code == 403
    assert not any("customer_technologies" in statement or "partner_pipeline" in statement for statement in sql)
    for target in (cid, 999999):
        response = client.get(f"/api/customers/{target}/health/", headers=headers(outsider.username))
        assert response.status_code == 404 and response.json() == {"detail": "Customer not found"}
    assert client.get(f"/api/customers/{cid}/health/", headers=headers()).status_code == 200
    assert client.get(f"/api/customers/{cid}/health/").status_code == 401


def test_eol_attention_firing_severity_legacy_and_global_cap(db_session, accounts):
    cid = accounts[0].id
    undated = tech(db_session, cid, lifecycle_state="eol", business_criticality="critical").id
    dated = []
    for criticality in ("critical", "high", "medium", "low", None, "critical"):
        dated.append(tech(db_session, cid, lifecycle_state="current", business_criticality=criticality,
                          end_of_support_date=NOW.date()).id)
    db_session.commit()
    args = (db_session, cid, {"critical_tech_at_risk": [], "total": 1},
            {"unprocessed_count": 0}, {"total_notes": 1, "notes_stale": False}, None)
    legacy = intelligence._opportunities_section(*args)
    # No EOL parameter means the existing legacy result is unchanged.
    assert legacy == []
    eol = health.dated_eol_for(db_session, cid)
    cards = intelligence._opportunities_section(*args, eol=eol)
    attention = [card for card in cards if card["type"] == "eol_attention"]
    assert len(attention) == 5
    assert undated not in [card["evidence"]["source_id"] for card in attention]
    assert {card["severity"] for card in attention} == {"high", "medium", "low"}
    assert all(card["detail"] == "Dated end of support 2026-11-04; source: not recorded." for card in attention)
    assert intelligence._opportunities_section(*args) == legacy
    fake = [{"id": f"renewal-{i}", "type": "renewal_attention", "severity": "medium"} for i in range(15)]
    crowded = intelligence._opportunities_section(*args, eol=eol, renewal_cards=fake)
    assert len(crowded) == 12
    assert crowded == sorted(crowded, key=lambda card: (intelligence._SEVERITY_RANK[card["severity"]], card["type"], card["id"]))
    workspace = intelligence.get_account_workspace(db_session, cid)
    assert any(card["type"] == "eol_attention" for card in workspace["opportunities"])


def test_eol_task_promotion_same_account_and_idempotency(db_session, accounts):
    source = tech(db_session, accounts[0].id, end_of_support_date=NOW.date())
    source_id = source.id
    cid = accounts[0].id
    other_id = accounts[1].id
    db_session.commit()
    payload = {"source_type": "eol_attention", "source_id": source_id}
    with pytest.raises(HTTPException) as exc:
        promote_task(db_session, other_id, payload, "admin")
    assert exc.value.status_code == 422 and exc.value.detail == "Unknown or out-of-scope promotion source"
    first = promote_task(db_session, cid, payload, "admin")
    second = promote_task(db_session, cid, payload, "admin")
    assert first["created"] and not second["created"]
    assert first["task"]["id"] == second["task"]["id"]
    assert first["task"]["title"] == "Review EOL: Synthetic technology"
    assert first["task"]["source_key"] == f"eol_attention:{source_id}"


@pytest.mark.parametrize("kind, grants, write_status", [
    ("owner", None, 201), ("auditor", None, 403),
    ("inside_sales", {"tasks": "contribute"}, 201),
    ("inside_sales", {"tasks": "read"}, 403),
    ("inside_sales", {"contacts": "contribute"}, 403),
])
def test_eol_promotion_http_permissions(client, db_session, accounts, kind, grants, write_status):
    from backend.models.account_membership import AccountMembership
    from backend.models.use_case import CustomerUser

    cid = accounts[0].id
    source_id = tech(db_session, cid, end_of_support_date=NOW.date()).id
    user = User(username="e5_matrix", approved=1, is_active=1, is_admin=0,
                sales_role="auditor" if kind == "auditor" else "rep")
    db_session.add(user)
    db_session.flush()
    if kind == "inside_sales":
        db_session.add(AccountMembership(customer_id=cid, user_id=user.id, role=kind, section_grants=grants))
    else:
        db_session.add(CustomerUser(customer_id=cid, user_id=user.id, role=kind))
    db_session.commit()
    assert client.get(f"/api/customers/{cid}/health/", headers=headers("e5_matrix")).status_code == 200
    response = client.post(f"/api/customers/{cid}/tasks/promote/", headers=headers("e5_matrix"),
                           json={"source_type": "eol_attention", "source_id": source_id})
    assert response.status_code == write_status, response.text
    if write_status == 201:
        second = client.post(f"/api/customers/{cid}/tasks/promote/", headers=headers("e5_matrix"),
                             json={"source_type": "eol_attention", "source_id": source_id})
        assert second.status_code == 200 and second.json()["created"] is False
