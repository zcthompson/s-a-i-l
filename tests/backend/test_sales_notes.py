"""Sales Notes (S-A-I-L) tests — service CRUD, junction validation, route auth.

Route tests follow the repo's TestClient auth pattern (test_customer_knowledge.py):
a real JWT via create_access_token. Access is gated by the CustomerUser
junction WITH admin bypass (admins own all customers — the customers.py /
sales_section.py / customer_knowledge.py / sales_evaluations.py /
technology_inventory.py convention): non-admin tests use a member user +
junction row; admin-bypass tests use the junction-less seeded admin.

Junction isolation (CHANGELOG 0.0.80 items 17-18): a note may only
link its own customer's technologies and use cases — cross-customer or
missing ids are rejected with 422, both at the service and route layers.
"""

from datetime import date

import pytest
from backend.models.sales_note import SalesNote as SNModel

from tests.backend.common import _admin_headers


def _non_admin_headers(db_session, customer_id: int = 1) -> dict:
    """Authorization header for a non-admin user with a CustomerUser row."""
    from backend.auth import create_access_token
    from backend.models.use_case import Customer, CustomerUser, User

    username = f"note_member_{customer_id}"
    user = db_session.query(User).filter(User.username == username).first()
    if not user:
        user = User(
            username=username,
            email=f"{username}@test.local",
            hashed_password="unused...ests",
            is_admin=0,
            approved=1,
            is_active=1,
        )
        db_session.add(user)
        db_session.commit()
    existing = db_session.query(Customer).filter(Customer.id == customer_id).first()
    if not existing:
        db_session.add(Customer(id=customer_id, name=f"Note Test Customer {customer_id}"))
        db_session.commit()
    existing_cu = (
        db_session.query(CustomerUser)
        .filter(CustomerUser.customer_id == customer_id)
        .filter(CustomerUser.user_id == user.id)
        .first()
    )
    if not existing_cu:
        db_session.add(
            CustomerUser(customer_id=customer_id, user_id=user.id, role="member")
        )
        db_session.commit()
    token = create_access_token({"sub": user.username, "is_admin": False})
    return {"Authorization": f"Bearer {token}"}


def _seed_customer(db_session, customer_id: int = 1) -> None:
    """Ensure a Customer row exists (for route tests)."""
    from backend.models.use_case import Customer

    existing = db_session.query(Customer).filter(Customer.id == customer_id).first()
    if not existing:
        db_session.add(Customer(id=customer_id, name=f"Note Test Customer {customer_id}"))
        db_session.commit()


def _seed_tech(db_session, customer_id: int, name: str = "Test Tech") -> int:
    """Seed a Technology Inventory item; return its id."""
    from backend.services.technology_inventory_service import create_technology

    tech = create_technology(
        db_session, customer_id, {"name": name, "category": "software"}
    )
    return tech.id


def _seed_use_case(db_session, customer_id: int, title: str = "Test Use Case") -> int:
    """Seed a UseCase; return its id."""
    from backend.models.use_case import UseCase

    uc = UseCase(title=title, customer_id=customer_id)
    db_session.add(uc)
    db_session.commit()
    db_session.refresh(uc)
    return uc.id


def _note_payload(**overrides):
    """Route-test payload. note_date is an ISO string — JSON payloads carry
    strings, and Pydantic parses ISO → date. Service tests may override with
    date objects (Pydantic accepts both)."""
    base = {
        "author": "J. Rivera (S-A-I-L)",
        "source": "discovery call",
        "note_date": "2026-08-15",
        "category": "discovery",
        "title": "Discovery call notes",
        "content": "Customer described their vSphere estate and refresh plans.",
    }
    base.update(overrides)
    return base


