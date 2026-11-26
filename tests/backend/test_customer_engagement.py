"""H5 synthetic acceptance: evidence, lifecycle, concurrency, access and delivery."""

import importlib
from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock

import pytest
from backend.models.account_membership import AccountMembership
from backend.models.collaboration import Notification
from backend.models.customer_contact import CustomerContact
from backend.models.customer_engagement import (
    ACTIVITY_TYPES,
    CustomerTask,
    TaskNotificationWindow,
    task_evidence_activities,
    task_evidence_notes,
)
from backend.models.intelligence_import import IntelligenceImport, PartnerPipeline
from backend.models.sales_note import SalesNote
from backend.models.use_case import Customer, CustomerUser, User
from backend.services import customer_engagement_service as service
from backend.services import task_notification_evaluator as evaluator
from backend.services.collaboration_service import CollaborationService
from backend.services.notification_service import connection_manager
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.backend.test_customer_contacts import headers, statements

ACTIVITY_KEYS = set("id customer_id type occurred_at occurred_date actor source outcome created_by created_at updated_at attendees".split())
TASK_KEYS = set("id customer_id title detail assignee due_at due_date status completed_by completed_at source_type source_id source_key created_by created_at updated_at version evidence_note_count evidence_activity_count overdue due_soon needs_reassignment".split())
NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


@pytest.fixture()
def world(db_session):
    customers = [Customer(name=f"Synthetic H5 {i}") for i in range(2)]
    users = [User(username=name, approved=1, is_active=1, is_admin=0, sales_role="rep")
             for name in ("h5_owner", "h5_assignee", "h5_new", "h5_outsider")]
    db_session.add_all([*customers, *users])
    db_session.flush()
    for user in users[:3]:
        db_session.add(CustomerUser(customer_id=customers[0].id, user_id=user.id, role="owner"))
    db_session.commit()
    return customers[0].id, customers[1].id, {user.username: user.id for user in users}


def account_url(cid, resource="tasks"):
    return f"/api/customers/{cid}/{resource}/"


def activity(client, cid, **overrides):
    return client.post(account_url(cid, "activities"), headers=headers("h5_owner"), json={
        "type": "call", "occurred_date": "2026-10-28", "actor": "h5_owner", **overrides})


def task(client, cid, **overrides):
    return client.post(account_url(cid), headers=headers("h5_owner"), json={"title": "Synthetic follow-up", **overrides})


def test_activity_crud_shape_relink_order_and_query_count(client, db_session, world):
    cid, other, _ = world
    contact = CustomerContact(customer_id=cid, display_name="Synthetic attendee")
    db_session.add(contact)
    db_session.commit()
    for kind in ACTIVITY_TYPES:
        result = activity(client, cid, type=kind, contact_ids=[contact.id], outcome="Discussed next step")
        assert result.status_code == 201, result.text
        row = result.json()
        assert set(row) == ACTIVITY_KEYS
        assert row["attendees"] == [{"contact_id": contact.id, "display_name": contact.display_name}]
        assert row["created_by"] == "h5_owner"
    path = f"/api/activities/{row['id']}/"
    assert client.get(path, headers=headers()).json() == row
    response = client.put(path, headers=headers(), json={"occurred_date": None,
        "occurred_at": "2026-10-29T00:30:00+02:00", "contact_ids": [], "actor": "h5_assignee"})
    assert response.status_code == 200, response.text
    assert response.json()["occurred_at"] == "2026-10-28T22:30:00+00:00"
    assert response.json()["attendees"] == []
    with statements(db_session) as sql:
        rows = service.list_activities(db_session, cid)
    assert len(sql) == 3
    assert [r["id"] for r in rows] == sorted(r["id"] for r in rows)
    db_session.query(User).filter_by(username="h5_assignee").update({"is_active": 0})
    db_session.commit()
    assert client.get(path, headers=headers()).json()["actor"] == "h5_assignee"
    assert client.delete(path, headers=headers()).status_code == 204
    assert client.get(path, headers=headers()).status_code == 404


