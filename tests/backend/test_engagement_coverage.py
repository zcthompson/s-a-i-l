"""H5 engagement is dated evidence, never scheduling, importing, or record edits."""

from datetime import UTC, date, datetime

from backend.models.customer_engagement import CustomerActivity, CustomerTask
from backend.models.sales_note import SalesNote
from backend.models.use_case import Customer
from backend.services.account_engagement import last_meaningful_interaction_for
from backend.services.customer_contact_service import LAST_CONTACTED_BASIS, contact_coverage_for

from tests.backend.test_customer_contacts import headers, statements

BASIS = "No qualified interaction evidence recorded (editing a contact is not engagement)"


def test_no_evidence_undated_note_edits_and_future_scheduling_never_count(client, db_session):
    customer = Customer(name="Synthetic no engagement")
    db_session.add(customer)
    db_session.flush()
    cid = customer.id
    note = SalesNote(customer_id=cid, category="discovery", title="Undated import", content="Synthetic",
                     source="import", updated_at=datetime(2099, 1, 1))
    db_session.add_all([note, CustomerTask(customer_id=cid, title="Future follow-up", due_date=date(2099, 1, 1), created_by="admin")])
    db_session.commit()
    with statements(db_session) as sql:
        assert last_meaningful_interaction_for(db_session, cid) is None
    assert len(sql) == 2
    with statements(db_session) as sql:
        coverage = contact_coverage_for(db_session, cid)
    assert len(sql) == 4
    assert coverage["calc_version"] == "contact-coverage/2"
    assert coverage["last_contacted"] is None
    assert coverage["last_contacted_basis"] == LAST_CONTACTED_BASIS == BASIS
    note.content = "Later edit"
    db_session.commit()
    assert last_meaningful_interaction_for(db_session, cid) is None
    response = client.get(f"/api/customers/{cid}/contacts/coverage/", headers=headers())
    assert response.status_code == 200
    assert response.json()["last_contacted_basis"] == BASIS


def test_latest_recorded_date_used_exactly_including_future_and_utc(client, db_session):
    customer = Customer(name="Synthetic dated engagement")
    db_session.add(customer)
    db_session.flush()
    cid = customer.id
    note = SalesNote(customer_id=cid, category="discovery", title="Dated evidence", content="Synthetic",
                     note_date=date(2026, 10, 25))
    recorded = CustomerActivity(customer_id=cid, type="call", actor="admin", occurred_date=date(2026, 10, 26), created_by="admin")
    db_session.add_all([note, recorded])
    db_session.commit()
    assert last_meaningful_interaction_for(db_session, cid) == date(2026, 10, 26)
    recorded.outcome = "Edited today"
    recorded.updated_at = datetime.now(UTC)
    db_session.commit()
    assert last_meaningful_interaction_for(db_session, cid) == date(2026, 10, 26)
    note.note_date = date(2026, 10, 27)
    db_session.commit()
    assert last_meaningful_interaction_for(db_session, cid) == date(2026, 10, 27)
    response = client.post(f"/api/customers/{cid}/activities/", headers=headers(), json={
        "type": "meeting", "actor": "admin", "occurred_at": "2099-01-01T00:30:00+02:00"})
    assert response.status_code == 201, response.text
    expected = "2098-12-31"
    coverage = client.get(f"/api/customers/{cid}/contacts/coverage/", headers=headers()).json()
    assert coverage["last_contacted"] == expected
    assert coverage["last_contacted_basis"] == f"Last meaningful interaction {expected} (recorded activities and dated notes; imports, record edits, and scheduling are not engagement)"
    assert last_meaningful_interaction_for(db_session, cid) == date(2098, 12, 31)
