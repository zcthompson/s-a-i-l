"""H4 synthetic acceptance tests: observations, isolation, integrity, and honest coverage."""

from contextlib import contextmanager

import pytest
from backend.auth import create_access_token
from backend.models.account_membership import AccountMembership
from backend.models.customer_contact import (
    BUYING_ROLES,
    contact_notes,
)
from backend.models.customer_technology import CustomerTechnology
from backend.models.sales_note import SalesNote
from backend.models.use_case import Customer, CustomerUser, UseCase, User
from backend.services import customer_contact_service as service
from backend.services import customer_intelligence as intelligence
from sqlalchemy import event, select

BASIS = "No qualified interaction evidence recorded (editing a contact is not engagement)"
GAPS = ["No contacts recorded", "No economic buyer recorded", "No champion recorded"]


def headers(username="admin"):
    return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}


@pytest.fixture()
def account(db_session):
    customer = Customer(name="Synthetic H4 account")
    other = Customer(name="Synthetic H4 other")
    db_session.add_all([customer, other])
    db_session.commit()
    return customer, other


def url(account):
    return f"/api/customers/{account.id}/contacts/"


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


def related(db, customer_id):
    note = SalesNote(customer_id=customer_id, category="discovery", title="Synthetic note", content="Synthetic observation")
    use_case = UseCase(customer_id=customer_id, title="Synthetic initiative")
    tech = CustomerTechnology(customer_id=customer_id, name="Synthetic technology", category="software")
    db.add_all([note, use_case, tech])
    db.commit()
    return note, use_case, tech


def test_crud_full_replacement_and_nulls(client, db_session, account):
    customer, _ = account
    note, use_case, tech = related(db_session, customer.id)
    payload = dict(display_name="  Synthetic contact  ", title="VP Finance", email="stored as provided",
                   phone="555-0100", department="Synthetic", persona="executive", source="Synthetic record",
                   observation_date="2026-10-27", verification_state="unverified",
                   buying_roles=[dict(role="economic_buyer", source="Synthetic source", observation_date="2026-10-26",
                                      verification_state="inferred"), dict(role="champion")],
                   related_note_ids=[note.id], related_use_case_ids=[use_case.id], related_technology_ids=[tech.id])
    response = client.post(url(customer), headers=headers(), json=payload)
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["display_name"] == "Synthetic contact"
    assert row["email"] == payload["email"]
    assert row["note_count"] == 1 and row["created_by"] == row["updated_by"] == "admin"
    assert row["buying_roles"][0] == {**payload["buying_roles"][0], "role_label": "Economic buyer"}
    assert row["buying_roles"][1]["source"] is None
    assert row["buying_roles"][1]["observation_date"] is None
    path = f"/api/contacts/{row['id']}/"
    assert client.get(path, headers=headers()).json() == row
    response = client.put(path, headers=headers(), json=dict(buying_roles=[dict(role="champion")],
                          related_note_ids=[], related_use_case_ids=[], related_technology_ids=[], email=None))
    assert response.status_code == 200, response.text
    assert response.json()["email"] is None
    assert response.json()["related_note_ids"] == []
    assert [r["role"] for r in response.json()["buying_roles"]] == ["champion"]
    assert client.delete(path, headers=headers()).status_code == 204
    assert client.get(path, headers=headers()).status_code == 404
    row = client.post(url(customer), headers=headers(), json={"display_name": "Synthetic minimum"}).json()
    for field in ("title", "email", "phone", "department", "persona", "persona_label", "source", "observation_date", "archived_at"):
        assert row[field] is None
    assert row["buying_roles"] == []


@pytest.mark.parametrize("payload, detail", [
    ({"display_name": ""}, "display_name is required"),
    ({"display_name": "  "}, "display_name is required"),
    ({"persona": "unknown"}, "Unknown persona 'unknown'"),
    ({"buying_roles": [{"role": "invented"}]}, "Unknown buying role 'invented'"),
    ({"buying_roles": [{"role": "champion"}, {"role": "champion"}]}, "Duplicate buying role 'champion'"),
    ({"verification_state": "invented"}, "verification_state must be one of"),
    ({"buying_roles": [{"role": "champion", "verification_state": "invented"}]}, "verification_state must be one of"),
])
def test_validation_on_create_and_update(client, db_session, account, payload, detail):
    customer, _ = account
    row = service.create_contact(db_session, customer.id, {"display_name": "Synthetic"}, "admin")
    for response in (client.post(url(customer), headers=headers(), json={"display_name": "Synthetic", **payload}),
                     client.put(f"/api/contacts/{row.id}/", headers=headers(), json=payload)):
        assert response.status_code == 422
        assert detail in response.json()["detail"]