@pytest.mark.parametrize("patch, detail", [
    ({"type": "invented"}, "Unknown activity type"),
    ({"occurred_date": None}, "An activity needs an occurred date (occurred_at or occurred_date)"),
    ({"occurred_at": "2026-10-28T12:00:00Z"}, "Provide exactly one of occurred_at or occurred_date"),
    ({"actor": "missing"}, "Unknown actor"),
])
def test_activity_validation(client, world, patch, detail):
    response = activity(client, world[0], **patch)
    assert response.status_code == 422
    assert response.json()["detail"] == detail


def test_activity_update_validates_merged_dates_and_cross_customer(client, db_session, world):
    cid, other, _ = world
    contact = CustomerContact(customer_id=other, display_name="Other attendee")
    db_session.add(contact)
    db_session.commit()
    assert activity(client, cid, contact_ids=[contact.id]).json()["detail"] == f"Related contact {contact.id} does not belong to this customer"
    row = activity(client, cid).json()
    path = f"/api/activities/{row['id']}/"
    for payload in ({"occurred_date": None}, {"occurred_at": "2026-10-28T12:00:00Z"},
                    {"actor": "missing"}, {"type": None}, {"contact_ids": [contact.id]}):
        assert client.put(path, headers=headers(), json=payload).status_code == 422


@pytest.mark.parametrize("patch, detail", [
    ({"title": "  "}, "title is required"),
    ({"assignee": "missing"}, "Unknown assignee"),
    ({"due_at": "2026-10-28T12:00:00Z", "due_date": "2026-10-28"}, "Provide at most one of due_at or due_date"),
    ({"status": "invented"}, "Unknown task status"),
])
def test_task_validation(client, world, patch, detail):
    response = task(client, world[0], **patch)
    assert response.status_code == 422
    assert response.json()["detail"] == detail


def test_task_evidence_shape_filters_order_and_query_count(client, db_session, world):
    cid, other, _ = world
    note = SalesNote(customer_id=cid, category="discovery", title="Evidence", content="Synthetic")
    foreign = SalesNote(customer_id=other, category="discovery", title="Foreign", content="Synthetic")
    db_session.add_all([note, foreign])
    db_session.commit()
    recorded = activity(client, cid).json()
    response = task(client, cid, evidence_note_ids=[note.id, note.id], evidence_activity_ids=[recorded["id"]])
    row = response.json()
    assert response.status_code == 201, response.text
    assert set(row) == TASK_KEYS
    assert row["evidence_note_count"] == row["evidence_activity_count"] == 1
    assert row["version"] == 1 and row["assignee"] is None
    assert not row["overdue"] and not row["due_soon"] and not row["needs_reassignment"]
    assert task(client, cid, evidence_note_ids=[foreign.id]).json()["detail"] == f"Related note {foreign.id} does not belong to this customer"
    foreign_activity = service.create_activity(
        db_session, other, {"type": "call", "actor": "admin", "occurred_date": date(2026, 10, 28)}, "admin")
    assert task(client, cid, evidence_activity_ids=[foreign_activity["id"]]).json()["detail"] == f"Related activity {foreign_activity['id']} does not belong to this customer"
    dated = task(client, cid, due_date="2026-10-29", assignee="h5_owner").json()
    instant = task(client, cid, due_at="2026-10-28T23:30:00-02:00").json()
    with statements(db_session) as sql:
        rows = service.list_tasks(db_session, cid)
    assert len(sql) == 3
    assert [r["id"] for r in rows] == [dated["id"], instant["id"], row["id"]]
    assert client.get(account_url(cid)+"?mine=true", headers=headers("h5_owner")).json() == [dated]
    assert len(client.get(account_url(cid)+"?status=open", headers=headers()).json()) == 3
    assert client.get(account_url(cid)+"?status=open,completed", headers=headers()).status_code == 422
    path = f"/api/tasks/{row['id']}/"
    assert client.get(path, headers=headers()).json() == row
    for payload in ({"assignee": "missing"}, {"title": None}, {"evidence_note_ids": [foreign.id]}):
        assert client.put(path, headers=headers(), json={"expected_version": 1, **payload}).status_code == 422
    assert client.put(path, headers=headers(), json={"title": "missing version"}).status_code == 422
    assert client.request("DELETE", path, headers=headers(), json={}).status_code == 422
    assert client.request("DELETE", path, headers=headers(), json={"expected_version": 0}).json()["detail"] == service.CONFLICT
    assert client.request("DELETE", path, headers=headers(), json={"expected_version": 1}).status_code == 204
    assert db_session.execute(select(task_evidence_notes)).all() == []
    assert db_session.execute(select(task_evidence_activities)).all() == []


