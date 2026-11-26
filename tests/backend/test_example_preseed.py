"""Vertical-determined per-department example pre-seeding.

Deterministic TestClient tests (no LLM). Two halves:

* the ``backend.example_use_cases`` registry (completeness + lookup rules);
* the bootstrap guarantee — every vertical department has at least one use
  case after a template assessment is started, with empty departments
  filled from the registry.

Fixture/auth setup mirrors ``test_assessment_bootstrap.py`` and
``test_customer_vertical.py``.
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")


from unittest.mock import patch

import pytest
from backend.example_use_cases import (
    EXAMPLE_USE_CASES,
    VERTICAL_VARIANTS,
    example_for_department,
)
from backend.models.use_case import Customer, CustomerUser, Department, UseCase, User
from backend.services.assessment_service import AssessmentService
from backend.templates import TEMPLATES
from backend.verticals import (
    DEPARTMENTS,
    VERTICALS,
    map_goal_to_department,
    resolve_departments,
)

from tests.backend.common import _token

_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"


def _assert_example_fields(e: dict, label: str) -> None:
    """Full required-field check shared by the generic + variant tests."""
    assert e["title"].strip(), label
    assert e["description"].strip(), label
    assert len(e["goals"]) == 3, label
    assert 2 <= len(e["challenges"]) <= 3, label
    assert 2 <= len(e["pain_points"]) <= 3, label
    assert e["impact_category"].strip(), label
    assert e["impact_description"].strip(), label
    assert isinstance(e["estimated_savings"], float), label
    assert isinstance(e["estimated_revenue"], float), label
    assert isinstance(e["timeline_estimate"], str) and e["timeline_estimate"], label


# ── registry unit tests (no client / no DB) ─────────────────────────────


class TestRegistryCompleteness:
    def test_every_department_has_a_generic_example(self):
        assert set(EXAMPLE_USE_CASES) == set(DEPARTMENTS)
        for dept, e in EXAMPLE_USE_CASES.items():
            _assert_example_fields(e, dept)

    def test_variant_keys_are_canonical_vertical_and_closed_department(self):
        for vertical, depts in VERTICAL_VARIANTS.items():
            assert vertical in VERTICALS, vertical
            for dept, e in depts.items():
                assert dept in DEPARTMENTS, (vertical, dept)
                _assert_example_fields(e, f"{vertical}/{dept}")


class TestExampleForDepartment:
    def test_variant_selected_when_defined(self):
        got = example_for_department("Finance", "Financial Services")
        assert got is VERTICAL_VARIANTS["Financial Services"]["Finance"]

    def test_generic_fallback_when_no_variant(self):
        # Financial Services has no Operations variant.
        got = example_for_department("Operations", "Financial Services")
        assert got is EXAMPLE_USE_CASES["Operations"]

    def test_case_insensitive_vertical(self):
        got = example_for_department("Finance", "financial services")
        assert got is VERTICAL_VARIANTS["Financial Services"]["Finance"]

    def test_other_none_unknown_vertical_gives_generic(self):
        for v in ("Other", None, "Plumbing & Ducts"):
            assert example_for_department("Marketing", v) is EXAMPLE_USE_CASES["Marketing"]

    def test_unknown_department_raises(self):
        with pytest.raises(ValueError):
            example_for_department("Not A Department", "Financial Services")


# ── bootstrap guarantee (TestClient + temp DB) ──────────────────────────

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
    owner = _make_user("ps_owner")
    db_session.add(owner)
    db_session.flush()

    retail = Customer(name="PsRetail", description="r", vertical="Retail & E-Commerce")
    other = Customer(name="PsOther", description="o", vertical="Other")
    other2 = Customer(name="PsOther2", description="o2", vertical="Other")
    db_session.add_all([retail, other, other2])
    db_session.flush()
    for cust in (retail, other, other2):
        db_session.add(CustomerUser(customer_id=cust.id, user_id=owner.id, role="owner"))
    db_session.commit()
    return {"retail": retail, "other": other, "other2": other2}


def _bootstrap(client, customer_name, template_id, username="ps_owner"):
    return client.post(
        f"/api/customers/{customer_name}/assessments/from-template/",
        json={"template_id": template_id},
        headers=_token(username),
    )


def _ucs(db_session, customer_id):
    return db_session.query(UseCase).filter(UseCase.customer_id == customer_id).all()


def test_guarantee_fills_empty_departments(client, db_session, env):
    template_id = "customer-support"
    dept_names = resolve_departments("Retail & E-Commerce")
    goals = TEMPLATES[template_id]["default_goals"]
    tmpl_dept = TEMPLATES[template_id].get("default_department")
    mapped = {
        map_goal_to_department(g, dept_names, tmpl_dept, i) for i, g in enumerate(goals)
    }
    # Self-documenting pre-condition: this template does NOT cover the 4-set.
    assert len(mapped) < 4

    r = _bootstrap(client, "PsRetail", template_id)
    assert r.status_code == 201
    body = r.json()

    cust = db_session.query(Customer).filter(Customer.name == "PsRetail").first()
    depts = db_session.query(Department).filter(Department.customer_id == cust.id).all()
    by_id = {d.id: d.name for d in depts}
    ucs = _ucs(db_session, cust.id)
    per_dept: dict[str, int] = {name: 0 for name in dept_names}
    for uc in ucs:
        per_dept[by_id[uc.department_id]] += 1
    for name in dept_names:
        assert per_dept[name] >= 1, name

    active = AssessmentService.get_active(db_session, cust.id)
    preseeded_titles = {p["title"] for p in body["preseeded"]}
    # Marketing + Sales have Retail variants; Operations falls back to generic.
    assert VERTICAL_VARIANTS["Retail & E-Commerce"]["Marketing"]["title"] in preseeded_titles
    assert VERTICAL_VARIANTS["Retail & E-Commerce"]["Sales"]["title"] in preseeded_titles
    assert EXAMPLE_USE_CASES["Operations"]["title"] in preseeded_titles

    preseeded_ids = {p["id"] for p in body["preseeded"]}
    for uc in ucs:
        if uc.id in preseeded_ids:
            assert uc.status == "draft"
            assert uc.created_by == "ps_owner"
            assert uc.assessment_id == active.id
            assert uc.department_id in by_id


def test_template_covering_four_departments_no_preseed(client, db_session, env):
    template_id = "marketing-personalization"
    dept_names = resolve_departments("Other")
    goals = TEMPLATES[template_id]["default_goals"]
    tmpl_dept = TEMPLATES[template_id].get("default_department")
    mapped = {
        map_goal_to_department(g, dept_names, tmpl_dept, i) for i, g in enumerate(goals)
    }
    assert mapped == set(dept_names)  # pre-condition: covers the full 4-set

    r = _bootstrap(client, "PsOther2", template_id)
    assert r.status_code == 201
    body = r.json()
    assert body["preseeded"] == []
    assert body["count"] == 4


def test_other_vertical_gets_generic_examples(client, db_session, env):
    r = _bootstrap(client, "PsOther", "customer-support")
    assert r.status_code == 201
    body = r.json()
    titles = {p["title"] for p in body["preseeded"]}
    # Other → DEFAULT_DEPARTMENTS; goals all map to Customer Success, so
    # Operations / Finance / IT are pre-seeded with the generic examples.
    assert titles == {
        EXAMPLE_USE_CASES["Operations"]["title"],
        EXAMPLE_USE_CASES["Finance"]["title"],
        EXAMPLE_USE_CASES["IT"]["title"],
    }


def test_rebootstrap_is_preseed_idempotent(client, db_session, env):
    r1 = _bootstrap(client, "PsRetail", "customer-support")
    assert r1.status_code == 201
    cust = db_session.query(Customer).filter(Customer.name == "PsRetail").first()
    ucs_after_first = {u.id for u in _ucs(db_session, cust.id)}

    r2 = _bootstrap(client, "PsRetail", "customer-support")
    assert r2.status_code == 201
    assert r2.json()["preseeded"] == []

    depts = db_session.query(Department).filter(Department.customer_id == cust.id).all()
    by_id = {d.id: d.name for d in depts}
    per_dept: dict[str, int] = {}
    for uc in _ucs(db_session, cust.id):
        per_dept[by_id[uc.department_id]] = per_dept.get(by_id[uc.department_id], 0) + 1
    # The 3 pre-seeded departments still hold exactly their one example UC.
    for name in ("Operations", "Marketing", "Sales"):
        assert per_dept[name] == 1
    # Every use case from the first call is still present (nothing rewritten).
    assert ucs_after_first <= {u.id for u in _ucs(db_session, cust.id)}


def test_wire_contract_has_preseeded_list(client, db_session, env):
    r = _bootstrap(client, "PsRetail", "customer-support")
    assert r.status_code == 201
    body = r.json()
    assert isinstance(body["preseeded"], list) and body["preseeded"]
    for entry in body["preseeded"]:
        assert set(entry) == {"id", "title", "department"}
        assert isinstance(entry["id"], int)
        assert entry["title"]
        assert entry["department"] in DEPARTMENTS


# ── fill-empty-only edge cases ─────────


def test_preexisting_uc_in_department_gets_no_preseed(client, db_session, env):
    """A department that already holds a use case before the bootstrap must
    NOT receive a pre-seeded example, and the existing row is untouched."""
    cust = db_session.query(Customer).filter(Customer.name == "PsRetail").first()
    dept_names = resolve_departments("Retail & E-Commerce")
    goals = TEMPLATES["customer-support"]["default_goals"]
    tmpl_dept = TEMPLATES["customer-support"].get("default_department")
    mapped = {
        map_goal_to_department(g, dept_names, tmpl_dept, i)
        for i, g in enumerate(goals)
    }
    # Pick a 4-set department the template goals do NOT map to, and give it
    # a use case created BEFORE the bootstrap (e.g. by an assessor manually).
    empty_dept = next(d for d in dept_names if d not in mapped)
    dept = Department(name=empty_dept, customer_id=cust.id)
    db_session.add(dept)
    db_session.flush()
    existing = UseCase(
        title="Pre-existing manual use case",
        description="created before the bootstrap",
        customer_id=cust.id,
        department=empty_dept,
        status="active",
        goals=["Existing goal"],
    )
    existing.department_obj = dept
    db_session.add(existing)
    db_session.commit()
    existing_id = existing.id

    r = _bootstrap(client, "PsRetail", "customer-support")
    assert r.status_code == 201
    body = r.json()
    assert empty_dept not in {p["department"] for p in body["preseeded"]}
    # The pre-existing row is present and unchanged.
    ucs = _ucs(db_session, cust.id)
    pre = next(u for u in ucs if u.id == existing_id)
    assert pre.title == "Pre-existing manual use case"
    assert pre.status == "active"
    assert pre.department_id == dept.id


def test_null_legacy_vertical_bootstrap_uses_generic_examples(client, db_session, env):
    """A legacy customer row with vertical=NULL gets the default 4-set and
    GENERIC examples (no variant is defined for None)."""
    owner = db_session.query(User).filter(User.username == "ps_owner").first()
    legacy = Customer(name="PsLegacy", description="legacy (vertical unset)", vertical=None)
    db_session.add(legacy)
    db_session.flush()
    db_session.add(CustomerUser(customer_id=legacy.id, user_id=owner.id, role="owner"))
    db_session.commit()

    r = _bootstrap(client, "PsLegacy", "customer-support")
    assert r.status_code == 201
    body = r.json()
    default4 = resolve_departments(None)
    goals = TEMPLATES["customer-support"]["default_goals"]
    tmpl_dept = TEMPLATES["customer-support"].get("default_department")
    mapped = {
        map_goal_to_department(g, default4, tmpl_dept, i) for i, g in enumerate(goals)
    }
    expected = set(default4) - mapped
    assert {p["department"] for p in body["preseeded"]} == expected
    for p in body["preseeded"]:
        assert p["title"] == EXAMPLE_USE_CASES[p["department"]]["title"]
        assert p["department"] in DEPARTMENTS