class TestSalesNoteService:
    @pytest.fixture(autouse=True)
    def _existing_customer_parents(self, db_session):
        from backend.models.use_case import Customer
        db_session.add_all([Customer(id=1, name="Synthetic parent 1"), Customer(id=2, name="Synthetic parent 2")])
        db_session.commit()

    """Service-level CRUD and junction validation for sales notes."""

    def test_create_and_get_note(self, db_session):
        from backend.schemas.sales_note import SalesNoteCreate
        from backend.services.sales_note_service import (
            create_sales_note,
            get_sales_note,
        )

        tech_id = _seed_tech(db_session, 1)
        uc_id = _seed_use_case(db_session, 1)
        payload = SalesNoteCreate(
            **_note_payload(), related_technology_ids=[tech_id], related_use_case_ids=[uc_id]
        )
        note = create_sales_note(db_session, 1, payload)
        assert note.id is not None
        assert note.customer_id == 1
        assert note.category == "discovery"
        assert note.verification_state == "verified"  # default for human notes
        assert note.related_technology_ids == [tech_id]
        assert note.related_use_case_ids == [uc_id]
        assert get_sales_note(db_session, note.id) is not None

    def test_unknowns_stay_null(self, db_session):
        """Creating with only category/title/content leaves author/source/
        note_date NULL — unknowns stay unknown, never fabricated."""
        from backend.schemas.sales_note import SalesNoteCreate
        from backend.services.sales_note_service import create_sales_note

        note = create_sales_note(
            db_session, 1, SalesNoteCreate(**_note_payload(author=None, source=None, note_date=None))
        )
        assert note.author is None
        assert note.source is None
        assert note.note_date is None
        assert note.verification_state == "verified"
        assert note.related_technology_ids == []
        assert note.related_use_case_ids == []

    def test_update_note_preserves_unlisted_fields(self, db_session):
        from backend.schemas.sales_note import SalesNoteCreate, SalesNoteUpdate
        from backend.services.sales_note_service import (
            create_sales_note,
            update_sales_note,
        )

        note = create_sales_note(db_session, 1, SalesNoteCreate(**_note_payload()))
        updated = update_sales_note(
            db_session, note.id, SalesNoteUpdate(title="Updated title", verification_state="inferred")
        )
        assert updated.title == "Updated title"
        assert updated.verification_state == "inferred"
        assert updated.author == "J. Rivera (S-A-I-L)"  # untouched
        assert updated.content == _note_payload()["content"]

    def test_update_missing_returns_none(self, db_session):
        from backend.schemas.sales_note import SalesNoteUpdate
        from backend.services.sales_note_service import update_sales_note

        assert update_sales_note(db_session, 9999, SalesNoteUpdate(title="Nope")) is None

    def test_clearing_required_field_rejected(self, db_session):
        from backend.schemas.sales_note import SalesNoteCreate, SalesNoteUpdate
        from backend.services.sales_note_service import (
            create_sales_note,
            update_sales_note,
        )
        from fastapi import HTTPException

        note = create_sales_note(db_session, 1, SalesNoteCreate(**_note_payload()))
        with pytest.raises(HTTPException) as exc:
            update_sales_note(db_session, note.id, SalesNoteUpdate(category=None))
        assert exc.value.status_code == 422

    def test_delete_note(self, db_session):
        from backend.schemas.sales_note import SalesNoteCreate
        from backend.services.sales_note_service import (
            create_sales_note,
            delete_sales_note,
            list_sales_notes,
        )

        note = create_sales_note(db_session, 1, SalesNoteCreate(**_note_payload()))
        assert delete_sales_note(db_session, note.id) is True
        assert list_sales_notes(db_session, 1) == []
        assert delete_sales_note(db_session, note.id) is False  # already gone

    def test_invalid_category_rejected(self, db_session):
        from backend.schemas.sales_note import SalesNoteCreate
        from backend.services.sales_note_service import create_sales_note
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            create_sales_note(
                db_session, 1, SalesNoteCreate(**_note_payload(category="quantum_flux"))
            )
        assert exc.value.status_code == 422
        assert "category" in str(exc.value.detail)

    def test_invalid_verification_state_rejected(self, db_session):
        from backend.schemas.sales_note import SalesNoteCreate
        from backend.services.sales_note_service import create_sales_note
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            create_sales_note(
                db_session, 1, SalesNoteCreate(**_note_payload(verification_state="guessed"))
            )

    def test_cross_customer_tech_junction_rejected(self, db_session):
        """A note for customer 1 cannot link customer 2's technology."""
        from backend.schemas.sales_note import SalesNoteCreate
        from backend.services.sales_note_service import create_sales_note
        from fastapi import HTTPException

        other_tech = _seed_tech(db_session, 2, "Other Co Tech")
        with pytest.raises(HTTPException) as exc:
            create_sales_note(
                db_session,
                1,
                SalesNoteCreate(**_note_payload(), related_technology_ids=[other_tech]),
            )
        assert exc.value.status_code == 422

    def test_cross_customer_use_case_junction_rejected(self, db_session):
        """A note for customer 1 cannot link customer 2's use case."""
        from backend.schemas.sales_note import SalesNoteCreate
        from backend.services.sales_note_service import create_sales_note
        from fastapi import HTTPException

        other_uc = _seed_use_case(db_session, 2, "Other Co UC")
        with pytest.raises(HTTPException) as exc:
            create_sales_note(
                db_session,
                1,
                SalesNoteCreate(**_note_payload(), related_use_case_ids=[other_uc]),
            )
        assert exc.value.status_code == 422

    def test_missing_junction_ids_rejected(self, db_session):
        from backend.schemas.sales_note import SalesNoteCreate
        from backend.services.sales_note_service import create_sales_note
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            create_sales_note(
                db_session,
                1,
                SalesNoteCreate(**_note_payload(), related_technology_ids=[99999]),
            )

    def test_list_filters_and_ordering(self, db_session):
        from backend.schemas.sales_note import SalesNoteCreate
        from backend.services.sales_note_service import (
            create_sales_note,
            list_sales_notes,
        )

        create_sales_note(db_session, 1, SalesNoteCreate(**_note_payload(note_date=date(2026, 8, 1), title="Old note", category="meeting")))
        create_sales_note(db_session, 1, SalesNoteCreate(**_note_payload(note_date=date(2026, 8, 20), title="New note", category="risk", content="Storage EOL risk raised by CIO")))
        create_sales_note(db_session, 1, SalesNoteCreate(**_note_payload(note_date=date(2026, 8, 10), title="Middle note", category="meeting")))

        assert len(list_sales_notes(db_session, 1)) == 3
        # Default: newest note_date first.
        dates = [n.note_date for n in list_sales_notes(db_session, 1)]
        assert dates == sorted(dates, reverse=True)
        # Ascending.
        dates = [n.note_date for n in list_sales_notes(db_session, 1, direction="asc")]
        assert dates == sorted(dates)
        assert len(list_sales_notes(db_session, 1, category="risk")) == 1
        assert [n.title for n in list_sales_notes(db_session, 1, search="storage eol")] == ["New note"]
        # Other customer's notes never leak.
        create_sales_note(db_session, 2, SalesNoteCreate(**_note_payload(title="Other Co note")))
        assert len(list_sales_notes(db_session, 1)) == 3

    def test_junction_replacement_on_update(self, db_session):
        from backend.schemas.sales_note import SalesNoteCreate, SalesNoteUpdate
        from backend.services.sales_note_service import (
            create_sales_note,
            update_sales_note,
        )

        t1 = _seed_tech(db_session, 1, "Tech A")
        t2 = _seed_tech(db_session, 1, "Tech B")
        note = create_sales_note(
            db_session, 1, SalesNoteCreate(**_note_payload(), related_technology_ids=[t1])
        )
        assert note.related_technology_ids == [t1]
        # Replace the set.
        update_sales_note(db_session, note.id, SalesNoteUpdate(related_technology_ids=[t2]))
        refreshed = db_session.get(SNModel, note.id)
        assert refreshed.related_technology_ids == [t2]
        # Clear the set.
        update_sales_note(db_session, note.id, SalesNoteUpdate(related_technology_ids=[]))
        refreshed = db_session.get(SNModel, note.id)
        assert refreshed.related_technology_ids == []
        # Omitting the field leaves the set untouched.
        t3 = _seed_tech(db_session, 1, "Tech C")
        update_sales_note(db_session, note.id, SalesNoteUpdate(related_technology_ids=[t3]))
        update_sales_note(db_session, note.id, SalesNoteUpdate(title="Renamed"))
        refreshed = db_session.get(SNModel, note.id)
        assert refreshed.related_technology_ids == [t3]
        assert refreshed.title == "Renamed"


