"""Synthetic worklist authorization, flattening and query-budget pins."""
import json
import time
from datetime import UTC, datetime, timedelta, timezone

import pytest
from backend.models.customer_engagement import CustomerActivity, CustomerTask
from backend.models.intelligence_import import IntelligenceImport, PartnerPipeline
from backend.models.use_case import Customer, CustomerUser, User
from backend.services import account_qbr, customer_engagement_service, pipeline_read_model
from backend.services.worklist_service import _renewal_candidates, _renewal_totals, worklist_for
from sqlalchemy import event

from tests.backend.test_customer_contacts import headers, statements

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def seed(db, count=1):
    user = User(username="synthetic_rep", sales_role="rep", approved=1, is_active=1)
    customers = [Customer(name=f"Synthetic work {i:02}") for i in range(count + 1)]
    batch = IntelligenceImport(file_name="synthetic.csv", file_sha256="0" * 64, file_data=b"",
        total_rows=count + 1, matched_accounts=count + 1, matched_rows=count + 1,
        unmatched_accounts=0, unmatched_report="[]", imported_by="synthetic_rep")
    db.add_all([user, batch, *customers])
    db.flush()
    for i, customer in enumerate(customers):
        if i < count:
            db.add(CustomerUser(customer_id=customer.id, user_id=user.id, role="owner"))
        db.add(CustomerActivity(customer_id=customer.id, type="qbr", actor=user.username,
            created_by=user.username, occurred_date=NOW.date() - timedelta(days=91)))
        for j, days in enumerate((-2, 10)):
            db.add(PartnerPipeline(customer_id=customer.id, import_id=batch.id,
                customer_account_name=customer.name, opportunity_name=f"Synthetic renewal {j}",
                opportunity_number=f"{i}-{j}", net_new_vs_renewal="Renewal", source_row=i * 2 + j,
                current_contract_end_date=NOW.date() + timedelta(days=days),
                est_acv_usd=None, est_tcv_usd=123.5))
        db.add(CustomerTask(customer_id=customer.id, title="Synthetic task", assignee=user.username,
            created_by=user.username, due_date=NOW.date()))
    db.commit()
    return {"username": user.username, "user_id": user.id}, [c.id for c in customers]


def test_scope_tasks_budget(db_session, client):
    user, ids = seed(db_session)
    expected = customer_engagement_service.my_tasks(db_session, user, now=NOW)
    with statements(db_session) as sql:
        result = worklist_for(db_session, user, NOW)
    assert len(sql) <= 10
    assert result["generated_at"] == NOW.isoformat()
    assert result["tasks"] == expected and len(expected) == 1
    assert set(expected[0]) == set("id customer_id title detail assignee due_at due_date status completed_by completed_at source_type source_id source_key created_by created_at updated_at version evidence_note_count evidence_activity_count overdue due_soon needs_reassignment customer_name".split())
    assert expected[0]["title"] == "Synthetic task" and expected[0]["customer_id"] == ids[0]
    assert result["renewals"] == [{"customer_id": ids[0], "customer_name": "Synthetic work 00",
        "opportunity_name": "Synthetic renewal 0", "end_date": "2026-11-02", "bucket": "overdue",
        "acv_usd": None, "tcv_usd": 123.5}]
    assert [r["customer_id"] for r in result["qbr"]] == ids[:1]
    assert client.get("/api/worklist/mine/", headers=headers(user["username"])).status_code == 200


def test_empty_budget(db_session):
    db_session.add(User(username="synthetic_empty", is_active=1, approved=1, sales_role="rep"))
    db_session.commit()
    with statements(db_session) as sql:
        result = worklist_for(db_session, {"username": "synthetic_empty"}, NOW)
    assert len(sql) <= 10
    assert result == {"generated_at": NOW.isoformat(), "tasks": [], "renewals": [], "qbr": [], "closing_deals": [],
                      "truncated": {"tasks": False, "renewals": False, "qbr": False, "closing_deals": False}}