@pytest.mark.parametrize("index, field, label", [(0, "related_note_ids", "note"), (1, "related_use_case_ids", "use case"), (2, "related_technology_ids", "technology")])
def test_cross_customer_rejected_atomically(client, db_session, account, index, field, label):
    customer, other = account
    foreign = related(db_session, other.id)[index]
    payload = {"display_name": "Synthetic", field: [foreign.id]}
    response = client.post(url(customer), headers=headers(), json=payload)
    assert response.status_code == 422
    assert response.json()["detail"] == f"Related {label} {foreign.id} does not belong to this customer"
    row = service.create_contact(db_session, customer.id, {"display_name": "Synthetic before"}, "admin")
    response = client.put(f"/api/contacts/{row.id}/", headers=headers(), json=payload)
    assert response.status_code == 422
    db_session.refresh(row)
    assert row.display_name == "Synthetic before"


def test_customer_immutable(client, db_session, account):
    customer, other = account
    row = client.post(url(customer), headers=headers(), json={"display_name": "Synthetic", "customer_id": other.id}).json()
    assert row["customer_id"] == customer.id
    response = client.put(f"/api/contacts/{row['id']}/", headers=headers(), json={"customer_id": other.id})
    assert response.json()["customer_id"] == customer.id


def test_archive_retains_notes_and_delete_guard(client, db_session, account):
    customer, _ = account
    note, _, _ = related(db_session, customer.id)
    row = service.create_contact(db_session, customer.id, {"display_name": "Synthetic", "related_note_ids": [note.id]}, "admin")
    path = f"/api/contacts/{row.id}/"
    detail = "Contact has linked sales notes; archive the contact instead (historical note references are preserved)"
    assert client.delete(path, headers=headers()).json() == {"detail": detail}
    response = client.put(path, headers=headers(), json={"archived": True})
    assert response.json()["archived_at"] is not None
    assert response.json()["related_note_ids"] == [note.id]
    assert client.get(url(customer), headers=headers()).json() == []
    assert len(client.get(url(customer)+"?include_archived=true", headers=headers()).json()) == 1
    assert client.get(f"/api/sales-notes/{note.id}/", headers=headers()).status_code == 200
    assert client.delete(path, headers=headers()).status_code == 409
    assert client.put(path, headers=headers(), json={"archived": False}).json()["archived_at"] is None
    assert client.delete(f"/api/sales-notes/{note.id}/", headers=headers()).status_code == 204
    assert db_session.execute(select(contact_notes)).all() == []
    assert client.delete(path, headers=headers()).status_code == 204


def test_email_not_identity(db_session, account):
    customer, other = account
    counts = (db_session.query(User).count(), db_session.query(AccountMembership).count(), db_session.query(CustomerUser).count())
    email = db_session.query(User).first().email
    ids = [service.create_contact(db_session, c.id, {"display_name": "Synthetic", "email": email}, "admin").id
           for c in (customer, customer, other)]
    assert len(set(ids)) == 3
    assert counts == (db_session.query(User).count(), db_session.query(AccountMembership).count(), db_session.query(CustomerUser).count())


def test_coverage_queries_honesty_and_archives(db_session, account):
    customer, _ = account
    cid = customer.id
    with statements(db_session) as sql:
        empty = service.contact_coverage_for(db_session, cid)
    assert len(sql) == 4
    assert empty["gaps"] == GAPS
    assert empty["roles"] == dict.fromkeys(BUYING_ROLES, 0)
    assert empty["last_contacted"] is None and empty["last_contacted_basis"] == BASIS
    contact = service.create_contact(db_session, cid, {"display_name": "Synthetic", "title": "VP Finance"}, "admin")
    assert contact.to_dict()["buying_roles"] == []
    assert service.contact_coverage_for(db_session, cid)["economic_buyer_recorded"] is False
    service.update_contact(db_session, contact, {"persona": "executive", "buying_roles": [{"role": r} for r in BUYING_ROLES]}, "admin")
    with statements(db_session) as sql:
        full = service.contact_coverage_for(db_session, cid)
    assert len(sql) == 4
    assert full["gaps"] == [] and full["personas"] == {"executive": 1}
    assert full["roles"] == dict.fromkeys(BUYING_ROLES, 1)
    assert full["last_contacted"] is None and full["last_contacted_basis"] == BASIS
    service.update_contact(db_session, contact, {"archived": True}, "admin")
    archived = service.contact_coverage_for(db_session, cid)
    assert archived["contacts_recorded"] == 0 and archived["archived_count"] == 1
    assert archived["gaps"] == GAPS
    assert archived["roles"] == empty["roles"]
    assert archived["personas"] == {} and archived["persona_unknown"] == 0


