"""Customer mutation authorization and deterministic cascade coverage."""

import json
from unittest.mock import patch

import pytest
from backend.models.collaboration import AuditLog, Comment, Notification, ScoreHistory
from backend.models.use_case import (
    AIPrediction,
    Customer,
    CustomerAssessment,
    CustomerUser,
    Department,
    Projection,
    UseCase,
    User,
)

_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"


@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
    from backend import auth as auth_mod
    bind = db_session.get_bind()
    shared_engine = getattr(bind, "engine", bind)

    def _lookup(username):
        user = db_session.query(User).filter(User.username == username).first()
        if not (user and user.is_active):
            return None
        return {"username": user.username, "email": user.email, "display_name": user.display_name,
                "department": user.department, "is_admin": user.is_admin, "role": user.role,
                "user_id": user.id}

    with patch.object(auth_mod, "_get_user_by_username", _lookup), \
         patch.object(auth_mod, "create_engine", lambda *args, **kwargs: shared_engine):
        yield


def _token(username):
    from backend.auth import create_access_token
    return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}


@pytest.fixture
def customer_seed(db_session):
    customer = Customer(name="mutation-customer", description="Before")
    db_session.add(customer)
    db_session.flush()
    users = {}
    for username, role in (("mut_owner", "owner"), ("mut_member", "member"),
                           ("mut_auditor", "auditor"), ("mut_outsider", None)):
        user = User(username=username, email=f"{username}@test.local", hashed_password=_HASH,
                    display_name=username, department="IT", is_admin=0, approved=1, is_active=1)
        db_session.add(user)
        db_session.flush()
        users[username] = user
        if role:
            db_session.add(CustomerUser(customer_id=customer.id, user_id=user.id, role=role,
                                        granted_by=users["mut_owner"].id if "mut_owner" in users else user.id))
    department = Department(name="IT", customer_id=customer.id)
    assessment = CustomerAssessment(customer_id=customer.id, name="Round one", created_by="mut_owner")
    db_session.add_all([department, assessment])
    db_session.flush()
    use_case = UseCase(title="Seed use case", customer_id=customer.id, department_id=department.id,
                       department="IT", assessment_id=assessment.id, status="active")
    db_session.add(use_case)
    db_session.flush()
    db_session.add_all([
        Projection(customer_id=customer.id, customer_name=customer.name, projection_data={"score": 1}),
        ScoreHistory(use_case_id=use_case.id, score=50, scored_by="mut_owner"),
        Comment(use_case_id=use_case.id, user_name="mut_owner", content="seed"),
        AIPrediction(use_case_id=use_case.id, customer_id=customer.id, horizon_days=30, predicted_score=60),
        Notification(user_name="mut_owner", type="seed", message="seed", customer_id=customer.id),
    ])
    db_session.commit()
    return {"customer_id": customer.id, "name": customer.name}


def test_delete_requires_authentication(client, customer_seed):
    assert client.delete(f"/api/customers/{customer_seed['name']}/").status_code == 401


@pytest.mark.parametrize("username", ["mut_member", "mut_auditor"])
def test_non_owner_cannot_delete(client, customer_seed, username):
    response = client.delete(f"/api/customers/{customer_seed['name']}/", headers=_token(username))
    assert response.status_code == 403
    assert response.json()["detail"] == "Customer owner or admin required"


def test_outsider_delete_is_404(client, customer_seed):
    # 404-first: out-of-scope is the same 404 as a missing customer.
    response = client.delete(f"/api/customers/{customer_seed['name']}/", headers=_token("mut_outsider"))
    assert response.status_code == 404
    assert response.json()["detail"] == "Customer not found"


def test_owner_delete_removes_customer_and_all_dependents(client, db_session, customer_seed):
    customer_id = customer_seed["customer_id"]
    response = client.delete(f"/api/customers/{customer_seed['name']}/", headers=_token("mut_owner"))
    assert response.status_code == 204
    db_session.expire_all()
    for model in (Customer, UseCase, Department, CustomerUser, Projection, CustomerAssessment,
                  ScoreHistory, Comment, AIPrediction):
        assert db_session.query(model).count() == 0
    assert db_session.query(Notification).filter(Notification.customer_id == customer_id).count() == 0
    audit = db_session.query(AuditLog).filter_by(action="customer.delete", customer_id=customer_id).one()
    assert audit.username == "mut_owner" and audit.target_id is None
    details = json.loads(audit.details)
    assert details["customer_name"] == customer_seed["name"]
    assert details["deleted_counts"]["customers"] == 1
    assert details["deleted_counts"]["use_cases"] == 1
    assert details["deleted_counts"]["assessments"] == 1


def test_admin_can_delete(client, db_session, customer_seed):
    assert client.delete(f"/api/customers/{customer_seed['name']}/", headers=_token("admin")).status_code == 204
    db_session.expire_all()
    assert db_session.query(Customer).filter(Customer.id == customer_seed["customer_id"]).first() is None


def test_delete_unknown_customer_returns_404(client):
    assert client.delete("/api/customers/missing/", headers=_token("admin")).status_code == 404


def test_update_requires_authentication(client, customer_seed):
    assert client.put(f"/api/customers/{customer_seed['name']}/", json={"description": "After"}).status_code == 401