@pytest.mark.parametrize("from_status", service.TRANSITIONS)
@pytest.mark.parametrize("to_status", service.TRANSITIONS)
def test_every_status_transition(client, world, from_status, to_status):
    row = task(client, world[0], status=from_status, completed_by="forged", completed_at="2000-01-01T00:00:00Z").json()
    path = f"/api/tasks/{row['id']}/"
    response = client.put(path, headers=headers("h5_assignee"), json={"expected_version": 1, "status": to_status,
        "completed_by": "forged", "completed_at": "2000-01-01T00:00:00Z"})
    if from_status != to_status and to_status not in service.TRANSITIONS[from_status]:
        assert response.status_code == 422
        assert response.json()["detail"] == f"Invalid task status transition from {from_status} to {to_status}"
    else:
        assert response.status_code == 200, response.text
        updated = response.json()
        assert updated["version"] == 2
        if to_status == "completed":
            assert updated["completed_by"] == ("h5_owner" if from_status == to_status else "h5_assignee")
            assert updated["completed_at"] != "2000-01-01T00:00:00+00:00"
            assert not updated["overdue"] and not updated["due_soon"]
        else:
            assert updated["completed_by"] is None and updated["completed_at"] is None
    version = response.json().get("version", 1)
    assert client.request("DELETE", path, headers=headers(), json={"expected_version": version}).status_code == 204


def test_concurrent_readers_compare_and_swap(db_session, world):
    cid = world[0]
    row = service.create_task(db_session, cid, {"title": "Original"}, "h5_owner")
    with Session(db_session.bind) as first, Session(db_session.bind) as second:
        a, b = first.get(CustomerTask, row["id"]), second.get(CustomerTask, row["id"])
        assert a.version == b.version == 1
        assert service.update_task(first, a, {"expected_version": 1, "title": "Winner"}, "h5_owner")["version"] == 2
        with pytest.raises(HTTPException) as exc:
            service.update_task(second, b, {"expected_version": 1, "title": "Loser"}, "h5_owner")
        assert exc.value.status_code == 409 and exc.value.detail == service.CONFLICT
    db_session.expire_all()
    assert db_session.get(CustomerTask, row["id"]).title == "Winner"


def test_promotion_three_clicks_sources_and_evidence(client, db_session, world):
    cid, other, _ = world
    note = SalesNote(customer_id=cid, category="discovery", title="Synthetic evidence", content="Preserve content")
    batch = IntelligenceImport(file_name="synthetic.csv", file_sha256="a"*64, file_data=b"synthetic",
        total_rows=1, matched_accounts=1, matched_rows=1, unmatched_accounts=0, unmatched_report="[]", imported_by="admin")
    db_session.add_all([note, batch])
    db_session.flush()
    pipeline = PartnerPipeline(import_id=batch.id, customer_id=cid, customer_account_name="Synthetic", opportunity_name="Renewal")
    db_session.add(pipeline)
    db_session.commit()
    for kind, source_id in (("note", note.id), ("renewal_attention", pipeline.id), ("contact_coverage", cid)):
        rows = []
        for expected_code in (201, 200, 200):
            response = client.post(account_url(cid)+"promote/", headers=headers(), json={"source_type": kind, "source_id": source_id})
            assert response.status_code == expected_code, response.text
            value = response.json()
            assert value["created"] == (expected_code == 201)
            assert set(value["task"]) == TASK_KEYS
            rows.append(value["task"])
        assert rows[0] == rows[1] == rows[2]
        assert rows[0]["source_key"] == f"{kind}:{source_id}"
        assert rows[0]["evidence_note_count"] == int(kind == "note")
    assert db_session.query(CustomerTask).count() == 3
    db_session.refresh(note)
    assert note.content == "Preserve content"
    for kind, source_id in (("unknown", cid), ("note", 99999), ("note", note.id),
                            ("renewal_attention", pipeline.id), ("contact_coverage", cid)):
        target = other if source_id != 99999 else cid
        response = client.post(account_url(target)+"promote/", headers=headers(), json={"source_type": kind, "source_id": source_id})
        assert response.status_code == 422
        assert response.json()["detail"] == "Unknown or out-of-scope promotion source"


