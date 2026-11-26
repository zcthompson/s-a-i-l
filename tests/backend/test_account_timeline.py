"""Account 360 timeline + QBR cadence — synthetic acceptance tests."""

import base64
import json
from contextlib import contextmanager
from datetime import UTC, date, datetime

import pytest
from backend.auth import create_access_token
from backend.models.account_strategy import AccountStrategySnapshot
from backend.models.collaboration import AuditLog, SystemConfig
from backend.models.customer_contact import CustomerContact
from backend.models.customer_engagement import CustomerActivity, CustomerTask
from backend.models.intelligence_import import IntelligenceImport, PartnerPipeline
from backend.models.rep_intelligence import RepIntelligenceImport, RepIntelligenceRow
from backend.models.rvtools_import import RvToolsImport
from backend.models.sales_note import SalesNote
from backend.models.use_case import Base, Customer, CustomerUser, User
from backend.services import account_qbr
from backend.services import account_timeline as timeline
from backend.services.customer_contact_service import contact_coverage_for
from sqlalchemy import event, func, select

NOW = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
SOURCE_TABLES = ("sales_notes", "customer_activities", "customer_tasks", "customer_contacts",
                 "intelligence_imports", "rep_intelligence_imports", "rvtools_imports",
                 "account_strategy_snapshots", "audit_logs", "system_config")


def headers(username="admin"):
    return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}


@pytest.fixture()
def account(db_session):
    customer = Customer(name="Synthetic E1 account", created_at=datetime(2026, 9, 1))
    other = Customer(name="Synthetic E1 other", created_at=datetime(2026, 9, 1))
    db_session.add_all([customer, other])
    db_session.commit()
    return customer, other


def url(customer_id, query=""):
    return f"/api/customers/{customer_id}/timeline/{query}"


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


def note(db, cid, day, title="Synthetic note", **kw):
    row = SalesNote(customer_id=cid, category="meeting", title=title, content=kw.pop("content", "Synthetic body"),
                    note_date=day, **kw)
    db.add(row)
    db.flush()
    return row


def activity(db, cid, kind="call", at=None, day=None, **kw):
    row = CustomerActivity(customer_id=cid, type=kind, occurred_at=at, occurred_date=day,
                           actor=kw.pop("actor", "synthetic_rep"), created_by="admin", **kw)
    db.add(row)
    db.flush()
    return row


def pipeline_batch(db, cid, created):
    batch = IntelligenceImport(file_name="synthetic.csv", file_sha256="a" * 64, file_data=b"synthetic",
                               total_rows=1, matched_accounts=1, matched_rows=1, unmatched_accounts=0,
                               unmatched_report="[]", imported_by="admin", created_at=created)
    db.add(batch)
    db.flush()
    db.add(PartnerPipeline(import_id=batch.id, customer_id=cid, customer_account_name="Synthetic",
                           opportunity_name="Synthetic renewal"))
    db.flush()
    return batch


def audit(db, cid, action, details, created, username="synthetic_admin"):
    row = AuditLog(user_id=1, username=username, action=action, customer_id=cid, target_id=2,
                   details=details if isinstance(details, str) else json.dumps(details), created_at=created)
    db.add(row)
    db.flush()
    return row


def cadence(db, value, value_type="integer"):
    column = {"integer": "integer_value", "string": "string_value"}[value_type]
    db.add(SystemConfig(category="engagement", key="qbr_cadence_days", value_type=value_type,
                        **{column: value}))
    db.flush()