def test_list_fixed_queries_search_and_order(db_session, account):
    customer, _ = account
    cid = customer.id
    with statements(db_session) as sql:
        assert service.list_contacts(db_session, cid) == []
    assert len(sql) == 1
    note, uc, tech = related(db_session, cid)
    for index in range(4):
        service.create_contact(db_session, cid, {"display_name": f"Synthetic {index}", "title": "Finance",
            "department": "Research", "related_note_ids": [note.id], "related_use_case_ids": [uc.id],
            "related_technology_ids": [tech.id], "buying_roles": [{"role": "champion"}]}, "admin")
    db_session.expire_all()
    with statements(db_session) as sql:
        rows = [row.to_dict() for row in service.list_contacts(db_session, cid)]
    assert len(sql) == 5
    assert [r["id"] for r in rows] == sorted(r["id"] for r in rows)
    assert all(r["note_count"] == 1 and r["related_note_ids"] == [note.id] for r in rows)
    for search in (" SYNTHETIC ", "fINAnce", " research "):
        assert len(service.list_contacts(db_session, cid, search=search)) == 4
    assert service.list_contacts(db_session, cid, search="nonexistent") == []


def test_workspace_card_and_graph_stability(db_session, account, monkeypatch):
    customer, _ = account
    cid = customer.id
    card = service.contact_coverage_card(service.contact_coverage_for(db_session, cid), customer.name)
    assert card == {"id": f"contact-coverage-{cid}", "type": "contact_coverage", "severity": "high",
        "title": "; ".join(GAPS), "detail": "0 contacts recorded; 0 buying role(s) recorded",
        "evidence": {"source": "customer_contacts", "source_id": cid, "source_name": "Account contact coverage"}}
    with statements(db_session) as workspace_sql:
        workspace = intelligence.get_account_workspace(db_session, cid)
    original_coverage = intelligence.contact_coverage_for
    monkeypatch.setattr(intelligence, "contact_coverage_for", lambda *_: original_coverage_value)
    original_coverage_value = service.contact_coverage_for(db_session, cid)
    with statements(db_session) as baseline_sql:
        intelligence.get_account_workspace(db_session, cid)
    assert len(workspace_sql) == len(baseline_sql) + 4
    monkeypatch.setattr(intelligence, "contact_coverage_for", original_coverage)
    assert [c for c in workspace["opportunities"] if c["type"] == "contact_coverage"] == [card]
    graph_before = intelligence.build_customer_intelligence_graph(db_session, cid)
    contact = service.create_contact(db_session, cid, {"display_name": "Synthetic", "buying_roles": [{"role": "economic_buyer"}]}, "admin")
    partial = service.contact_coverage_card(service.contact_coverage_for(db_session, cid), customer.name)
    assert partial["severity"] == "medium" and partial["title"] == "No champion recorded"
    service.update_contact(db_session, contact, {"buying_roles": [{"role": "economic_buyer"}, {"role": "champion"}]}, "admin")
    assert service.contact_coverage_card(service.contact_coverage_for(db_session, cid), customer.name) is None
    assert not any(c["type"] == "contact_coverage" for c in intelligence.get_account_workspace(db_session, cid)["opportunities"])
    graph_after = intelligence.build_customer_intelligence_graph(db_session, cid)
    # The graph uses the panel synthesis, so the coverage card appears as a
    # Risks / Gaps node while gaps exist and disappears once coverage is complete.
    # No new domain is added; nodes outside the risk domain are unaffected.
    coverage = [n for n in graph_before["nodes"] if n["type"] == "risk" and n["status"] == "contact_coverage"]
    assert [n["label"] for n in coverage] == [card["title"]]
    assert coverage[0]["metadata"]["evidence"] == card["evidence"]
    assert not any(n["status"] == "contact_coverage" for n in graph_after["nodes"])
    assert {n["category"] for n in graph_before["nodes"]} <= {n["category"] for n in graph_after["nodes"]} | {"risk"}

    def outside_risk(graph):
        return sorted((n["id"], n["label"]) for n in graph["nodes"] if n["category"] != "risk")
    assert outside_risk(graph_after) == outside_risk(graph_before)


