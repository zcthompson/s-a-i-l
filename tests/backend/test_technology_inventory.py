"""Technology Inventory (S-A-I-L) tests — service CRUD, validation, route auth.

Route tests follow the repo's TestClient auth pattern (test_customer_knowledge.py):
a real JWT via create_access_token. Access is gated by the CustomerUser
junction WITH admin bypass (admins own all customers — the customers.py /
sales_section.py / customer_knowledge.py / sales_evaluations.py convention):
non-admin tests use a member user + junction row; admin-bypass tests use the
junction-less seeded admin.
"""

import pytest

from tests.backend.common import _admin_headers


def _non_admin_headers(db_session, customer_id: int = 1) -> dict:
    """Authorization header for a non-admin user with a CustomerUser row.

    Seeds a non-admin User + Customer row + member junction row and returns
    a real JWT header — the junction row is this user's ONLY access to the
    customer (no admin bypass), making it the right caller for 403 tests.
    """
    from backend.auth import create_access_token
    from backend.models.use_case import Customer, CustomerUser, User

    username = f"tech_member_{customer_id}"
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
        db_session.add(Customer(id=customer_id, name=f"Tech Test Customer {customer_id}"))
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
        db_session.add(Customer(id=customer_id, name=f"Tech Test Customer {customer_id}"))
        db_session.commit()


class TestTechnologyInventoryService:
    @pytest.fixture(autouse=True)
    def _existing_customer_parents(self, db_session):
        from backend.models.use_case import Customer
        db_session.add_all([Customer(id=1, name="Synthetic parent 1"), Customer(id=2, name="Synthetic parent 2")])
        db_session.commit()

    """Service-level CRUD and validation for technology inventory."""

    def test_create_and_list_technology(self, db_session):
        from backend.services.technology_inventory_service import (
            create_technology,
            list_technology,
        )

        item = create_technology(
            db_session,
            1,
            {
                "name": "VMware vSphere",
                "vendor": "VMware",
                "category": "virtualization",
                "version_edition": "7.0 U3",
                "deployment_model": "on_premise",
                "lifecycle_state": "current",
                "support_state": "under_support",
                "business_criticality": "critical",
                "verification_state": "verified",
            },
        )
        assert item.id is not None
        assert item.customer_id == 1
        assert item.category == "virtualization"
        assert item.verification_state == "verified"

        items = list_technology(db_session, customer_id=1)
        assert len(items) == 1
        assert items[0].id == item.id

    def test_unknown_attributes_stay_null(self, db_session):
        """Creating with only name+category leaves every other attribute
        NULL — unknowns stay unknown, never fabricated."""
        from backend.services.technology_inventory_service import create_technology

        item = create_technology(db_session, 1, {"name": "Mystery Appliance", "category": "hardware"})
        assert item.vendor is None
        assert item.version_edition is None
        assert item.deployment_model is None
        assert item.quantity is None
        assert item.lifecycle_state is None
        assert item.support_state is None
        assert item.business_criticality is None
        assert item.source is None
        assert item.date_observed is None
        assert item.confidence is None
        assert item.notes is None
        assert item.verification_state == "unverified"  # default

    def test_update_technology(self, db_session):
        from backend.services.technology_inventory_service import (
            create_technology,
            update_technology,
        )

        item = create_technology(db_session, 1, {"name": "ESXi", "category": "virtualization"})
        updated = update_technology(
            db_session, item.id, {"version_edition": "8.0 U2", "verification_state": "inferred", "confidence": 0.8}
        )
        assert updated.version_edition == "8.0 U2"
        assert updated.verification_state == "inferred"
        assert updated.confidence == 0.8
        assert updated.name == "ESXi"  # untouched fields preserved

    def test_update_missing_item_returns_none(self, db_session):
        from backend.services.technology_inventory_service import update_technology

        assert update_technology(db_session, 9999, {"name": "Nope"}) is None

    def test_delete_technology(self, db_session):
        from backend.services.technology_inventory_service import (
            create_technology,
            delete_technology,
            list_technology,
        )

        item = create_technology(db_session, 1, {"name": "Old Switch", "category": "networking"})
        assert delete_technology(db_session, item.id) is True
        assert list_technology(db_session, customer_id=1) == []
        assert delete_technology(db_session, item.id) is False  # already gone

    def test_invalid_category_rejected(self, db_session):
        from backend.services.technology_inventory_service import create_technology
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            create_technology(db_session, 1, {"name": "X", "category": "quantum_flux"})
        assert exc.value.status_code == 422
        assert "category" in str(exc.value.detail)

    def test_invalid_verification_state_rejected(self, db_session):
        from backend.services.technology_inventory_service import create_technology
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            create_technology(
                db_session, 1, {"name": "X", "category": "software", "verification_state": "guessed"}
            )

    def test_invalid_confidence_rejected(self, db_session):
        from backend.services.technology_inventory_service import create_technology
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            create_technology(
                db_session, 1, {"name": "X", "category": "software", "confidence": 1.5}
            )

    def test_invalid_quantity_rejected(self, db_session):
        from backend.services.technology_inventory_service import create_technology
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            create_technology(
                db_session, 1, {"name": "X", "category": "software", "quantity": 0}
            )

    def test_list_filters(self, db_session):
        from backend.services.technology_inventory_service import (
            create_technology,
            list_technology,
        )

        create_technology(db_session, 1, {"name": "VMware vSphere", "vendor": "VMware", "category": "virtualization", "verification_state": "verified"})
        create_technology(db_session, 1, {"name": "AWS EC2", "vendor": "Amazon", "category": "cloud_platform", "verification_state": "inferred"})
        create_technology(db_session, 1, {"name": "Cisco UCS", "vendor": "Cisco", "category": "hardware", "verification_state": "verified"})

        assert len(list_technology(db_session, 1)) == 3
        assert len(list_technology(db_session, 1, category="cloud_platform")) == 1
        assert list_technology(db_session, 1, vendor="Cisco")[0].name == "Cisco UCS"
        assert len(list_technology(db_session, 1, verification_state="verified")) == 2
        assert [i.name for i in list_technology(db_session, 1, search="vmware")] == ["VMware vSphere"]
        # Other customer's inventory never leaks into this customer's list.
        create_technology(db_session, 2, {"name": "Other Co Stack", "category": "other"})
        assert len(list_technology(db_session, 1)) == 3