def populated(db, cid):
    """Mixed-date fixture across every source (one row each, plus ties)."""
    task = CustomerTask(customer_id=cid, title="Send proposal", status="completed", completed_by="synthetic_rep",
                        completed_at=datetime(2026, 10, 6, 12, 0), created_by="admin",
                        updated_at=datetime(2026, 10, 6, 12, 0))
    contact = CustomerContact(customer_id=cid, display_name="Synthetic Buyer", title="VP Synthetic",
                              created_at=datetime(2026, 10, 4, 10, 0), updated_at=datetime(2026, 10, 4, 10, 0))
    snapshot = AccountStrategySnapshot(customer_id=cid, plan_number=3, note="Synthetic publish",
                                       content={"version": 1}, published_by="admin",
                                       published_at=datetime(2026, 10, 3, 8, 0))
    db.add_all([task, contact, snapshot])
    db.flush()
    rows = {
        "task": task, "contact": contact, "snapshot": snapshot,
        "instant": activity(db, cid, "meeting", at=datetime(2026, 10, 5, 9, 0), outcome="Synthetic outcome"),
        "note": note(db, cid, date(2026, 10, 5), author="synthetic_author"),
        "dated_activity": activity(db, cid, "demo", day=date(2026, 10, 5)),
        "pipeline": pipeline_batch(db, cid, datetime(2026, 10, 5, 0, 0)),
        "membership": audit(db, cid, "membership.add", {"role": "co_owner"}, datetime(2026, 10, 1, 7, 0)),
    }
    rep = RepIntelligenceImport(file_name="rep.csv", file_sha256="b" * 64, file_data=b"synthetic", total_rows=1,
                                imported_rows=1, imported_with_issues=0, skipped_rows=0, status="completed",
                                technologies_created=0, technologies_refreshed=0, imported_by="admin",
                                created_at=datetime(2026, 9, 30, 8, 0))
    db.add(rep)
    db.flush()
    db.add(RepIntelligenceRow(import_id=rep.id, source_row=1, customer_id=cid, status="imported", issues=[]))
    rv = RvToolsImport(customer_id=cid, file_name="rv.xlsx", file_sha256="c" * 64, file_data=b"synthetic",
                       host_count=1, vm_count=1, datastore_count=1, license_count=1, vcenter="vc-synthetic",
                       imported_by="admin", created_at=datetime(2026, 9, 29, 8, 0))
    db.add(rv)
    db.commit()
    rows.update(rep=rep, rv=rv)
    return rows


# ── gate ────────────────────────────────────────────────────────────────


def test_unknown_and_outsider_are_404_before_any_source_query(client, db_session, account):
    customer, other = account
    populated(db_session, customer.id)
    outsider = User(username="synthetic_outsider", email="synthetic_outsider@test.local", hashed_password="unused",
                    is_admin=0, approved=1, is_active=1, sales_role="rep")
    db_session.add(outsider)
    db_session.flush()
    db_session.add(CustomerUser(customer_id=other.id, user_id=outsider.id, role="owner"))
    db_session.commit()
    for path, who in ((url(999999), "admin"), (url(customer.id), outsider.username),
                      (url(customer.id, "?limit=0&cursor=%%%"), outsider.username)):
        with statements(db_session) as sql:
            response = client.get(path, headers=headers(who))
        assert response.status_code == 404
        assert response.json() == {"detail": "Customer not found"}
        touched = [s for s in sql if any(f" {t}" in s for t in SOURCE_TABLES)]
        assert touched == []
    assert client.get(url(other.id), headers=headers(outsider.username)).status_code == 200
    assert client.get(url(customer.id)).status_code == 401


@pytest.mark.parametrize("value", ["0", "101", "-1", "abc", "1.5", ""])
def test_limit_validation_exact(client, account, value):
    response = client.get(url(account[0].id, f"?limit={value}"), headers=headers())
    assert response.status_code == 422
    assert response.json() == {"detail": "limit must be an integer between 1 and 100"}


@pytest.mark.parametrize("cursor", [
    "%%%", "bm90LWpzb24", base64.urlsafe_b64encode(b"[1,2]").decode(),
    base64.urlsafe_b64encode(json.dumps({"ts": None, "kind": "bogus", "id": 1}).encode()).decode(),
    base64.urlsafe_b64encode(json.dumps({"ts": "not-a-date", "kind": "note", "id": 1}).encode()).decode(),
    base64.urlsafe_b64encode(json.dumps({"ts": None, "kind": "note", "id": "1"}).encode()).decode(),
    base64.urlsafe_b64encode(json.dumps({"ts": None, "kind": "note"}).encode()).decode(),
])
def test_malformed_cursor_400_exact(client, account, cursor):
    response = client.get(url(account[0].id), params={"cursor": cursor}, headers=headers())
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid cursor"}


