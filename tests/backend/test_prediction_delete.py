"""Regression tests for saved analytics prediction deletion."""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")


from unittest.mock import patch

import pytest
from backend.models.use_case import AIPrediction, Customer, CustomerUser, UseCase, User

_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"



@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
    """Keep JWT user and CustomerUser lookups on the shared test database."""
    from backend import auth as auth_mod

    bind = db_session.get_bind()
    shared_engine = getattr(bind, "engine", bind)

    def _lookup(username):
        user = db_session.query(User).filter(User.username == username).first()
        if not (user and user.is_active):
            return None
        return {
            "username": user.username,
            "email": user.email,
            "display_name": user.display_name,
            "department": user.department,
            "is_admin": user.is_admin,
            "role": user.role,
            "user_id": user.id,
        }

    with patch.object(auth_mod, "_get_user_by_username", _lookup), \
         patch.object(auth_mod, "create_engine", lambda *args, **kwargs: shared_engine):
        yield


def _token(username):
    from backend.auth import create_access_token

    token = create_access_token({"sub": username})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def prediction_seed(db_session):
    customer = Customer(name="prediction-delete-customer", description="Test")
    db_session.add(customer)
    db_session.flush()

    users = {}
    for username, role in (("pred_owner", "owner"),
                           ("pred_member", "member"),
                           ("pred_auditor", "auditor"),
                           ("pred_outsider", None)):
        user = User(
            username=username,
            email=f"{username}@test.local",
            hashed_password=_FAKE_BCRYPT_HASH,
            display_name=username,
            department="IT",
            is_admin=0,
            approved=1,
            is_active=1,
        )
        db_session.add(user)
        db_session.flush()
        users[username] = user
        if role:
            db_session.add(CustomerUser(
                customer_id=customer.id, user_id=user.id, role=role,
            ))

    use_case = UseCase(
        title="Customer prediction", customer_id=customer.id,
        department="IT", status="active", overall_score=60.0,
    )
    unassigned_use_case = UseCase(
        title="Unassigned prediction", customer_id=None,
        department="IT", status="active", overall_score=50.0,
    )
    db_session.add_all([use_case, unassigned_use_case])
    db_session.flush()

    prediction = AIPrediction(
        use_case_id=use_case.id, customer_id=customer.id,
        horizon_days=45, predicted_score=70.0,
    )
    unassigned_prediction = AIPrediction(
        use_case_id=unassigned_use_case.id, customer_id=None,
        horizon_days=45, predicted_score=55.0,
    )
    db_session.add_all([prediction, unassigned_prediction])
    db_session.commit()

    return {
        "customer_id": customer.id,
        "prediction_id": prediction.id,
        "unassigned_prediction_id": unassigned_prediction.id,
    }


def test_delete_requires_authentication(client, prediction_seed):
    response = client.delete(
        f"/api/analytics/predictions/{prediction_seed['prediction_id']}/"
    )
    assert response.status_code == 401


def test_member_cannot_delete(client, prediction_seed):
    response = client.delete(
        f"/api/analytics/predictions/{prediction_seed['prediction_id']}/",
        headers=_token("pred_member"),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Global admin or customer owner role required"


def test_auditor_cannot_delete(client, prediction_seed):
    response = client.delete(
        f"/api/analytics/predictions/{prediction_seed['prediction_id']}/",
        headers=_token("pred_auditor"),
    )
    assert response.status_code == 403


def test_outsider_delete_is_404(client, prediction_seed):
    # 404-first (R4/Q7): out-of-scope is the same 404 as a missing prediction.
    response = client.delete(
        f"/api/analytics/predictions/{prediction_seed['prediction_id']}/",
        headers=_token("pred_outsider"),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Prediction not found"


def test_owner_can_delete_and_prediction_disappears_from_list(client, prediction_seed):
    prediction_id = prediction_seed["prediction_id"]
    response = client.delete(
        f"/api/analytics/predictions/{prediction_id}/",
        headers=_token("pred_owner"),
    )
    assert response.status_code == 200
    assert response.json() == {"message": f"Prediction {prediction_id} deleted"}

    listed = client.get(
        f"/api/analytics/predictions/?customer_id={prediction_seed['customer_id']}",
        headers=_token("pred_owner"),
    )
    assert listed.status_code == 200
    assert prediction_id not in {row["id"] for row in listed.json()}


def test_global_admin_can_delete_without_customer_junction(client, db_session, prediction_seed):
    prediction_id = prediction_seed["prediction_id"]
    response = client.delete(
        f"/api/analytics/predictions/{prediction_id}/",
        headers=_token("admin"),
    )
    assert response.status_code == 200
    db_session.expire_all()
    assert db_session.query(AIPrediction).filter(AIPrediction.id == prediction_id).first() is None


def test_missing_prediction_returns_404(client, prediction_seed):
    response = client.delete(
        "/api/analytics/predictions/999999/", headers=_token("admin")
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Prediction not found"


def test_admin_can_delete_unassigned_prediction(client, prediction_seed):
    response = client.delete(
        f"/api/analytics/predictions/{prediction_seed['unassigned_prediction_id']}/",
        headers=_token("admin"),
    )
    assert response.status_code == 200


def test_non_admin_cannot_delete_unassigned_prediction(client, prediction_seed):
    response = client.delete(
        f"/api/analytics/predictions/{prediction_seed['unassigned_prediction_id']}/",
        headers=_token("pred_member"),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Prediction has no customer assignment"