class TestTechnologyInventoryRoutes:
    """Route-level authorization and CRUD for technology inventory."""

    def test_unauthenticated_gets_401(self, client, db_session):
        _seed_customer(db_session, 1)
        assert client.get("/api/customers/1/technology/").status_code == 401
        assert (
            client.post(
                "/api/customers/1/technology/", json={"name": "X", "category": "software"}
            ).status_code
            == 401
        )
        assert client.get("/api/technology/1/").status_code == 401
        assert client.put("/api/technology/1/", json={"name": "X"}).status_code == 401
        assert client.delete("/api/technology/1/").status_code == 401

    def test_missing_customer_gets_404(self, client, db_session):
        assert client.get("/api/customers/9999/technology/", headers=_admin_headers(db_session)).status_code == 404
        assert (
            client.post(
                "/api/customers/9999/technology/",
                json={"name": "X", "category": "software"},
                headers=_admin_headers(db_session),
            ).status_code
            == 404
        )

    def test_user_without_customer_access_gets_404(self, client, db_session):
        """A member of customer 2 cannot touch customer 1's inventory — and
        gets the same 404 as a missing customer (404-first, R4/Q7)."""
        _seed_customer(db_session, 1)
        _seed_customer(db_session, 2)
        headers = _non_admin_headers(db_session, customer_id=2)
        assert client.get("/api/customers/1/technology/", headers=headers).status_code == 404
        assert (
            client.post(
                "/api/customers/1/technology/",
                json={"name": "X", "category": "software"},
                headers=headers,
            ).status_code
            == 404
        )

    def test_member_can_create_list_get_update_delete(self, client, db_session):
        _seed_customer(db_session, 1)
        headers = _non_admin_headers(db_session, customer_id=1)

        r = client.post(
            "/api/customers/1/technology/",
            json={
                "name": "VMware vSphere",
                "vendor": "VMware",
                "category": "virtualization",
                "version_edition": "7.0 U3",
                "deployment_model": "on_premise",
                "lifecycle_state": "current",
                "support_state": "under_support",
                "business_criticality": "critical",
                "verification_state": "verified",
            },
            headers=headers,
        )
        assert r.status_code == 201
        item_id = r.json()["id"]
        assert r.json()["customer_id"] == 1
        assert r.json()["verification_state"] == "verified"

        r = client.get("/api/customers/1/technology/", headers=headers)
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["name"] == "VMware vSphere"

        r = client.get(f"/api/technology/{item_id}/", headers=headers)
        assert r.status_code == 200
        assert r.json()["vendor"] == "VMware"

        r = client.put(
            f"/api/technology/{item_id}/",
            json={"lifecycle_state": "eol_announced", "confidence": 0.9},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["lifecycle_state"] == "eol_announced"
        assert r.json()["confidence"] == 0.9
        assert r.json()["name"] == "VMware vSphere"  # untouched

        r = client.delete(f"/api/technology/{item_id}/", headers=headers)
        assert r.status_code == 204
        assert client.get("/api/customers/1/technology/", headers=headers).json() == []

    def test_member_cannot_access_other_customers_item(self, client, db_session):
        """Cross-customer isolation: member of customer 2 gets 404 (not 403)
        on a customer-1 item — no existence leakage."""
        _seed_customer(db_session, 1)
        _seed_customer(db_session, 2)
        admin = _admin_headers(db_session)

        r = client.post(
            "/api/customers/1/technology/",
            json={"name": "Secret Stack", "category": "software"},
            headers=admin,
        )
        assert r.status_code == 201
        item_id = r.json()["id"]

        member2 = _non_admin_headers(db_session, customer_id=2)
        assert client.get(f"/api/technology/{item_id}/", headers=member2).status_code == 404
        assert (
            client.put(f"/api/technology/{item_id}/", json={"name": "Hacked"}, headers=member2).status_code
            == 404
        )
        assert client.delete(f"/api/technology/{item_id}/", headers=member2).status_code == 404
        # Item still intact for the admin.
        assert client.get(f"/api/technology/{item_id}/", headers=admin).status_code == 200

    def test_invalid_enum_gets_422_via_route(self, client, db_session):
        _seed_customer(db_session, 1)
        admin = _admin_headers(db_session)
        r = client.post(
            "/api/customers/1/technology/",
            json={"name": "X", "category": "quantum_flux"},
            headers=admin,
        )
        assert r.status_code == 422

    def test_invalid_confidence_gets_422_via_route(self, client, db_session):
        _seed_customer(db_session, 1)
        admin = _admin_headers(db_session)
        r = client.post(
            "/api/customers/1/technology/",
            json={"name": "X", "category": "software", "confidence": 42},
            headers=admin,
        )
        assert r.status_code == 422

    def test_missing_item_gets_404(self, client, db_session):
        admin = _admin_headers(db_session)
        assert client.get("/api/technology/9999/", headers=admin).status_code == 404
        assert (
            client.put("/api/technology/9999/", json={"name": "X"}, headers=admin).status_code
            == 404
        )
        assert client.delete("/api/technology/9999/", headers=admin).status_code == 404

    def test_list_filters_via_route(self, client, db_session):
        _seed_customer(db_session, 1)
        admin = _admin_headers(db_session)
        client.post("/api/customers/1/technology/", json={"name": "VMware vSphere", "vendor": "VMware", "category": "virtualization", "verification_state": "verified"}, headers=admin)
        client.post("/api/customers/1/technology/", json={"name": "AWS EC2", "vendor": "Amazon", "category": "cloud_platform", "verification_state": "inferred"}, headers=admin)
        client.post("/api/customers/1/technology/", json={"name": "Cisco UCS", "vendor": "Cisco", "category": "hardware", "verification_state": "verified"}, headers=admin)

        assert len(client.get("/api/customers/1/technology/", headers=admin).json()) == 3
        r = client.get("/api/customers/1/technology/?category=cloud_platform", headers=admin)
        assert len(r.json()) == 1 and r.json()[0]["name"] == "AWS EC2"
        r = client.get("/api/customers/1/technology/?search=cisco", headers=admin)
        assert len(r.json()) == 1 and r.json()[0]["vendor"] == "Cisco"
        r = client.get("/api/customers/1/technology/?verification_state=verified", headers=admin)
        assert len(r.json()) == 2
        r = client.get("/api/customers/1/technology/?sort=category", headers=admin)
        cats = [i["category"] for i in r.json()]
        assert cats == sorted(cats)

    def test_empty_put_gets_400(self, client, db_session):
        _seed_customer(db_session, 1)
        admin = _admin_headers(db_session)
        item_id = client.post(
            "/api/customers/1/technology/", json={"name": "X", "category": "software"}, headers=admin
        ).json()["id"]
        assert client.put(f"/api/technology/{item_id}/", json={}, headers=admin).status_code == 400


class TestTechnologyInventoryAdminBypass:
    """Admins bypass the CustomerUser junction (own all customers)."""

    def test_admin_without_junction_can_create_and_read(self, client, db_session):
        _seed_customer(db_session, 1)
        # The seeded admin has NO CustomerUser junction rows — the bypass
        # must still allow full access.
        headers = _admin_headers(db_session)
        r = client.post(
            "/api/customers/1/technology/",
            json={"name": "Admin Added", "category": "management_tool"},
            headers=headers,
        )
        assert r.status_code == 201
        item_id = r.json()["id"]
        assert client.get(f"/api/technology/{item_id}/", headers=headers).status_code == 200
        assert client.delete(f"/api/technology/{item_id}/", headers=headers).status_code == 204