# ── merge + shape ───────────────────────────────────────────────────────


def test_merge_order_shape_and_imported_labels(client, db_session, account):
    cid = account[0].id
    rows = populated(db_session, cid)
    second_note = note(db_session, cid, date(2026, 10, 5), title="Synthetic later note")
    db_session.commit()
    body = client.get(url(cid), headers=headers()).json()
    assert set(body) == {"customer_id", "qbr", "items", "next_cursor", "more"}
    assert body["customer_id"] == cid and body["more"] is False and body["next_cursor"] is None
    order = [(i["kind"], i["id"]) for i in body["items"]]
    assert order == [
        ("task", rows["task"].id),                    # 2026-10-06 12:00 instant
        ("activity", rows["instant"].id),             # 2026-10-05 09:00 instant beats same-day date-only
        ("note", second_note.id),                     # 2026-10-05 date-only, kind order, id desc
        ("note", rows["note"].id),
        ("activity", rows["dated_activity"].id),      # 2026-10-05 date-only, after notes by kind order
        ("pipeline_import", rows["pipeline"].id),     # 2026-10-05 00:00 instant ties midnight → kind order
        ("contact", rows["contact"].id),
        ("strategy_snapshot", rows["snapshot"].id),
        ("membership", rows["membership"].id),
        ("rep_import", rows["rep"].id),
        ("rvtools_import", rows["rv"].id),
    ]
    by_kind = {}
    for item in body["items"]:
        assert set(item) == {"kind", "id", "title", "detail", "actor", "timestamp", "date_only",
                             "imported", "source_ref"}
        by_kind.setdefault(item["kind"], item)
    assert by_kind["task"] == {
        "kind": "task", "id": rows["task"].id, "title": "Task completed: Send proposal", "detail": None,
        "actor": "synthetic_rep", "timestamp": "2026-10-06T12:00:00+00:00", "date_only": False,
        "imported": False, "source_ref": f"module=task&id={rows['task'].id}"}
    assert by_kind["note"]["timestamp"] == "2026-10-05" and by_kind["note"]["date_only"] is True
    assert by_kind["activity"]["title"] == "Meeting" and by_kind["activity"]["detail"] == "Synthetic outcome"
    assert by_kind["contact"]["title"] == "Contact added: Synthetic Buyer"
    assert by_kind["contact"]["detail"] == "VP Synthetic" and by_kind["contact"]["actor"] is None
    assert by_kind["strategy_snapshot"]["title"] == "Strategy plan #3 published"
    assert by_kind["strategy_snapshot"]["actor"] is None
    imported = {i["kind"]: (i["title"], i["detail"], i["imported"]) for i in body["items"] if i["imported"]}
    assert imported == {
        "pipeline_import": (f"Pipeline import #{rows['pipeline'].id}", "imported admin", True),
        "rep_import": (f"Rep intelligence import #{rows['rep'].id}", "imported admin", True),
        "rvtools_import": (f"RVTools import #{rows['rv'].id}", "vCenter vc-synthetic", True),
    }
    assert all(not i["imported"] for i in body["items"]
               if i["kind"] not in ("pipeline_import", "rep_import", "rvtools_import"))


def test_note_author_null_kept_and_detail_window(db_session, account):
    cid = account[0].id
    note(db_session, cid, date(2026, 10, 1), content="word " * 100)
    note(db_session, cid, None, title="Undated note excluded")
    db_session.commit()
    items = timeline.build_timeline(db_session, cid, now=NOW)["items"]
    assert len(items) == 1
    assert items[0]["actor"] is None
    assert len(items[0]["detail"]) == 160 and items[0]["detail"].endswith("…")


