"""WP19 — vertical-aware template-assessment bootstrap.

Deterministic TestClient tests (no LLM). Verifies that starting a
template assessment for a customer seeds the vertical's 4 departments and
one draft use case per template goal, attached to the active round.
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")


from unittest.mock import patch

import pytest
from backend.models.use_case import (
    Customer,
    CustomerAssessment,
    CustomerUser,
    Department,
    UseCase,
    User,
)
from backend.services.assessment_service import AssessmentService
from backend.templates import TEMPLATES

from tests.backend.common import _token

_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"

@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
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
         patch.object(auth_mod, "create_engine", lambda *a, **k: shared_engine):
        yield




def _make_user(name, is_admin=0):
    return User(
        username=name, email=f"{name}@test.local",
        hashed_password=_FAKE_BCRYPT_HASH,
        display_name=name, department="IT",
        is_admin=is_admin, approved=1, is_active=1,
    )


@pytest.fixture
def env(db_session):
    admin = _make_user("bs_admin", 1)
    owner = _make_user("bs_owner")
    member = _make_user("bs_member")
    outsider = _make_user("bs_outsider")
    db_session.add_all([admin, owner, member, outsider])
    db_session.flush()

    retail = Customer(name="RetailCust", description="r", vertical="Retail & E-Commerce")
    other = Customer(name="OtherCust", description="o", vertical="Other")
    legacy = Customer(name="LegacyCust", description="l")  # vertical NULL
    db_session.add_all([retail, other, legacy])
    db_session.flush()

    for cust in (retail, other, legacy):
        db_session.add(CustomerUser(customer_id=cust.id, user_id=owner.id, role="owner"))
        db_session.add(CustomerUser(customer_id=cust.id, user_id=member.id, role="member"))
    db_session.commit()
    return {"retail": retail, "other": other, "legacy": legacy}


def _bootstrap(client, customer_name, template_id, username, is_admin=False):
    return client.post(
        f"/api/customers/{customer_name}/assessments/from-template/",
        json={"template_id": template_id},
        headers=_token(username, is_admin),
    )


RETAIL_DEPTS = {"Customer Success", "Operations", "Marketing", "Sales"}
DEFAULT_DEPTS = {"Customer Success", "Operations", "Finance", "IT"}


def test_retail_customer_support_bootstrap(client, db_session, env):
    r = _bootstrap(client, "RetailCust", "customer-support", "bs_owner")
    assert r.status_code == 201
    body = r.json()

    cust = db_session.query(Customer).filter(Customer.name == "RetailCust").first()
    depts = db_session.query(Department).filter(Department.customer_id == cust.id).all()
    assert {d.name for d in depts} == RETAIL_DEPTS
    assert all(d["created"] for d in body["departments"])

    goals = TEMPLATES["customer-support"]["default_goals"]
    ucs = db_session.query(UseCase).filter(UseCase.customer_id == cust.id).all()
    # Documented contract update (WP21): the 4 customer-support goals all
    # keyword-map to Customer Success, so the other 3 Retail departments
    # (Operations, Marketing, Sales) are pre-seeded with one example UC
    # each. count = 4 goal UCs + 3 pre-seeded = 7.
    assert len(body["preseeded"]) == 3
    assert len(ucs) == len(goals) + len(body["preseeded"]) == body["count"] == 7
    dept_ids = {d.id for d in depts}
    active = AssessmentService.get_active(db_session, cust.id)
    goal_ucs = sorted(ucs, key=lambda u: u.id)[:len(goals)]
    for uc, goal in zip(goal_ucs, goals):
        assert uc.goals == [goal]
        assert uc.status == "draft"
        assert uc.created_by == "bs_owner"
        assert uc.department_id in dept_ids
        assert uc.department in RETAIL_DEPTS
        assert uc.assessment_id == active.id
        assert uc.description == TEMPLATES["customer-support"]["description"]
        assert uc.challenges == TEMPLATES["customer-support"]["default_challenges"]
        assert uc.pain_points == TEMPLATES["customer-support"]["default_pain_points"]
        assert uc.impact_category == TEMPLATES["customer-support"]["impact_category"]
        assert uc.impact_description == TEMPLATES["customer-support"]["impact_description"]
        assert uc.timeline_estimate == TEMPLATES["customer-support"]["timeline"]

    listed = client.get("/api/customers/RetailCust/use-cases/", headers=_token("bs_owner"))
    assert {row["id"] for row in listed.json()} == {u.id for u in ucs}


def test_other_vertical_default_departments(client, db_session, env):
    r = _bootstrap(client, "OtherCust", "customer-support", "bs_owner")
    assert r.status_code == 201
    cust = db_session.query(Customer).filter(Customer.name == "OtherCust").first()
    depts = db_session.query(Department).filter(Department.customer_id == cust.id).all()
    assert {d.name for d in depts} == DEFAULT_DEPTS


def test_legacy_null_vertical_default_departments(client, db_session, env):
    r = _bootstrap(client, "LegacyCust", "customer-support", "bs_owner")
    assert r.status_code == 201
    cust = db_session.query(Customer).filter(Customer.name == "LegacyCust").first()
    depts = db_session.query(Department).filter(Department.customer_id == cust.id).all()
    assert {d.name for d in depts} == DEFAULT_DEPTS


def test_bootstrap_twice_is_department_idempotent(client, db_session, env):
    r1 = _bootstrap(client, "RetailCust", "customer-support", "bs_owner")
    assert r1.status_code == 201
    r2 = _bootstrap(client, "RetailCust", "customer-support", "bs_owner")
    assert r2.status_code == 201
    assert all(d["created"] is False for d in r2.json()["departments"])

    cust = db_session.query(Customer).filter(Customer.name == "RetailCust").first()
    depts = db_session.query(Department).filter(Department.customer_id == cust.id).all()
    assert len(depts) == 4
    ucs = db_session.query(UseCase).filter(UseCase.customer_id == cust.id).all()
    # Documented contract update (WP21): first bootstrap seeds 4 goal UCs
    # (all Customer Success) + 3 pre-seeded examples (Operations, Marketing,
    # Sales) = 7. The second bootstrap re-seeds the 4 goal UCs but pre-seeds
    # nothing (every department now has ≥1 UC) → 7 + 4 = 11.
    assert len(ucs) == 11
    assert r2.json()["preseeded"] == []


def test_existing_active_round_reused(client, db_session, env):
    cust = db_session.query(Customer).filter(Customer.name == "RetailCust").first()
    existing = AssessmentService.ensure_active(db_session, cust.id, "seed")
    _bootstrap(client, "RetailCust", "customer-support", "bs_owner")
    db_session.expire_all()
    rounds = db_session.query(CustomerAssessment).filter(
        CustomerAssessment.customer_id == cust.id).all()
    assert len(rounds) == 1
    assert rounds[0].id == existing.id


def test_all_archived_creates_new_round(client, db_session, env):
    cust = db_session.query(Customer).filter(Customer.name == "RetailCust").first()
    first = AssessmentService.ensure_active(db_session, cust.id, "seed")
    AssessmentService.archive(db_session, first.id, "seed")
    r = _bootstrap(client, "RetailCust", "customer-support", "bs_owner")
    assert r.status_code == 201
    db_session.expire_all()
    active = AssessmentService.get_active(db_session, cust.id)
    assert active is not None and active.id != first.id
    ucs = db_session.query(UseCase).filter(UseCase.customer_id == cust.id).all()
    assert all(uc.assessment_id == active.id for uc in ucs)


def test_access_owner_member_ok_outsider_404_anon_401(client, env):
    assert _bootstrap(client, "RetailCust", "customer-support", "bs_owner").status_code == 201
    assert _bootstrap(client, "OtherCust", "customer-support", "bs_member").status_code == 201
    r = _bootstrap(client, "RetailCust", "customer-support", "bs_outsider")
    # 404-first (R4/Q7): an outsider (no grant) gets the same 404 as a
    # missing customer.
    assert r.status_code == 404
    assert r.json()["detail"] == "Customer not found"
    anon = client.post(
        "/api/customers/RetailCust/assessments/from-template/",
        json={"template_id": "customer-support"},
    )
    assert anon.status_code == 401


def test_admin_bootstrap_ok(client, env):
    assert _bootstrap(client, "RetailCust", "customer-support", "bs_admin", True).status_code == 201


def test_unknown_template_404(client, env):
    r = _bootstrap(client, "RetailCust", "no-such-template", "bs_owner")
    assert r.status_code == 404


def test_three_goal_template_seeds_three(client, db_session, env):
    r = _bootstrap(client, "RetailCust", "operations", "bs_owner")
    assert r.status_code == 201
    # Documented contract update (WP21): the 3 "operations" goals all map to
    # Operations, so the other 3 Retail departments (Customer Success,
    # Marketing, Sales) are pre-seeded → count = 3 goal UCs + 3 examples = 6.
    body = r.json()
    assert len(body["use_cases"]) == 3
    assert len(body["preseeded"]) == 3
    assert body["count"] == 6
    cust = db_session.query(Customer).filter(Customer.name == "RetailCust").first()
    ucs = db_session.query(UseCase).filter(UseCase.customer_id == cust.id).all()
    assert len(ucs) == 6


def test_unknown_customer_404(client, env):
    r = _bootstrap(client, "NoSuchCust", "customer-support", "bs_admin", True)
    assert r.status_code == 404