@pytest.mark.parametrize("kind, read_status, write_status", [
    ("owner", 200, 201), ("member", 200, 201), ("auditor", 200, 403),
    ("sales_ops", 200, 403), ("ps_admin", 404, 404), ("outsider", 404, 404),
    ("inside_contribute", 200, 201), ("inside_read", 200, 403),
    ("inside_none", 200, 403), ("legacy_inside", 200, 201),
    ("manager", 200, 201), ("admin", 200, 201),
])
def test_authorization_matrix(client, db_session, account, kind, read_status, write_status):
    from backend.models.sales_access import (
        InsideSalesAssignment,
        SalesOpsAssignment,
        SalesReporting,
    )
    customer, other = account
    contact = service.create_contact(db_session, customer.id, {"display_name": "Synthetic existing"}, "admin")
    path = f"/api/contacts/{contact.id}/"
    user = User(username="synthetic_actor", email="synthetic_actor@test.local", hashed_password="unused",
                is_admin=int(kind == "admin"), approved=1, is_active=1,
                role="ps_admin" if kind == "ps_admin" else None,
                sales_role=kind if kind in ("auditor", "sales_ops") else ("sales_manager" if kind == "manager" else "rep"))
    db_session.add(user)
    db_session.flush()
    if kind in ("owner", "member", "auditor"):
        db_session.add(CustomerUser(customer_id=customer.id, user_id=user.id, role=kind))
    if kind == "sales_ops":
        db_session.add(SalesOpsAssignment(customer_id=customer.id, user_id=user.id))
    if kind.startswith("inside_"):
        grants = {"contacts": "contribute" if kind == "inside_contribute" else "read"} if kind != "inside_none" else None
        db_session.add(AccountMembership(customer_id=customer.id, user_id=user.id,
                                         role="sales_ops" if kind == "sales_ops" else "inside_sales", section_grants=grants))
    if kind in ("manager", "legacy_inside"):
        rep = User(username="synthetic_rep", email="synthetic_rep@test.local", hashed_password="unused",
                   sales_role="rep", is_admin=0, approved=1, is_active=1)
        db_session.add(rep)
        db_session.flush()
        db_session.add(CustomerUser(customer_id=customer.id, user_id=rep.id, role="owner"))
        if kind == "manager":
            db_session.add(SalesReporting(manager_user_id=user.id, rep_user_id=rep.id))
        else:
            user.sales_role = "inside_sales"
            db_session.add(InsideSalesAssignment(inside_sales_user_id=user.id, customer_id=customer.id, rep_user_id=rep.id))
    db_session.commit()
    auth = headers(user.username)
    assert client.get(url(customer), headers=auth).status_code == read_status
    assert client.get(url(customer)+"coverage/", headers=auth).status_code == read_status
    assert client.get(path, headers=auth).status_code == read_status
    assert client.get("/api/contacts/999999/", headers=auth).status_code == 404
    assert client.get("/api/customers/999999/contacts/", headers=auth).status_code == 404
    response = client.post(url(customer), headers=auth, json={"display_name": "Synthetic new"})
    assert response.status_code == write_status, response.text
    update = client.put(path, headers=auth, json={"title": "Synthetic edit"})
    assert update.status_code == (200 if write_status == 201 else write_status)
    delete = client.delete(path, headers=auth)
    assert delete.status_code == (204 if write_status == 201 else write_status)


def test_unauthenticated(client, db_session, account):
    customer, _ = account
    row = service.create_contact(db_session, customer.id, {"display_name": "Synthetic"}, "admin")
    path = f"/api/contacts/{row.id}/"
    for response in (client.get(url(customer)), client.post(url(customer), json={"display_name": "Synthetic"}),
                     client.get(url(customer)+"coverage/"), client.get(path),
                     client.put(path, json={"title": "Synthetic"}), client.delete(path)):
        assert response.status_code == 401