def test_post_commit_notifications_completion_reopen_and_reassignment(client, db_session, world, monkeypatch):
    cid, _, _ = world
    wakes = []
    def wake(username, frame):
        assert set(frame) == {"type", "id"} and frame["type"] == "notification"
        with Session(db_session.bind) as check:
            persisted = check.get(Notification, frame["id"])
            assert persisted is not None and persisted.user_name == username
        wakes.append((username, frame))
    monkeypatch.setattr(connection_manager, "schedule_send_to_user", wake)
    response = task(client, cid, assignee="h5_assignee", due_date="2020-01-01")
    assert response.status_code == 201, response.text
    row = response.json()
    path = f"/api/tasks/{row['id']}/"
    assert client.put(path, headers=headers(), json={"expected_version": 1, "assignee": "h5_new"}).json()["version"] == 2
    assert client.put(path, headers=headers("h5_new"), json={"expected_version": 2, "status": "completed"}).json()["completed_by"] == "h5_new"
    assert client.put(path, headers=headers(), json={"expected_version": 3, "status": "open"}).json()["completed_at"] is None
    rows = db_session.query(Notification).order_by(Notification.id).all()
    assert [(n.type, n.user_name, n.customer_id) for n in rows] == [
        ("task_assigned", "h5_assignee", cid), ("task_reassigned", "h5_new", cid), ("task_completed", "h5_owner", cid)]
    assert [n.message for n in rows] == [
        "You were assigned task Synthetic follow-up on Synthetic H5 0.",
        "Task Synthetic follow-up on Synthetic H5 0 was reassigned to you.",
        "Task Synthetic follow-up on Synthetic H5 0 was completed by h5_new."]
    assert len(wakes) == 3
    # Self-completion and clearing an assignee produce no additional deliveries.
    client.put(path, headers=headers("h5_owner"), json={"expected_version": 4, "status": "completed", "assignee": None})
    assert len(wakes) == 3
    own = service.create_task(db_session, cid, {"title": "Fail commit", "assignee": "h5_assignee"}, "h5_owner")
    wakes.clear()
    monkeypatch.setattr(db_session, "commit", Mock(side_effect=RuntimeError("failed commit")))
    with pytest.raises(RuntimeError, match="failed commit"):
        service.update_task(db_session, db_session.get(CustomerTask, own["id"]),
            {"expected_version": 1, "assignee": "h5_new"}, "h5_owner")
    assert wakes == []
    db_session.rollback()


@pytest.mark.parametrize("revocation", ("junction", "membership", "inactive", "deleted"))
def test_revocation_hides_mine_notifications_and_evaluator_but_preserves_history(client, db_session, world, revocation):
    cid, _, users = world
    uid = users["h5_assignee"]
    if revocation == "membership":
        db_session.query(CustomerUser).filter_by(user_id=uid).delete()
        db_session.add(AccountMembership(user_id=uid, customer_id=cid, role="inside_sales"))
        db_session.commit()
    row = task(client, cid, assignee="h5_assignee", due_date="2026-10-27").json()
    assert len(client.get("/api/tasks/mine/", headers=headers("h5_assignee")).json()) == 1
    if revocation == "junction":
        db_session.query(CustomerUser).filter_by(user_id=uid).delete()
    elif revocation == "membership":
        db_session.query(AccountMembership).filter_by(user_id=uid).delete()
    elif revocation == "inactive":
        db_session.query(User).filter_by(id=uid).update({"is_active": 0})
    else:
        db_session.query(CustomerUser).filter_by(user_id=uid).delete()
        db_session.query(User).filter_by(id=uid).delete()
    db_session.commit()
    # Service-level pins also cover a stale caller context independently of auth.
    assert service.my_tasks(db_session, {"username": "h5_assignee"}) == []
    assert CollaborationService.get_user_notifications(db_session, "h5_assignee") == []
    if revocation in ("junction", "membership"):
        assert client.get("/api/tasks/mine/", headers=headers("h5_assignee")).json() == []
        assert client.get("/api/use-cases/notifications/", headers=headers("h5_assignee")).json() == []
        assert client.get(f"/api/tasks/{row['id']}/", headers=headers("h5_assignee")).status_code == 404
    assert evaluator.scan_task_notifications(db_session, NOW) == 0
    assert db_session.query(TaskNotificationWindow).count() == 0
    visible = client.get(f"/api/tasks/{row['id']}/", headers=headers("h5_owner")).json()
    assert visible["assignee"] == "h5_assignee" and visible["needs_reassignment"]
    assert db_session.query(CustomerTask).count() == 1


