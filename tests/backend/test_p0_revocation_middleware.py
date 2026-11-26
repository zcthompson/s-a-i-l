"""Regression coverage for legacy sharing revocation and import write blocks."""

import pytest
from backend.auth import create_access_token
from backend.models.account_membership import AccountMembership
from backend.models.use_case import Customer, CustomerUser, User
from backend.services import membership_service, sales_access


def headers(username):
    token = create_access_token({"sub": username, "is_admin": False})
    return {"Authorization": f"Bearer {token}"}


def make_user(db, name, role="rep"):
    user = User(username=name, email=f"{name}@test.local", hashed_password="unused",
                approved=1, is_active=1, sales_role=role, is_admin=0)
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def setup(db_session):
    customer = Customer(name="Revocation Account")
    db_session.add(customer)
    db_session.flush()
    owner = make_user(db_session, "revoke_owner")
    target = make_user(db_session, "revoke_target")
    db_session.add(CustomerUser(customer_id=customer.id, user_id=owner.id, role="owner"))
    db_session.commit()
    return customer, owner, target


def url(customer, target):
    return f"/api/customers/{customer.name}/users/{target.id}/"


@pytest.mark.parametrize("junction,role", [(True, "primary_owner"), (False, "co_owner")])
def test_removal_revokes_all_rows_and_capabilities(client, db_session, setup, junction, role):
    customer, owner, target = setup
    if junction:
        db_session.add(CustomerUser(customer_id=customer.id, user_id=target.id, role="owner"))
    db_session.add_all([
        AccountMembership(customer_id=customer.id, user_id=target.id, role=role),
        AccountMembership(customer_id=customer.id, user_id=target.id, role="inside_sales"),
    ])
    db_session.commit()
    assert sales_access.can(membership_service.actor_context(db_session, target.id), db_session,
                            sales_access.CAP_MANAGE_TEAM, customer.id)
    response = client.delete(url(customer, target), headers=headers("admin"))
    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert not db_session.query(CustomerUser).filter_by(customer_id=customer.id, user_id=target.id).all()
    assert not db_session.query(AccountMembership).filter_by(customer_id=customer.id, user_id=target.id).all()
    context = membership_service.actor_context(db_session, target.id)
    assert not sales_access.can(context, db_session, sales_access.CAP_MANAGE_TEAM, customer.id)
    assert not sales_access.can(context, db_session, sales_access.CAP_TRANSFER_OWNERSHIP, customer.id)
    assert client.delete(url(customer, target), headers=headers("admin")).status_code == 404


def test_downgrade_removes_only_owner_memberships(client, db_session, setup):
    customer, owner, target = setup
    db_session.add(CustomerUser(customer_id=customer.id, user_id=target.id, role="owner"))
    db_session.add_all(AccountMembership(customer_id=customer.id, user_id=target.id, role=role)
                       for role in ("co_owner", "inside_sales"))
    db_session.commit()
    response = client.put(url(customer, target), params={"role": "member"}, headers=headers("admin"))
    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert db_session.query(CustomerUser).filter_by(customer_id=customer.id, user_id=target.id).one().role == "member"
    assert [m.role for m in db_session.query(AccountMembership).filter_by(
        customer_id=customer.id, user_id=target.id).all()] == ["inside_sales"]


def test_owner_grants_require_admin_and_upgrade_mints_no_membership(client, db_session, setup):
    customer, owner, target = setup
    add_url = f"/api/customers/{customer.name}/users/"
    response = client.post(add_url, params={"user_id": target.id, "role": "owner"},
                           headers=headers(owner.username))
    assert response.status_code == 403
    assert response.json()["detail"] == "Only admins can grant owner role"
    db_session.add(CustomerUser(customer_id=customer.id, user_id=target.id, role="member"))
    db_session.commit()
    response = client.put(url(customer, target), params={"role": "owner"}, headers=headers(owner.username))
    assert response.status_code == 403
    assert response.json()["detail"] == "Only admins can grant owner role"
    response = client.put(url(customer, target), params={"role": "owner"}, headers=headers("admin"))
    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert db_session.query(CustomerUser).filter_by(customer_id=customer.id, user_id=target.id).one().role == "owner"
    assert not db_session.query(AccountMembership).filter_by(customer_id=customer.id, user_id=target.id).all()


@pytest.mark.parametrize("method,path,expected", [
    ("delete", "/api/intelligence-import/999999/", 404),
    ("post", "/api/rvtools-import/", 422),
    ("delete", "/api/rep-intelligence/999999/", 404),
])
def test_import_middleware_roles(client, db_session, method, path, expected):
    for name, role in (("import_sadmin", "sales_admin"), ("import_manager", "sales_manager"),
                       ("import_auditor", "auditor")):
        make_user(db_session, name, role)
    db_session.commit()
    call = getattr(client, method)
    response = call(path, headers=headers("import_sadmin"))
    assert response.status_code == 403
    assert response.json()["detail"] == "Sales admin cannot modify account content"
    response = call(path, headers=headers("import_auditor"))
    assert response.status_code == 403
    assert response.json()["detail"] == "Auditor role is read-only"
    for username in ("import_manager", "admin"):
        response = call(path, headers=headers(username))
        assert response.status_code == expected, (username, response.text)