@pytest.mark.parametrize("username", ["mut_member"])
def test_non_owner_cannot_update(client, customer_seed, username):
    response = client.put(f"/api/customers/{customer_seed['name']}/", headers=_token(username), json={"description": "After"})
    assert response.status_code == 403
    # the update gate is central CAP_METADATA (member = no).
    assert response.json()["detail"] == "Not authorized to modify this customer"


def test_outsider_update_is_404(client, customer_seed):
    # 404-first: out-of-scope is the same 404 as a missing customer.
    response = client.put(f"/api/customers/{customer_seed['name']}/", headers=_token("mut_outsider"),
                          json={"description": "After"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Customer not found"


@pytest.mark.parametrize("username", ["mut_owner", "admin"])
def test_owner_and_admin_can_update_description_without_renaming(client, db_session, customer_seed, username):
    response = client.put(f"/api/customers/{customer_seed['name']}/", headers=_token(username), json={"description": "After"})
    assert response.status_code == 200
    assert response.json()["name"] == customer_seed["name"]
    assert response.json()["description"] == "After"
    db_session.expire_all()
    assert db_session.query(Customer).filter(Customer.id == customer_seed["customer_id"]).one().description == "After"


def test_update_unknown_customer_returns_404(client):
    assert client.put("/api/customers/missing/", headers=_token("admin"), json={"description": "After"}).status_code == 404


def test_admin_create_grants_creator_owner(client, db_session):
    response = client.post("/api/customers/", headers=_token("admin"), json={"name": "created-customer", "description": "New"})
    assert response.status_code == 201
    db_session.expire_all()
    customer = db_session.query(Customer).filter(Customer.name == "created-customer").one()
    admin = db_session.query(User).filter(User.username == "admin").one()
    junction = db_session.query(CustomerUser).filter_by(customer_id=customer.id, user_id=admin.id).one()
    assert junction.role == "owner"
    assert junction.granted_by == admin.id


def test_non_admin_create_remains_forbidden(client, customer_seed):
    assert client.post("/api/customers/", headers=_token("mut_owner"), json={"name": "forbidden"}).status_code == 403


def test_owner_delete_cleans_customer_level_predictions_without_use_cases(client, db_session):
    """Defensive else-branch: a customer with no use cases but a legacy
    customer-scoped prediction row (FK pragma off, so a dangling
    use_case_id can exist) must still have its predictions cleaned."""
    customer = Customer(name="no-usecase-customer")
    db_session.add(customer)
    db_session.flush()
    owner = User(username="nu_owner", email="nu_owner@test.local", hashed_password=_HASH,
                 display_name="nu_owner", department="IT", is_admin=0, approved=1, is_active=1)
    db_session.add(owner)
    db_session.flush()
    db_session.add(CustomerUser(customer_id=customer.id, user_id=owner.id, role="owner",
                                granted_by=owner.id))
    if db_session.bind.dialect.name == "postgresql":
        from sqlalchemy.exc import IntegrityError
        db_session.commit()
        db_session.add(AIPrediction(use_case_id=999999, customer_id=customer.id,
                                    horizon_days=30, predicted_score=55))
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()
        response = client.delete(f"/api/customers/{customer.name}/", headers=_token("nu_owner"))
        assert response.status_code == 204
        return
    db_session.add(AIPrediction(use_case_id=999999, customer_id=customer.id,
                                horizon_days=30, predicted_score=55))
    db_session.commit()
    customer_id = customer.id
    response = client.delete(f"/api/customers/{customer.name}/", headers=_token("nu_owner"))
    assert response.status_code == 204
    db_session.expire_all()
    assert db_session.query(Customer).filter(Customer.id == customer_id).count() == 0
    assert db_session.query(AIPrediction).filter(AIPrediction.customer_id == customer_id).count() == 0


def test_commit_failure_rolls_back_customer_dependents_and_delete_audit(
    client, db_session, customer_seed, monkeypatch,
):
    from backend.main import app
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    audit_staged = []
    original_flush = Session.flush

    def observed_flush(session, *args, **kwargs):
        audit_staged.extend(row for row in session.new
                            if isinstance(row, AuditLog) and row.action == "customer.delete")
        return original_flush(session, *args, **kwargs)

    def fail_commit(session):
        # All delete work and its audit must reach the commit boundary
        # together, then the route's rollback guard restores the seed.
        session.flush()
        raise RuntimeError("synthetic commit failure")

    monkeypatch.setattr(Session, "flush", observed_flush)
    monkeypatch.setattr(Session, "commit", fail_commit)
    with TestClient(app, raise_server_exceptions=False) as failing_client:
        response = failing_client.delete(f"/api/customers/{customer_seed['name']}/",
                                         headers=_token("mut_owner"))
    assert response.status_code == 500
    assert len(audit_staged) == 1
    db_session.expire_all()
    customer_id = customer_seed["customer_id"]
    for model in (Customer, UseCase, Department, CustomerUser, Projection, CustomerAssessment,
                  ScoreHistory, Comment, AIPrediction, Notification):
        assert db_session.query(model).count() == (3 if model is CustomerUser else 1)
    assert db_session.query(Customer).filter_by(id=customer_id).one().name == customer_seed["name"]
    assert db_session.query(AuditLog).filter_by(action="customer.delete").count() == 0