def test_unauthorized_assignment_no_notification_or_access(client, db_session, world):
    cid = world[0]
    row = task(client, cid, assignee="h5_outsider").json()
    assert row["needs_reassignment"]
    assert db_session.query(Notification).count() == 0
    auth = headers("h5_outsider")
    assert client.get("/api/tasks/mine/", headers=auth).json() == []
    for resource in ("tasks", "activities"):
        assert client.get(account_url(cid, resource), headers=auth).status_code == 404
        assert client.post(account_url(cid, resource), headers=auth, json={"title": "Denied", "type": "call", "actor": "h5_outsider"}).status_code == 404
    path = f"/api/tasks/{row['id']}/"
    assert client.put(path, headers=auth, json={"expected_version": 1, "title": "Denied"}).status_code == 404
    assert client.request("DELETE", path, headers=auth, json={"expected_version": 1}).status_code == 404
    recorded = activity(client, cid).json()
    path = f"/api/activities/{recorded['id']}/"
    assert client.get(path, headers=auth).status_code == 404
    assert client.put(path, headers=auth, json={"outcome": "Denied"}).status_code == 404
    assert client.delete(path, headers=auth).status_code == 404
    for path in ("/api/tasks/999999/", "/api/activities/999999/"):
        assert client.get(path, headers=auth).status_code == 404
    assert client.get(account_url(999999), headers=auth).status_code == 404


def test_mine_scale_fixed_three_queries_and_flags(db_session, world):
    _, _, users = world
    customer_ids = []
    for index in range(50):
        customer = Customer(name=f"Synthetic portfolio {index}")
        db_session.add(customer)
        db_session.flush()
        customer_ids.append(customer.id)
        db_session.add(CustomerUser(customer_id=customer.id, user_id=users["h5_assignee"], role="member"))
        db_session.add_all([CustomerTask(customer_id=customer.id, title=f"Follow-up {index}/{j}",
            assignee="h5_assignee", created_by="h5_owner", due_date=date(2020, 1, 1)) for j in range(6)])
    db_session.commit()
    with statements(db_session) as sql:
        rows = service.my_tasks(db_session, {"username": "h5_assignee"})
    assert len(sql) == 2 and len(rows) == 300
    assert len({row["customer_id"] for row in rows}) == 50
    assert all(set(row) == TASK_KEYS | {"customer_name"} and row["overdue"] and not row["due_soon"]
               and not row["needs_reassignment"] for row in rows)


@pytest.mark.parametrize("due, expected", [
    ({}, (False, False)),
    ({"due_date": NOW.date()}, (False, True)),
    ({"due_date": NOW.date()-timedelta(days=1)}, (True, False)),
    ({"due_date": NOW.date()+timedelta(days=1)}, (False, False)),
    ({"due_at": NOW-timedelta(microseconds=1)}, (True, False)),
    ({"due_at": NOW}, (False, False)),
    ({"due_at": NOW+timedelta(hours=24)}, (False, True)),
    ({"due_at": NOW+timedelta(hours=24, microseconds=1)}, (False, False)),
    ({"due_at": datetime.fromisoformat("2026-10-28T09:00:00-04:00")}, (False, True)),
])
def test_utc_date_and_instant_boundaries(due, expected):
    for status in ("open", "in_progress", "completed", "cancelled"):
        flags = service.due_flags(CustomerTask(status=status, **due), NOW)
        assert (flags["overdue"], flags["due_soon"]) == (expected if status in ("open", "in_progress") else (False, False))


