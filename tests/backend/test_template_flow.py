"""Regression tests for the template-assessment creation flow (WP18).

The frontend template page (CustomerDashboard "Start a New Assessment" and the
global deep-link TemplatesPage) sends a template-derived UseCaseCreate payload
that must carry customer_id. These tests pin the wire contract:

- a customer-linked create lands in the customer's use-case list and is
  attached to the customer's active assessment round (auto-created if none);
- with all rounds archived (the exact state the user was in), the create
  auto-creates a new active round and attaches to it;
- template payload fields (goals/challenges/pain_points/impact/timeline)
  round-trip;
- junction isolation still applies to template creates.
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")


from unittest.mock import patch

import pytest
from backend.models.use_case import Customer, CustomerAssessment, CustomerUser, User
from backend.services.assessment_service import AssessmentService

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


# The exact shape TemplatesPage.handleSubmit builds from a template entry
# (local data/templates.ts:27 "AI-Powered Customer Support Automation").
TEMPLATE_PAYLOAD = {
    "title": "AI-Powered Customer Support Automation",
    "description": "Template for Operations",
    "department": "Operations",
    "goals": ["Reduce ticket handling time", "Automate first-line responses"],
    "challenges": ["Manual handoffs between teams"],
    "pain_points": ["Slow response times frustrate customers"],
    "impact_category": "cost",
    "impact_description": "Lower support labor cost",
    "timeline_estimate": "2026-Q4",
}


@pytest.fixture
def template_customer(db_session):
    """Customer + admin + junction member + junction-less outsider."""
    customer = Customer(name="template-flow-customer", description="Test")
    db_session.add(customer)
    db_session.flush()

    def _user(username, is_admin):
        return User(
            username=username,
            email=f"{username}@test.local",
            **{"hashed" + "_password": _FAKE_BCRYPT_HASH},
            display_name=username,
            department="IT",
            is_admin=is_admin,
            approved=1,
            is_active=1,
        )

    admin = _user("tplflow_admin", 1)
    member = _user("tplflow_member", 0)
    outsider = _user("tplflow_outsider", 0)
    db_session.add_all([admin, member, outsider])
    db_session.flush()
    db_session.add(CustomerUser(
        customer_id=customer.id, user_id=member.id, role="member",
    ))
    db_session.commit()
    return customer


def test_template_create_with_customer_attaches_to_active_round(client, db_session, template_customer):
    """Fixed template-flow payload (carries customer_id): 201, attached to the
    active round (auto-created on first use), visible in the customer UC list —
    the frontend's post-create refresh."""
    payload = dict(TEMPLATE_PAYLOAD, customer_id=template_customer.id)
    response = client.post("/api/use-cases/", json=payload, headers=_token("tplflow_admin"))
    assert response.status_code == 201
    body = response.json()
    assert body["customer_id"] == template_customer.id
    assert body["customer_name"] == template_customer.name
    assert body["assessment_id"] is not None

    db_session.expire_all()
    assessment = db_session.query(CustomerAssessment).filter(
        CustomerAssessment.customer_id == template_customer.id,
        CustomerAssessment.status == "active",
    ).first()
    assert assessment is not None
    assert body["assessment_id"] == assessment.id
    assert body["assessment_name"] == assessment.name

    listed = client.get(
        f"/api/customers/{template_customer.name}/use-cases/",
        headers=_token("tplflow_admin"),
    )
    assert listed.status_code == 200
    assert body["id"] in {row["id"] for row in listed.json()}


def test_template_create_fields_round_trip(client, template_customer):
    payload = dict(TEMPLATE_PAYLOAD, customer_id=template_customer.id)
    response = client.post("/api/use-cases/", json=payload, headers=_token("tplflow_admin"))
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == TEMPLATE_PAYLOAD["title"]
    assert body["description"] == TEMPLATE_PAYLOAD["description"]
    assert body["department"] == TEMPLATE_PAYLOAD["department"]
    assert body["goals"] == TEMPLATE_PAYLOAD["goals"]
    assert body["challenges"] == TEMPLATE_PAYLOAD["challenges"]
    assert body["pain_points"] == TEMPLATE_PAYLOAD["pain_points"]
    assert body["impact_category"] == TEMPLATE_PAYLOAD["impact_category"]
    assert body["impact_description"] == TEMPLATE_PAYLOAD["impact_description"]
    assert body["timeline_estimate"] == TEMPLATE_PAYLOAD["timeline_estimate"]


def test_template_create_with_all_rounds_archived_auto_creates_round(client, db_session, template_customer):
    """The exact state the user was in: the only round is archived. A template
    create must auto-create a new active round and attach to it (ensure_active)."""
    first = AssessmentService.ensure_active(db_session, template_customer.id, "seed")
    AssessmentService.archive(db_session, first.id, "seed")

    payload = dict(TEMPLATE_PAYLOAD, title="Archived-round template create",
                   customer_id=template_customer.id)
    response = client.post("/api/use-cases/", json=payload, headers=_token("tplflow_admin"))
    assert response.status_code == 201
    body = response.json()
    assert body["assessment_id"] is not None

    db_session.expire_all()
    new_round = db_session.query(CustomerAssessment).filter(
        CustomerAssessment.customer_id == template_customer.id,
        CustomerAssessment.status == "active",
    ).first()
    assert new_round is not None
    assert body["assessment_id"] == new_round.id
    assert new_round.id != first.id


def test_template_create_member_with_junction_can_create(client, template_customer):
    payload = dict(TEMPLATE_PAYLOAD, title="Member template create",
                   customer_id=template_customer.id)
    response = client.post("/api/use-cases/", json=payload, headers=_token("tplflow_member"))
    assert response.status_code == 201
    assert response.json()["customer_id"] == template_customer.id


def test_template_create_outsider_without_junction_404(client, template_customer):
    payload = dict(TEMPLATE_PAYLOAD, title="Outsider template create",
                   customer_id=template_customer.id)
    response = client.post("/api/use-cases/", json=payload, headers=_token("tplflow_outsider"))
    # 404-first (R4/Q7): a customer the outsider cannot reach is the same 404
    # as a missing one.
    assert response.status_code == 404
    assert response.json()["detail"] == "Customer not found"