def test_task_and_contact_variants(db_session, account):
    cid = account[0].id
    db_session.add_all([
        CustomerTask(customer_id=cid, title="Open one", status="open", assignee=None, created_by="admin",
                     updated_at=datetime(2026, 10, 2, 9, 0)),
        CustomerTask(customer_id=cid, title="Moving", status="in_progress", assignee="synthetic_rep",
                     created_by="admin", updated_at=datetime(2026, 10, 3, 9, 0)),
        CustomerTask(customer_id=cid, title="Dropped", status="cancelled", created_by="admin",
                     updated_at=datetime(2026, 10, 4, 9, 0)),
        CustomerContact(customer_id=cid, display_name="Gone Contact", title="Old title", archived=True,
                        created_at=datetime(2026, 9, 1), updated_at=datetime(2026, 10, 1, 9, 0)),
    ])
    db_session.commit()
    items = timeline.build_timeline(db_session, cid, now=NOW)["items"]
    assert [(i["title"], i["actor"], i["detail"], i["timestamp"]) for i in items] == [
        ("Task in_progress: Moving", "synthetic_rep", None, "2026-10-03T09:00:00+00:00"),
        ("Task open: Open one", None, None, "2026-10-02T09:00:00+00:00"),
        ("Contact archived: Gone Contact", None, None, "2026-10-01T09:00:00+00:00"),
    ]


# ── pagination + caps ───────────────────────────────────────────────────


def test_contact_cap_uses_emitted_timestamp_across_pages(client, db_session, account):
    cid = account[0].id
    # Edits to old active contacts do not create timeline events; they must
    # not push newer creation and archive events out of the bounded source.
    old = [CustomerContact(customer_id=cid, display_name=f"Old {i}", archived=False,
                           created_at=datetime(2026, 9, 1), updated_at=datetime(2026, 11, 1))
           for i in range(21)]
    newer = [CustomerContact(customer_id=cid, display_name=f"New {i}", archived=False,
                             created_at=datetime(2026, 10, 10), updated_at=datetime(2026, 10, 10))
             for i in range(2)]
    archived = CustomerContact(customer_id=cid, display_name="Archived", archived=True,
                               created_at=datetime(2026, 8, 1), updated_at=datetime(2026, 10, 11))
    db_session.add_all([*old, *newer, archived])
    db_session.commit()
    expected = [archived.id, *sorted((r.id for r in newer), reverse=True),
                *sorted((r.id for r in old), reverse=True)[:17]]
    seen, cursor = [], None
    while True:
        params = {"limit": 7, **({"cursor": cursor} if cursor else {})}
        response = client.get(url(cid), params=params, headers=headers())
        assert response.status_code == 200
        body = response.json()
        seen.extend(item["id"] for item in body["items"] if item["kind"] == "contact")
        if not body["more"]:
            break
        cursor = body["next_cursor"]
    assert seen == expected


def test_cursor_pagination_exact_pages_no_overlap(client, db_session, account):
    cid = account[0].id
    notes = [note(db_session, cid, date(2026, 10, d)) for d in range(1, 8)]
    db_session.commit()
    expected = [n.id for n in reversed(notes)]
    seen, cursor, pages = [], None, []
    while True:
        params = {"limit": 3, **({"cursor": cursor} if cursor else {})}
        body = client.get(url(cid), params=params, headers=headers()).json()
        pages.append([i["id"] for i in body["items"]])
        seen.extend(pages[-1])
        if not body["more"]:
            assert body["next_cursor"] is None
            break
        assert body["next_cursor"]
        cursor = body["next_cursor"]
    assert pages == [expected[0:3], expected[3:6], expected[6:7]]
    assert seen == expected and len(set(seen)) == len(seen)
    decoded = json.loads(base64.urlsafe_b64decode(timeline.encode_cursor(
        {"timestamp": "2026-10-05", "kind": "note", "id": notes[4].id})))
    assert decoded == {"ts": "2026-10-05", "kind": "note", "id": notes[4].id}