@pytest.mark.parametrize("reference,due_date,due_at,expected", [
    (datetime(2025, 1, 1, 23, 59, 59, tzinfo=UTC), "2025-01-01", None, (False, True)),
    (datetime(2025, 1, 2, 0, 0, tzinfo=UTC), "2025-01-01", None, (True, False)),
    (datetime(2025, 1, 1, 19, 0, tzinfo=timezone(timedelta(hours=-5))), "2025-01-02", None, (False, True)),
    (datetime(2025, 1, 2, 0, 0, tzinfo=UTC), None, datetime(2025, 1, 1, 23, 59, 59, 999999), (True, False)),
    (datetime(2025, 1, 2, 0, 0, tzinfo=UTC), None, datetime(2025, 1, 2), (False, False)),
    (datetime(2025, 1, 2, 0, 0, tzinfo=UTC), None, datetime(2025, 1, 3), (False, True)),
    (datetime(2025, 1, 2, 0, 0, tzinfo=UTC), None, datetime(2025, 1, 3, 0, 0, 0, 1), (False, False)),
])
def test_worklist_uses_generated_at_for_task_due_flags(db_session, reference, due_date, due_at, expected):
    user, ids = seed(db_session)
    db_session.query(CustomerTask).delete()
    db_session.add(CustomerTask(customer_id=ids[0], title="Boundary task", assignee=user["username"],
        created_by=user["username"], due_date=datetime.fromisoformat(due_date).date() if due_date else None,
        due_at=due_at))
    db_session.commit()
    result = worklist_for(db_session, user, reference)
    assert result["generated_at"] == reference.astimezone(UTC).isoformat()
    assert len(result["tasks"]) == 1
    assert (result["tasks"][0]["overdue"], result["tasks"][0]["due_soon"]) == expected


def test_cap_order(db_session):
    user, ids = seed(db_session, 23)
    result = worklist_for(db_session, user, NOW)
    assert len(result["renewals"]) == 20
    assert [r["customer_id"] for r in result["renewals"]] == ids[:20]
    assert result["truncated"] == {"tasks": True, "renewals": True, "qbr": True, "closing_deals": False}
    assert len(result["tasks"]) == len(result["qbr"]) == 20
    assert ids[-1] not in {r["customer_id"] for key in ("tasks", "qbr", "renewals")
                           for r in result[key]}


def test_renewal_selected_opportunity_keeps_all_source_lines(db_session):
    user, ids = seed(db_session)
    original = db_session.query(PartnerPipeline).filter_by(customer_id=ids[0],
        opportunity_number="0-0").one()
    original.est_acv_usd = 0.1
    db_session.add(PartnerPipeline(customer_id=ids[0], import_id=original.import_id,
        customer_account_name="Synthetic", opportunity_number="0-0", source_row=999,
        est_acv_usd=0.2, est_tcv_usd=None))
    db_session.commit()
    card = worklist_for(db_session, user, NOW)["renewals"][0]
    assert card["acv_usd"] == 0.3 and card["tcv_usd"] == 123.5


def test_large_worklist_bounds_materialized_rows_and_payload(db_session):
    user, ids = seed(db_session, 100)
    first = db_session.query(PartnerPipeline).filter_by(customer_id=ids[0],
        opportunity_number="0-0").one()
    batch = first.import_id
    db_session.add_all([
        PartnerPipeline(customer_id=ids[0], import_id=batch, customer_account_name="Synthetic",
                        opportunity_number="0-0", source_row=10000 + i, est_acv_usd=0.1)
        for i in range(5000)
    ])
    db_session.add_all([
        CustomerActivity(customer_id=ids[0], type="qbr", actor=user["username"],
                         created_by=user["username"], occurred_date=NOW.date() - timedelta(days=100 + i))
        for i in range(1000)
    ])
    db_session.commit()
    db_session.expunge_all()
    loaded = []

    def record_load(session, instance):
        loaded.append(type(instance))

    event.listen(db_session, "loaded_as_persistent", record_load)
    started = time.perf_counter()
    try:
        with statements(db_session) as sql:
            result = worklist_for(db_session, user, NOW)
    finally:
        elapsed = time.perf_counter() - started
        event.remove(db_session, "loaded_as_persistent", record_load)
    payload_bytes = len(json.dumps(result).encode())
    candidates = _renewal_candidates(db_session, user, NOW.date())
    totals = _renewal_totals(db_session, candidates[:20])
    assert len(candidates) == 21 and len(totals) == 20
    assert len(sql) <= 10
    assert len(loaded) <= 21
    assert PartnerPipeline not in loaded and CustomerActivity not in loaded
    assert all(len(result[key]) == 20 for key in ("tasks", "renewals", "qbr"))
    assert all(result["truncated"][key] for key in ("tasks", "renewals", "qbr"))
    assert result["renewals"][0]["acv_usd"] == 500.0
    assert payload_bytes < 25000
    assert elapsed < 10.0
    print(f"scale: {len(sql)} statements, {len(loaded)} ORM rows, "
          f"{len(candidates)} candidates, {len(totals)} aggregates, "
          f"{payload_bytes} bytes, {elapsed:.3f}s")


