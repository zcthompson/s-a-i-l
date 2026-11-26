"""WP3 — contract/type hygiene (audit P1): wire-contract regression tests.

Pins the backend contract fixes for v0.0.68 WP3:

- P1-1: notification ``read`` is a JSON **bool** on the wire (the schema
  used to declare ``read: int``; the model to_dict already emitted a bool,
  which the response_model coerced to 0/1).
- P1-2: GET /api/use-cases/ and GET /api/use-cases/{id}/ both expose
  ``assessment_id``/``assessment_name`` (the list route's UseCaseResponse
  used to strip them; the detail route now shares the same response_model,
  so both routes serve the identical field set).
- P1-3: GET /api/scoring/dimensions/ returns {name, weight} entries (the
  response_model was an untyped ``list``).
- P1-4: a malformed ``?customer_id`` on the list route is a 422 (was a 500
  from an unguarded ``int()``).

Run: pytest tests/backend/test_contract_hygiene.py -v
"""


from unittest.mock import patch

import pytest

_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"



@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
    """Route-level auth: point the real JWT user lookup at the shared
    session (test_integration.py pattern)."""
    from backend.models.use_case import User

    from backend import auth as auth_mod

    bind = db_session.get_bind()
    shared_engine = getattr(bind, "engine", bind)

    if not db_session.query(User).count():
        db_session.add(User(username="admin", email="admin@test.local",
                            hashed_password=_FAKE_BCRYPT_HASH,
                            display_name="Administrator", department="IT",
                            is_admin=1, approved=1, is_active=1))
        db_session.commit()

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

    def _shared_engine(*args, **kwargs):
        return shared_engine

    with patch.object(auth_mod, "_get_user_by_username", _lookup), \
         patch.object(auth_mod, "create_engine", _shared_engine):
        yield


@pytest.fixture()
def auth(db_session):
    """Authorization header for the seeded admin user."""
    from backend.auth import create_access_token
    from backend.models.use_case import User

    admin = db_session.query(User).filter(User.is_admin == 1).first()
    return {
        "Authorization":
            f"Bearer {create_access_token({'sub': admin.username, 'is_admin': True})}"
    }


class TestNotificationReadBool:
    def test_read_is_json_bool(self, client, db_session, auth):
        from backend.models.collaboration import Notification

        db_session.add(Notification(user_name="admin", type="comment",
                                    message="WP3 contract probe", read=0))
        db_session.commit()

        r = client.get("/api/use-cases/notifications/", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        item = next(n for n in data if n.get("message") == "WP3 contract probe")
        # bool, not int 0/1 — asserted at the JSON level
        assert item["read"] is False


class TestUseCaseAssessmentFields:
    def test_list_and_detail_expose_assessment_fields(self, client, db_session, auth):
        from backend.models.use_case import Customer, UseCase
        from backend.services.assessment_service import AssessmentService

        c = Customer(name="WP3Co", description="wp3 contract seed")
        db_session.add(c)
        db_session.commit()
        db_session.refresh(c)

        assessment = AssessmentService.create(db_session, c.id, "Round A", "admin")

        uc = UseCase(title="WP3 UC", department="Operations", status="active",
                     customer_id=c.id, assessment_id=assessment.id)
        db_session.add(uc)
        db_session.commit()
        db_session.refresh(uc)

        # List route (UseCaseResponse response_model used to strip these)
        r = client.get(f"/api/use-cases/?customer_id={c.id}", headers=auth)
        assert r.status_code == 200
        row = next(x for x in r.json() if x["id"] == uc.id)
        assert row["assessment_id"] == assessment.id
        assert row["assessment_name"] == "Round A"

        # Detail route (now shares the same response_model)
        r = client.get(f"/api/use-cases/{uc.id}/", headers=auth)
        assert r.status_code == 200
        detail = r.json()
        assert detail["assessment_id"] == assessment.id
        assert detail["assessment_name"] == "Round A"
        # score_history is not part of the use-case contract (the drill-down
        # endpoint serves history) — identical field set on both routes.
        assert "score_history" not in detail

    def test_malformed_customer_id_422(self, client, auth):
        """Was a 500 from an unguarded int(); FastAPI now validates the
        query param -> 422."""
        r = client.get("/api/use-cases/?customer_id=not-an-int", headers=auth)
        assert r.status_code == 422

    def test_valid_numeric_customer_id_still_filters(self, client, db_session, auth):
        """Regression guard: a numeric customer_id string still parses and
        filters (the common ?customer_id=1 call shape from the UI)."""
        from backend.models.use_case import Customer, UseCase

        c = Customer(name="WP3FilterCo", description="wp3 filter seed")
        db_session.add(c)
        db_session.commit()
        db_session.refresh(c)

        db_session.add(UseCase(title="WP3 Filtered UC", department="Operations",
                               status="active", customer_id=c.id))
        db_session.commit()

        r = client.get(f"/api/use-cases/?customer_id={c.id}", headers=auth)
        assert r.status_code == 200
        rows = r.json()
        assert rows and all(x["customer_id"] == c.id for x in rows)


class TestDimensionsPayload:
    def test_dimensions_are_name_weight_pairs(self, client):
        """Public route; each entry is exactly {name, weight}."""
        r = client.get("/api/scoring/dimensions/")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 6
        for entry in data:
            assert set(entry.keys()) == {"name", "weight"}
            assert isinstance(entry["name"], str)
            assert isinstance(entry["weight"], (int, float))