def test_per_source_caps(db_session, account):
    cid = account[0].id
    for i in range(55):
        note(db_session, cid, date(2026, 1, 1) + (date(2026, 1, 2) - date(2026, 1, 1)) * i)
    for i in range(12):
        audit(db_session, cid, "membership.remove", {"role": "co_owner"}, datetime(2026, 9, 1, i))
    db_session.commit()
    body = timeline.build_timeline(db_session, cid, limit=100, now=NOW)
    kinds = [i["kind"] for i in body["items"]]
    assert kinds.count("note") == timeline.CAPS["note"] == 50
    assert kinds.count("membership") == timeline.CAPS["membership"] == 10
    assert body["more"] is False and body["next_cursor"] is None
    # the newest 50 notes are the ones kept
    first_note = next(i for i in body["items"] if i["kind"] == "note")
    assert first_note["timestamp"] == (date(2026, 1, 1) + (date(2026, 1, 2) - date(2026, 1, 1)) * 54).isoformat()


# ── membership whitelist ────────────────────────────────────────────────


def test_membership_whitelist_only(db_session, account):
    cid = account[0].id
    secret = {"before": [{"user_id": 9, "role": "SECRET_BEFORE"}], "after": [{"secret": "SECRET_AFTER"}],
              "extra": "SECRET_EXTRA"}
    audit(db_session, cid, "membership.add", {**secret, "role": "co_owner"}, datetime(2026, 10, 5))
    audit(db_session, cid, "membership.remove", {**secret, "role": "inside_sales"}, datetime(2026, 10, 4))
    audit(db_session, cid, "ownership.transfer", {**secret, "previous_owners": [3], "review": False},
          datetime(2026, 10, 3))
    audit(db_session, cid, "ownership.transfer", {**secret, "new_username": "synthetic_new_owner"},
          datetime(2026, 10, 2))
    audit(db_session, cid, "membership.add", "not json {", datetime(2026, 10, 1))
    audit(db_session, cid, "membership.grants", {"role": "co_owner"}, datetime(2026, 10, 6))
    audit(db_session, account[1].id, "membership.add", {"role": "co_owner"}, datetime(2026, 10, 6))
    db_session.commit()
    items = timeline.build_timeline(db_session, cid, now=NOW)["items"]
    assert [(i["title"], i["detail"], i["actor"], i["source_ref"]) for i in items] == [
        ("Membership added: co_owner", None, "synthetic_admin", None),
        ("Membership removed: inside_sales", None, "synthetic_admin", None),
        ("Ownership transferred to not recorded", None, "synthetic_admin", None),
        ("Ownership transferred to synthetic_new_owner", None, "synthetic_admin", None),
        ("Membership added: not recorded", None, "synthetic_admin", None),
    ]
    assert "SECRET" not in json.dumps(items)


# ── QBR ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("last, state, days_until", [
    (date(2026, 8, 20), "current", 15),    # due 2026-11-18 → 15 days → current
    (date(2026, 8, 19), "due_soon", 14),   # boundary 14
    (date(2026, 8, 5), "due_soon", 0),     # due today (2026-11-03)
    (date(2026, 8, 4), "overdue", -1),
])
def test_qbr_states_and_boundaries(db_session, account, last, state, days_until):
    cid = account[0].id
    activity(db_session, cid, "qbr", day=last - (date(2026, 1, 2) - date(2026, 1, 1)) * 30)
    activity(db_session, cid, "qbr", day=last)
    activity(db_session, cid, "call", day=date(2026, 11, 1))
    db_session.commit()
    result = account_qbr.qbr_state_for(db_session, cid, now=NOW)
    due = date.fromordinal(last.toordinal() + 90)
    assert result == {"last_qbr_date": last.isoformat(), "cadence_days": 90, "next_qbr_due": due.isoformat(),
                      "state": state, "days_until": days_until}
    items = [i for i in timeline.build_timeline(db_session, cid, now=NOW)["items"] if i["kind"] == "qbr"]
    if state == "overdue":
        assert [(i["title"], i["detail"]) for i in items] == [
            ("QBR overdue", f"Last QBR {last.isoformat()}; 1 days overdue")]
    elif state == "due_soon":
        assert [(i["title"], i["detail"]) for i in items] == [
            ("QBR due soon", f"Due {due.isoformat()} (in {days_until} days)")]
    else:
        assert items == []
    for item in items:
        assert item["id"] is None and item["source_ref"] is None and item["imported"] is False


