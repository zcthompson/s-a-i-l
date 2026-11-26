"""Sales managers may create prospect accounts that enter the existing
admin ownership-review queue; other non-admin roles may not create accounts."""

import json

import pytest
from backend.auth import create_access_token
from backend.models.account_membership import AccountMembership
from backend.models.collaboration import AuditLog
from backend.models.customer_alias import CustomerAlias
from backend.models.use_case import Customer, CustomerUser, User


def headers(username="admin"):
    return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}


def _user(db, username, sales_role, active=1):
    user = User(username=username, role="user", sales_role=sales_role, is_admin=0,
                approved=1, is_active=active, auth_provider="local")
    db.add(user)
    db.commit()
    return user


@pytest.fixture()
def people(db_session):
    return {
        "manager": _user(db_session, "synthetic_manager", "sales_manager"),
        "rep": _user(db_session, "synthetic_rep", "rep"),
        "isr": _user(db_session, "synthetic_isr", "inside_sales"),
        "former": _user(db_session, "synthetic_former_manager", "sales_manager", active=0),
    }


def _audits(db, action):
    return db.query(AuditLog).filter(AuditLog.action == action).all()


def test_manager_prospect_enters_review_queue_with_manager_as_owner(client, db_session, people):
    manager = people["manager"]
    r = client.post("/api/customers/", json={"name": "Synthetic Prospect Co"}, headers=headers(manager.username))
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    db_session.expire_all()
    customer = db_session.get(Customer, cid)
    assert customer.ownership_status == "needs_review"
    assert db_session.query(CustomerUser).filter_by(customer_id=cid, user_id=manager.id, role="owner").count() == 1
    assert db_session.query(AccountMembership).filter_by(
        customer_id=cid, user_id=manager.id, role="primary_owner").count() == 1
    audit, = _audits(db_session, "account.prospect_create")
    assert audit.customer_id == cid and json.loads(audit.details)["provisional_owner"] == manager.username
    # The manager can open the new account.
    assert client.get("/api/customers/Synthetic%20Prospect%20Co/", headers=headers(manager.username)).status_code == 200

    queue = client.get("/api/admin/ownership-review/", headers=headers()).json()["items"]
    assert [i for i in queue if i["customer_id"] == cid] == [{
        "customer_id": cid, "name": "Synthetic Prospect Co", "current_owner": manager.username,
        "current_owner_user_id": manager.id, "placeholder": True,
    }]
    # An admin assigns the prospect to a rep through the existing review flow.
    r = client.post(f"/api/admin/ownership-review/{cid}/", json={"user_id": people["rep"].id}, headers=headers())
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert db_session.get(Customer, cid).ownership_status is None
    assert db_session.query(AccountMembership).filter_by(customer_id=cid, role="primary_owner").one().user_id == people["rep"].id


@pytest.mark.parametrize("who", ["rep", "isr", "former"])
def test_other_roles_cannot_create_accounts(client, db_session, people, who):
    r = client.post("/api/customers/", json={"name": f"Synthetic {who} attempt"}, headers=headers(people[who].username))
    assert r.status_code in (401, 403), r.text
    assert db_session.query(Customer).filter(Customer.name == f"Synthetic {who} attempt").count() == 0
    assert _audits(db_session, "account.prospect_create") == []


@pytest.mark.parametrize("name", ["ACME Corp", "acme   corp", "Acme Corporation"])
def test_prospect_duplicates_by_name_or_alias_are_refused(client, db_session, people, name):
    acme = Customer(name="ACME Corp")
    db_session.add(acme)
    db_session.flush()
    db_session.add(CustomerAlias(customer_id=acme.id, alias="Acme Corporation", alias_norm="acme corporation",
                                 created_by="admin"))
    db_session.commit()
    before = db_session.query(Customer).count()
    r = client.post("/api/customers/", json={"name": name}, headers=headers(people["manager"].username))
    assert r.status_code == 400, r.text
    assert db_session.query(Customer).count() == before


def test_admin_creation_is_unchanged(client, db_session, people):
    r = client.post("/api/customers/", json={"name": "Synthetic Admin Co"}, headers=headers())
    assert r.status_code == 201, r.text
    db_session.expire_all()
    assert db_session.get(Customer, r.json()["id"]).ownership_status is None
    assert _audits(db_session, "account.prospect_create") == []