def test_evaluator_windows_restart_dedup_exact_messages(client, db_session, world, monkeypatch):
    cid = world[0]
    wakes = Mock()
    monkeypatch.setattr(connection_manager, "schedule_send_to_user", wakes)
    for due in ({"due_date": "2026-10-28"}, {"due_date": "2026-10-27"},
                {"due_date": "2026-10-29"}, {"due_at": "2026-10-28T13:00:00Z"},
                {"due_at": "2026-10-28T11:59:00Z"}, {}):
        assert task(client, cid, assignee="h5_assignee", **due).status_code == 201
    wakes.reset_mock()
    assert evaluator.scan_task_notifications(db_session, NOW) == 4
    assert wakes.call_count == 4
    assert db_session.query(TaskNotificationWindow).count() == 4
    notices = db_session.query(Notification).filter(Notification.type.in_(("task_due_soon", "task_overdue"))).order_by(Notification.id).all()
    assert [n.type for n in notices] == ["task_due_soon", "task_overdue", "task_due_soon", "task_overdue"]
    assert [n.message for n in notices] == [
        "Task Synthetic follow-up on Synthetic H5 0 is due soon (2026-10-28).",
        "Task Synthetic follow-up on Synthetic H5 0 is overdue (was due 2026-10-27).",
        "Task Synthetic follow-up on Synthetic H5 0 is due soon (2026-10-28 13:00 UTC).",
        "Task Synthetic follow-up on Synthetic H5 0 is overdue (was due 2026-10-28 11:59 UTC)."]
    importlib.reload(evaluator)
    with Session(db_session.bind) as restarted:
        assert evaluator.scan_task_notifications(restarted, NOW) == 0
    assert wakes.call_count == 4
    assert evaluator.scan_task_notifications(db_session, NOW+timedelta(days=1)) == 3
    assert db_session.query(TaskNotificationWindow).count() == 7


def test_evaluator_import_has_no_thread_side_effect(monkeypatch):
    start = Mock()
    monkeypatch.setattr(evaluator.threading.Thread, "start", start)
    importlib.reload(evaluator)
    start.assert_not_called()


def test_legacy_notifications_unchanged_on_revocation(db_session, world):
    cid = world[0]
    for kind in (*service.TASK_NOTIFICATION_TYPES, "mention", "scoring"):
        CollaborationService.stage_notification(db_session, "h5_outsider", kind, "Synthetic", cid)
    CollaborationService.stage_notification(db_session, "h5_outsider", "task_assigned", "No customer", None)
    db_session.commit()
    rows = CollaborationService.get_user_notifications(db_session, "h5_outsider")
    assert {n["type"] for n in rows} == {"mention", "scoring", "task_assigned"}
    assert all(n["customer_id"] is None for n in rows if n["type"] == "task_assigned")


@pytest.mark.parametrize("kind, read_status, write_status", [
    ("owner", 200, 201), ("member", 200, 201), ("auditor", 200, 403),
    ("sales_ops", 200, 403), ("ps_admin", 404, 404), ("outsider", 404, 404),
    ("inside_contribute", 200, 201), ("inside_read", 200, 403),
    ("inside_none", 200, 403), ("legacy_inside", 200, 201),
    ("manager", 200, 201), ("admin", 200, 201),
])
@pytest.mark.parametrize("resource", ("activities", "tasks"))
def test_http_authorization_matrix(client, db_session, world, kind, read_status, write_status, resource):
    from backend.models.sales_access import (
        InsideSalesAssignment,
        SalesOpsAssignment,
        SalesReporting,
    )

    cid = world[0]
    user = User(username="matrix_actor", is_admin=int(kind == "admin"), approved=1, is_active=1,
                role="ps_admin" if kind == "ps_admin" else "user",
                sales_role=kind if kind in ("auditor", "sales_ops") else "sales_manager" if kind == "manager" else "rep")
    db_session.add(user)
    db_session.flush()
    if kind in ("owner", "member", "auditor"):
        db_session.add(CustomerUser(customer_id=cid, user_id=user.id, role=kind))
    if kind == "sales_ops":
        db_session.add(SalesOpsAssignment(customer_id=cid, user_id=user.id))
    if kind.startswith("inside_"):
        grants = {resource: "contribute" if kind == "inside_contribute" else "read"} if kind != "inside_none" else None
        db_session.add(AccountMembership(customer_id=cid, user_id=user.id, role="inside_sales", section_grants=grants))
    if kind in ("manager", "legacy_inside"):
        owner_id = world[2]["h5_owner"]
        if kind == "manager":
            db_session.add(SalesReporting(manager_user_id=user.id, rep_user_id=owner_id))
        else:
            user.sales_role = "inside_sales"
            db_session.add(InsideSalesAssignment(inside_sales_user_id=user.id, customer_id=cid))
    db_session.commit()
    if resource == "activities":
        payload = {"type": "meeting", "actor": "h5_owner", "occurred_date": "2026-10-28"}
        existing = service.create_activity(db_session, cid, payload | {"occurred_date": date(2026, 10, 28)}, "h5_owner")
        update = {"outcome": "Updated"}
    else:
        payload = {"title": "Matrix follow-up"}
        existing = service.create_task(db_session, cid, payload, "h5_owner")
        update = {"title": "Updated", "expected_version": 1}
    auth = headers(user.username)
    base = account_url(cid, resource)
    path = f"/api/{resource}/{existing['id']}/"
    assert client.get(base, headers=auth).status_code == read_status
    assert client.get(path, headers=auth).status_code == read_status
    assert client.post(base, headers=auth, json=payload).status_code == write_status
    assert client.put(path, headers=auth, json=update).status_code == (200 if write_status == 201 else write_status)
    response = (client.delete(path, headers=auth) if resource == "activities" else
                client.request("DELETE", path, headers=auth, json={"expected_version": 2}))
    assert response.status_code == (204 if write_status == 201 else write_status)