def test_qbr_not_recorded_and_occurred_at(db_session, account):
    cid = account[0].id
    assert account_qbr.qbr_state_for(db_session, cid, now=NOW) == {
        "last_qbr_date": None, "cadence_days": 90, "next_qbr_due": None, "state": "not_recorded",
        "days_until": None}
    assert timeline.build_timeline(db_session, cid, now=NOW)["items"] == []
    activity(db_session, cid, "qbr", at=datetime(2026, 10, 1, 23, 30))
    db_session.commit()
    assert account_qbr.qbr_state_for(db_session, cid, now=NOW)["last_qbr_date"] == "2026-10-01"
    assert account_qbr.QBR_BASIS == "activity type qbr + system_config engagement.qbr_cadence_days (default 90)"


@pytest.mark.parametrize("value, value_type, expected", [
    (60, "integer", 60), ("60", "string", 60), (10, "integer", 90), (400, "integer", 90),
    ("abc", "string", 90), (None, None, 90),
])
def test_qbr_cadence_from_system_config(db_session, account, value, value_type, expected):
    cid = account[0].id
    if value_type:
        cadence(db_session, value, value_type)
    activity(db_session, cid, "qbr", day=date(2026, 10, 1))
    db_session.commit()
    result = account_qbr.qbr_state_for(db_session, cid, now=NOW)
    assert result["cadence_days"] == expected
    assert result["next_qbr_due"] == date.fromordinal(date(2026, 10, 1).toordinal() + expected).isoformat()


def test_route_qbr_is_service_verbatim(client, db_session, account):
    cid = account[0].id
    activity(db_session, cid, "qbr", day=date(2020, 1, 1))
    db_session.commit()
    body = client.get(url(cid), headers=headers()).json()
    assert body["qbr"] == account_qbr.qbr_state_for(db_session, cid)
    assert body["qbr"]["state"] == "overdue"


# ── budgets + invariants ────────────────────────────────────────────────


def test_query_budget_populated(client, db_session, account):
    cid = account[0].id
    populated(db_session, cid)
    activity(db_session, cid, "qbr", day=date(2026, 9, 1))
    cadence(db_session, 60)
    db_session.commit()
    with statements(db_session) as sql:
        response = client.get(url(cid), headers=headers())
    assert response.status_code == 200
    assert len(sql) <= 13, sql
    with statements(db_session) as service_sql:
        timeline.build_timeline(db_session, cid, now=NOW)
    assert len(service_sql) == 12
    assert not any("UNION" in s.upper() for s in service_sql)


def _row_counts(db):
    return {t.name: db.execute(select(func.count()).select_from(t)).scalar() for t in Base.metadata.sorted_tables}


def test_no_writes(client, db_session, account):
    cid = account[0].id
    populated(db_session, cid)
    activity(db_session, cid, "qbr", day=date(2026, 9, 1))
    db_session.commit()
    before = _row_counts(db_session)
    with statements(db_session) as sql:
        timeline.build_timeline(db_session, cid, now=NOW)
    assert all(s.lstrip().upper().startswith("SELECT") for s in sql)
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    assert client.get(url(cid), headers=headers()).status_code == 200
    assert _row_counts(db_session) == before