class TestSalesNoteRoutes:
    """Route-level authorization and CRUD for sales notes."""

    def test_unauthenticated_gets_401(self, client, db_session):
        _seed_customer(db_session, 1)
        assert client.get("/api/customers/1/sales-notes/").status_code == 401
        assert (
            client.post("/api/customers/1/sales-notes/", json=_note_payload()).status_code
            == 401
        )
        assert client.get("/api/sales-notes/1/").status_code == 401
        assert client.put("/api/sales-notes/1/", json={"title": "X"}).status_code == 401
        assert client.delete("/api/sales-notes/1/").status_code == 401

    def test_missing_customer_gets_404(self, client, db_session):
        admin = _admin_headers(db_session)
        assert client.get("/api/customers/9999/sales-notes/", headers=admin).status_code == 404
        assert (
            client.post("/api/customers/9999/sales-notes/", json=_note_payload(), headers=admin).status_code
            == 404
        )

    def test_user_without_customer_access_gets_404(self, client, db_session):
        """A member of customer 2 gets the same 404 as a missing customer on
        customer 1's notes (404-first, R4/Q7)."""
        _seed_customer(db_session, 1)
        _seed_customer(db_session, 2)
        headers = _non_admin_headers(db_session, customer_id=2)
        assert client.get("/api/customers/1/sales-notes/", headers=headers).status_code == 404
        assert (
            client.post("/api/customers/1/sales-notes/", json=_note_payload(), headers=headers).status_code
            == 404
        )

    def test_member_can_create_list_get_update_delete(self, client, db_session):
        _seed_customer(db_session, 1)
        headers = _non_admin_headers(db_session, customer_id=1)
        tech_id = _seed_tech(db_session, 1)
        uc_id = _seed_use_case(db_session, 1)

        r = client.post(
            "/api/customers/1/sales-notes/",
            json={**_note_payload(), "related_technology_ids": [tech_id], "related_use_case_ids": [uc_id]},
            headers=headers,
        )
        assert r.status_code == 201
        note_id = r.json()["id"]
        assert r.json()["customer_id"] == 1
        assert r.json()["verification_state"] == "verified"
        assert r.json()["related_technology_ids"] == [tech_id]
        assert r.json()["related_use_case_ids"] == [uc_id]

        r = client.get("/api/customers/1/sales-notes/", headers=headers)
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["title"] == "Discovery call notes"

        r = client.get(f"/api/sales-notes/{note_id}/", headers=headers)
        assert r.status_code == 200
        assert r.json()["author"] == "J. Rivera (S-A-I-L)"

        r = client.put(
            f"/api/sales-notes/{note_id}/",
            json={"title": "Updated title", "verification_state": "inferred"},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["title"] == "Updated title"
        assert r.json()["verification_state"] == "inferred"
        assert r.json()["author"] == "J. Rivera (S-A-I-L)"  # untouched
        # Related sets survive an update that omits them.
        assert r.json()["related_technology_ids"] == [tech_id]

        r = client.delete(f"/api/sales-notes/{note_id}/", headers=headers)
        assert r.status_code == 204
        assert client.get("/api/customers/1/sales-notes/", headers=headers).json() == []

    def test_member_cannot_access_other_customers_note(self, client, db_session):
        """Cross-customer isolation: member of customer 2 gets 404 (not 403)
        on a customer-1 note — no existence leakage."""
        _seed_customer(db_session, 1)
        _seed_customer(db_session, 2)
        admin = _admin_headers(db_session)

        r = client.post(
            "/api/customers/1/sales-notes/",
            json=_note_payload(title="Secret note"),
            headers=admin,
        )
        assert r.status_code == 201
        note_id = r.json()["id"]

        member2 = _non_admin_headers(db_session, customer_id=2)
        assert client.get(f"/api/sales-notes/{note_id}/", headers=member2).status_code == 404
        assert (
            client.put(f"/api/sales-notes/{note_id}/", json={"title": "Hacked"}, headers=member2).status_code
            == 404
        )
        assert client.delete(f"/api/sales-notes/{note_id}/", headers=member2).status_code == 404
        # Note still intact for the admin.
        assert client.get(f"/api/sales-notes/{note_id}/", headers=admin).status_code == 200

    def test_invalid_category_gets_422_via_route(self, client, db_session):
        _seed_customer(db_session, 1)
        admin = _admin_headers(db_session)
        r = client.post(
            "/api/customers/1/sales-notes/",
            json=_note_payload(category="quantum_flux"),
            headers=admin,
        )
        assert r.status_code == 422

    def test_cross_customer_junction_gets_422_via_route(self, client, db_session):
        _seed_customer(db_session, 1)
        _seed_customer(db_session, 2)
        admin = _admin_headers(db_session)
        other_tech = _seed_tech(db_session, 2)
        r = client.post(
            "/api/customers/1/sales-notes/",
            json={**_note_payload(), "related_technology_ids": [other_tech]},
            headers=admin,
        )
        assert r.status_code == 422

    def test_missing_note_gets_404(self, client, db_session):
        admin = _admin_headers(db_session)
        assert client.get("/api/sales-notes/9999/", headers=admin).status_code == 404
        assert (
            client.put("/api/sales-notes/9999/", json={"title": "X"}, headers=admin).status_code
            == 404
        )
        assert client.delete("/api/sales-notes/9999/", headers=admin).status_code == 404

    def test_list_filters_via_route(self, client, db_session):
        _seed_customer(db_session, 1)
        admin = _admin_headers(db_session)
        client.post("/api/customers/1/sales-notes/", json=_note_payload(note_date="2026-08-01", title="Old", category="meeting"), headers=admin)
        client.post("/api/customers/1/sales-notes/", json=_note_payload(note_date="2026-08-20", title="New risk", category="risk", content="Security gap flagged"), headers=admin)
        client.post("/api/customers/1/sales-notes/", json=_note_payload(note_date="2026-08-10", title="Mid", category="meeting"), headers=admin)

        assert len(client.get("/api/customers/1/sales-notes/", headers=admin).json()) == 3
        r = client.get("/api/customers/1/sales-notes/?category=risk", headers=admin)
        assert len(r.json()) == 1 and r.json()[0]["title"] == "New risk"
        r = client.get("/api/customers/1/sales-notes/?search=security+gap", headers=admin)
        assert len(r.json()) == 1 and r.json()[0]["category"] == "risk"
        r = client.get("/api/customers/1/sales-notes/?sort=note_date&direction=asc", headers=admin)
        titles = [n["title"] for n in r.json()]
        assert titles == ["Old", "Mid", "New risk"]
        r = client.get("/api/customers/1/sales-notes/?author=j.+rivera", headers=admin)
        assert len(r.json()) == 3

    def test_empty_put_gets_400(self, client, db_session):
        _seed_customer(db_session, 1)
        admin = _admin_headers(db_session)
        note_id = client.post(
            "/api/customers/1/sales-notes/", json=_note_payload(), headers=admin
        ).json()["id"]
        assert client.put(f"/api/sales-notes/{note_id}/", json={}, headers=admin).status_code == 400


class TestSalesNoteAdminBypass:
    """Admins bypass the CustomerUser junction (own all customers)."""

    def test_admin_without_junction_can_create_and_read(self, client, db_session):
        _seed_customer(db_session, 1)
        # The seeded admin has NO CustomerUser junction rows — the bypass
        # must still allow full access.
        headers = _admin_headers(db_session)
        r = client.post(
            "/api/customers/1/sales-notes/",
            json=_note_payload(),
            headers=headers,
        )
        assert r.status_code == 201
        note_id = r.json()["id"]
        assert client.get(f"/api/sales-notes/{note_id}/", headers=headers).status_code == 200
        assert client.delete(f"/api/sales-notes/{note_id}/", headers=headers).status_code == 204