def test_evaluator_commit_failure_never_pushes_or_consumes_window(db_session, world, monkeypatch):
    cid = world[0]
    row = service.create_task(db_session, cid, {"title": "Fail evaluation", "assignee": "h5_assignee",
                                              "due_date": NOW.date()}, "h5_owner")
    wake = Mock()
    monkeypatch.setattr(connection_manager, "schedule_send_to_user", wake)
    with monkeypatch.context() as scoped:
        scoped.setattr(db_session, "commit", Mock(side_effect=RuntimeError("commit failed")))
        with pytest.raises(RuntimeError, match="commit failed"):
            evaluator.scan_task_notifications(db_session, NOW)
    wake.assert_not_called()
    db_session.rollback()
    assert db_session.query(TaskNotificationWindow).count() == 0
    assert evaluator.scan_task_notifications(db_session, NOW) == 1
    wake.assert_called_once()


def test_unauthenticated_engagement_routes(client, db_session, world):
    cid = world[0]
    recorded = service.create_activity(db_session, cid, {"type": "call", "actor": "admin", "occurred_date": NOW.date()}, "admin")
    followup = service.create_task(db_session, cid, {"title": "Synthetic"}, "admin")
    for path in (account_url(cid), account_url(cid, "activities"), "/api/tasks/mine/",
                 f"/api/tasks/{followup['id']}/", f"/api/activities/{recorded['id']}/"):
        assert client.get(path).status_code == 401


def test_deleting_evidence_and_attendees_cleans_junctions_with_foreign_keys_off(client, db_session, world):
    from sqlalchemy import text

    cid = world[0]
    db_session.commit()
    if db_session.bind.dialect.name == "sqlite":
        db_session.execute(text("PRAGMA foreign_keys=OFF"))
    contact = CustomerContact(customer_id=cid, display_name="Synthetic temporary attendee")
    note = SalesNote(customer_id=cid, category="discovery", title="Synthetic removable evidence", content="Synthetic")
    db_session.add_all([contact, note])
    db_session.commit()
    contact_id, note_id = contact.id, note.id
    recorded = activity(client, cid, contact_ids=[contact_id]).json()
    followup = task(client, cid, evidence_note_ids=[note_id], evidence_activity_ids=[recorded["id"]]).json()
    assert client.delete(f"/api/contacts/{contact_id}/", headers=headers()).status_code == 204
    assert client.get(f"/api/activities/{recorded['id']}/", headers=headers()).json()["attendees"] == []
    assert client.delete(f"/api/sales-notes/{note_id}/", headers=headers()).status_code == 204
    assert client.get(f"/api/tasks/{followup['id']}/", headers=headers()).json()["evidence_note_count"] == 0
    assert client.delete(f"/api/activities/{recorded['id']}/", headers=headers()).status_code == 204
    assert client.get(f"/api/tasks/{followup['id']}/", headers=headers()).json()["evidence_activity_count"] == 0