def test_engagement_strings_untouched(db_session, account):
    cid = account[0].id
    activity(db_session, cid, "meeting", at=datetime(2026, 10, 2, 9, 0))
    note(db_session, cid, date(2026, 10, 4))
    pipeline_batch(db_session, cid, datetime(2026, 10, 30, 9, 0))
    db_session.commit()
    before = json.dumps(contact_coverage_for(db_session, cid), sort_keys=True)
    timeline.build_timeline(db_session, cid, now=NOW)
    after = json.dumps(contact_coverage_for(db_session, cid), sort_keys=True)
    assert after == before
    assert json.loads(after)["last_contacted"] == "2026-10-04"


@pytest.mark.parametrize("kind", [[], {}])
def test_nested_kind_is_an_invalid_cursor(kind):
    cursor = base64.urlsafe_b64encode(json.dumps({"ts": None, "kind": kind, "id": 1}).encode()).decode()
    with pytest.raises(timeline.InvalidCursor):
        timeline.decode_cursor(cursor)


@pytest.mark.parametrize("field, value", [
    ("kind", []), ("kind", {}), ("kind", None), ("kind", True), ("kind", 1),
    ("ts", []), ("ts", {}), ("ts", True), ("ts", 1), ("ts", ""),
    ("ts", "0001-01-01T00:00:00+23:59"), ("ts", "9999-12-31T23:59:59-23:59"),
    ("id", []), ("id", {}), ("id", True), ("id", 1.5),
    ("id", -1), ("id", 0), ("id", 2**63),
])
def test_invalid_cursor_fields_return_400_without_source_reads(client, db_session, account, field, value):
    cid = account[0].id
    payload = {"ts": None, "kind": "note", "id": 1, field: value}
    cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    with statements(db_session) as sql:
        response = client.get(url(cid), params={"cursor": cursor}, headers=headers())
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid cursor"}
    assert not any(f" {table}" in statement for statement in sql for table in SOURCE_TABLES)


@pytest.mark.parametrize("cursor", [
    "a" * 1025,
    base64.urlsafe_b64encode(b'{"ts":null,"kind":"note","id":1}').decode() + "!",
    "a" * 4 + "☃",
    base64.urlsafe_b64encode(b"\xff").decode(),
])
def test_invalid_cursor_encoding_and_size_return_400(client, account, cursor):
    response = client.get(url(account[0].id), params={"cursor": cursor}, headers=headers())
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid cursor"}


def test_cursor_validation_runs_after_authorization(client, db_session, account, monkeypatch):
    cid = account[0].id
    outsider = User(username="cursor_outsider", email="cursor_outsider@test.local", hashed_password="unused",
                    is_admin=0, approved=1, is_active=1, sales_role="rep")
    db_session.add(outsider)
    db_session.commit()

    def unexpected_decode(cursor):
        pytest.fail("Cursor decoded before authorization")

    monkeypatch.setattr(timeline, "decode_cursor", unexpected_decode)
    for target, auth, status in ((cid, {}, 401), (999999, headers(), 404),
                                  (cid, headers("cursor_outsider"), 404)):
        response = client.get(url(target), params={"cursor": "a" * 1025}, headers=auth)
        assert response.status_code == status
        if status == 404:
            assert response.json() == {"detail": "Customer not found"}


@pytest.mark.parametrize("stamp, kind, row_id", [
    ("2026-11-04", "note", 1),
    ("2026-11-04T12:34:56.123456+00:00", "activity", 2**63-1),
    ("2026-11-04T12:34:56-05:00", "task", 2),
    (None, "contact", 3),
    ("2026-11-04", "qbr", None),
])
def test_emitted_cursor_roundtrip_preserves_order_with_optional_padding(stamp, kind, row_id):
    cursor = timeline.encode_cursor({"timestamp": stamp, "kind": kind, "id": row_id})
    instant = (datetime.fromisoformat(stamp).replace(tzinfo=UTC) if stamp and "T" not in stamp
               else datetime.fromisoformat(stamp) if stamp else None)
    expected = timeline._sort_key(instant, kind, row_id)
    assert timeline.decode_cursor(cursor) == expected
    assert timeline.decode_cursor(cursor.rstrip("=")) == expected