def test_renewal_totals_match_reference_with_whitespace_and_unknowns(db_session):
    user, ids = seed(db_session)
    rows = db_session.query(PartnerPipeline).filter_by(customer_id=ids[0],
        opportunity_number="0-0").all()
    first = rows[0]
    first.opportunity_number = "\u00a0ABC\u00a0"
    first.opportunity_name = "  "
    first.est_acv_usd = 1.005
    second = PartnerPipeline(customer_id=ids[0], import_id=first.import_id,
        customer_account_name="Synthetic", opportunity_number="ABC", opportunity_name="Chosen",
        source_row=first.source_row + 1, est_acv_usd=2.005, est_tcv_usd=None)
    db_session.add(second)
    db_session.commit()
    expected = pipeline_read_model.renewal_attention_for_rows([first, second], reference_date=NOW.date())
    reference = expected["buckets"]["overdue"][0]
    actual = worklist_for(db_session, user, NOW)["renewals"][0]
    assert actual["opportunity_name"] == reference["opportunity_name"]
    assert actual["acv_usd"] == reference["est_acv"]["total"]
    assert actual["tcv_usd"] == reference["est_tcv"]["total"]


def test_newer_snapshot_excludes_old_renewal(db_session):
    user, ids = seed(db_session)
    batch = IntelligenceImport(file_name="new.csv", file_sha256="1" * 64, file_data=b"",
        total_rows=1, matched_accounts=1, matched_rows=1, unmatched_accounts=0,
        unmatched_report="[]", imported_by=user["username"])
    db_session.add(batch)
    db_session.flush()
    db_session.add(PartnerPipeline(customer_id=ids[0], import_id=batch.id,
        customer_account_name="Synthetic", opportunity_number="new", source_row=1,
        current_contract_end_date=NOW.date() + timedelta(days=181)))
    db_session.commit()
    assert worklist_for(db_session, user, NOW)["renewals"] == []


@pytest.mark.parametrize("days,state", [(-1, "overdue"), (0, "due_soon"), (14, "due_soon"),
                                         (15, "current"), (None, "not_recorded")])
def test_qbr_equivalence_boundaries(db_session, days, state):
    user, ids = seed(db_session)
    db_session.query(CustomerActivity).delete()
    last = NOW.date() + timedelta(days=days - 90) if days is not None else None
    if last:
        db_session.add_all([
            CustomerActivity(customer_id=ids[0], type="qbr", actor=user["username"],
                created_by=user["username"], occurred_at=datetime.combine(last, datetime.min.time())),
            CustomerActivity(customer_id=ids[0], type="qbr", actor=user["username"],
                created_by=user["username"], occurred_date=last - timedelta(days=3)),
        ])
    db_session.commit()
    pure = account_qbr.qbr_state_from(last, 90, NOW.date())
    assert pure == account_qbr.qbr_state_for(db_session, ids[0], NOW)
    assert pure["state"] == state
    result = worklist_for(db_session, user, NOW)
    assert len(result["qbr"]) == (1 if state in ("due_soon", "overdue") else 0)
    if result["qbr"]:
        assert result["qbr"][0]["days_until"] == days


def test_bucket_priority_days_names_and_excluded_dates(db_session):
    user, ids = seed(db_session, 9)
    db_session.query(CustomerTask).delete()
    rows = db_session.query(PartnerPipeline).order_by(PartnerPipeline.source_row).all()
    # Every account has two cards; replace both dates to pin first-card choice,
    # cross-account urgency, bucket boundaries, and date-less exclusions.
    offsets = [20, -1, -10, 50, 80, 150, 181, None, -1, -100]
    for row in rows:
        index = ids.index(row.customer_id)
        offset = offsets[index]
        row.current_contract_end_date = NOW.date() + timedelta(days=offset) if offset is not None else None
        if row.opportunity_number.endswith("-1") and offset is not None:
            row.current_contract_end_date += timedelta(days=1)
    db_session.commit()
    result = worklist_for(db_session, user, NOW)
    assert [r["customer_id"] for r in result["renewals"]] == [ids[i] for i in (2, 1, 8, 0, 3, 4, 5)]
    assert [r["bucket"] for r in result["renewals"]] == [
        "overdue", "overdue", "overdue", "within_30", "within_60", "within_90", "within_180"]
    assert all(r["opportunity_name"] == "Synthetic renewal 0" for r in result["renewals"])