def test_workspace_actions_are_scoped_and_return_identity_choices(client, db_session, world):
    cid, other, users = world
    user = db_session.get(User, users['h5_assignee'])
    user.display_name = 'Synthetic Assignee'
    db_session.commit()
    response = client.get(account_url(cid, 'workspace-actions'), headers=headers('h5_owner'))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert all(payload['capabilities'].values())
    choices = {row['username']: row['display_name'] for row in payload['assignees']}
    assert choices['h5_assignee'] == 'Synthetic Assignee'
    assert 'h5_outsider' not in choices
    assert client.get(account_url(other, 'workspace-actions'), headers=headers('h5_owner')).status_code == 404


def test_workspace_actions_respect_section_grants(client, db_session, world):
    cid, _, users = world
    db_session.query(CustomerUser).filter_by(user_id=users['h5_assignee']).delete()
    user = db_session.get(User, users['h5_assignee'])
    user.sales_role = 'inside_sales'
    db_session.add(AccountMembership(user_id=user.id, customer_id=cid, role='inside_sales', section_grants={'contacts': 'contribute', 'tasks': 'read'}))
    db_session.commit()
    response = client.get(account_url(cid, 'workspace-actions'), headers=headers('h5_assignee'))
    assert response.status_code == 200, response.text
    assert response.json()['capabilities'] == {'contact': True, 'activity': False, 'task': False, 'deal': False,
        'use_case': False, 'assessment': False, 'technology': False, 'note': False, 'knowledge': False}
    assert response.json()['assignees'] == []


def test_workspace_actions_are_read_only_for_auditors(client, db_session, world):
    cid, _, users = world
    user = db_session.get(User, users['h5_assignee'])
    user.sales_role = 'auditor'
    db_session.commit()
    response = client.get(account_url(cid, 'workspace-actions'), headers=headers('h5_assignee'))
    assert response.status_code == 200
    assert not any(response.json()['capabilities'].values())
    assert response.json()['assignees'] == []


@pytest.mark.parametrize("grant, note_allowed", [("read", False), ("contribute", True)])
def test_legacy_capabilities_inside_sales_notes_only(client, db_session, world, grant, note_allowed):
    cid, _, users = world
    db_session.query(CustomerUser).filter_by(user_id=users['h5_assignee']).delete()
    user = db_session.get(User, users['h5_assignee'])
    user.sales_role = 'inside_sales'
    db_session.add(AccountMembership(user_id=user.id, customer_id=cid, role='inside_sales',
                                     section_grants={'notes': grant}))
    db_session.commit()
    response = client.get(account_url(cid, 'workspace-actions'), headers=headers('h5_assignee'))
    assert response.status_code == 200
    capabilities = response.json()['capabilities']
    assert capabilities['note'] is note_allowed
    for name in ('use_case', 'assessment', 'technology', 'knowledge'):
        assert capabilities[name] is False


def test_concurrent_notification_scans_claim_each_window_once(client, db_session, world, monkeypatch):
    """Independent workers must not deliver the same due window twice."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy.engine.create import create_engine

    cid = world[0]
    response = task(client, cid, assignee="h5_assignee", due_date="2026-10-28")
    assert response.status_code == 201
    task_id = response.json()['id']
    db_session.commit()
    monkeypatch.setattr(connection_manager, 'schedule_send_to_user', Mock())
    bind = db_session.get_bind()
    engine = create_engine(bind.url, pool_size=2, max_overflow=0,
                           connect_args={'timeout': 10} if bind.dialect.name == 'sqlite' else {})
    barrier = Barrier(2, timeout=10)

    def scan(_):
        with Session(engine) as session:
            barrier.wait()
            return evaluator.scan_task_notifications(session, NOW)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            counts = list(executor.map(scan, range(2)))
        assert sorted(counts) == [0, 1]
        db_session.expire_all()
        assert db_session.query(TaskNotificationWindow).filter_by(task_id=task_id, window='due_soon').count() == 1
        assert db_session.query(Notification).filter_by(customer_id=cid, type='task_due_soon').count() == 1
    finally:
        engine.dispose()
