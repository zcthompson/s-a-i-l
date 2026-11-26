"""Technology dependency (S-A-I-L) tests — service CRUD, canonical orientation,
cross-customer isolation, route auth.

Route tests follow the repo's TestClient auth pattern (test_customer_knowledge.py /
test_technology_inventory.py): a real JWT via create_access_token. Access is gated by the
CustomerUser junction WITH admin bypass. Service tests verify:
- controlled-vocabulary validation (relationship_type, verification_state, confidence);
- same-customer endpoint enforcement (cross-customer 422);
- no self-dependency (422);
- canonical orientation: the exact duplicate 409s and the mirrored direction of the same
  logical relationship 409s — a relationship is never stored twice.
"""

import pytest

from tests.backend.common import _admin_headers


def _non_admin_headers(db_session, customer_id: int = 1) -> dict:
    """Authorization header for a non-admin user with a CustomerUser row."""
    from backend.auth import create_access_token
    from backend.models.use_case import Customer, CustomerUser, User

    username = f"dep_member_{customer_id}"
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
        db_session.add(Customer(id=customer_id, name=f"Dep Test Customer {customer_id}"))
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
        db_session.add(Customer(id=customer_id, name=f"Dep Test Customer {customer_id}"))
        db_session.commit()


def _seed_tech(db_session, customer_id: int, name: str = "Tech", **fields) -> int:
    """Create a technology inventory item and return its id."""
    from backend.services.technology_inventory_service import create_technology

    item = create_technology(
        db_session, customer_id, {"name": name, "category": fields.pop("category", "software"), **fields}
    )
    return item.id


class TestTechnologyDependencyService:
    @pytest.fixture(autouse=True)
    def _existing_customer_parents(self, db_session):
        from backend.models.use_case import Customer
        db_session.add_all([Customer(id=1, name="Synthetic parent 1"), Customer(id=2, name="Synthetic parent 2")])
        db_session.commit()

    """Service-level CRUD and validation for technology dependencies."""

    def test_create_and_list_dependency(self, db_session):
        from backend.services.technology_dependency_service import (
            create_dependency,
            list_dependencies,
        )

        src = _seed_tech(db_session, 1, name="VMware vSphere 6.5", category="virtualization")
        tgt = _seed_tech(db_session, 1, name="Dell PowerEdge R720", category="hardware")
        dep = create_dependency(
            db_session,
            1,
            {
                "source_id": src,
                "target_id": tgt,
                "relationship_type": "runs_on",
                "verification_state": "verified",
                "source_provenance": "discovery call",
                "notes": "vSphere runs on the R720 fleet",
            },
        )
        assert dep.id is not None
        assert dep.customer_id == 1
        assert dep.source_id == src
        assert dep.target_id == tgt
        assert dep.relationship_type == "runs_on"

        deps = list_dependencies(db_session, customer_id=1)
        assert len(deps) == 1
        assert deps[0].id == dep.id
        # Denormalized endpoints in to_dict (no second round-trip).
        d = dep.to_dict()
        assert d["source_name"] == "VMware vSphere 6.5"
        assert d["target_name"] == "Dell PowerEdge R720"

    def test_unknown_attributes_stay_null(self, db_session):
        src = _seed_tech(db_session, 1, name="A")
        tgt = _seed_tech(db_session, 1, name="B")
        from backend.services.technology_dependency_service import create_dependency

        dep = create_dependency(db_session, 1, {"source_id": src, "target_id": tgt, "relationship_type": "depends_on"})
        assert dep.verification_state == "verified"  # default
        assert dep.confidence is None
        assert dep.source_provenance is None
        assert dep.date_observed is None
        assert dep.notes is None

    def test_update_dependency(self, db_session):
        src = _seed_tech(db_session, 1, name="A")
        tgt = _seed_tech(db_session, 1, name="B")
        from backend.services.technology_dependency_service import (
            create_dependency,
            update_dependency,
        )

        dep = create_dependency(db_session, 1, {"source_id": src, "target_id": tgt, "relationship_type": "depends_on"})
        updated = update_dependency(db_session, dep.id, {"verification_state": "inferred", "confidence": 0.7, "notes": "inferred from architecture"})
        assert updated.verification_state == "inferred"
        assert updated.confidence == 0.7
        assert updated.notes == "inferred from architecture"
        assert updated.relationship_type == "depends_on"  # untouched

    def test_update_missing_returns_none(self, db_session):
        from backend.services.technology_dependency_service import update_dependency

        assert update_dependency(db_session, 9999, {"notes": "x"}) is None

    def test_delete_dependency(self, db_session):
        src = _seed_tech(db_session, 1, name="A")
        tgt = _seed_tech(db_session, 1, name="B")
        from backend.services.technology_dependency_service import (
            create_dependency,
            delete_dependency,
            list_dependencies,
        )

        dep = create_dependency(db_session, 1, {"source_id": src, "target_id": tgt, "relationship_type": "depends_on"})
        assert delete_dependency(db_session, dep.id) is True
        assert list_dependencies(db_session, customer_id=1) == []
        assert delete_dependency(db_session, dep.id) is False

    def test_invalid_relationship_type_rejected(self, db_session):
        src = _seed_tech(db_session, 1, name="A")
        tgt = _seed_tech(db_session, 1, name="B")
        from backend.services.technology_dependency_service import create_dependency
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            create_dependency(db_session, 1, {"source_id": src, "target_id": tgt, "relationship_type": "vibes"})
        assert exc.value.status_code == 422
        assert "relationship_type" in str(exc.value.detail)

    def test_invalid_verification_state_rejected(self, db_session):
        src = _seed_tech(db_session, 1, name="A")
        tgt = _seed_tech(db_session, 1, name="B")
        from backend.services.technology_dependency_service import create_dependency
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            create_dependency(db_session, 1, {"source_id": src, "target_id": tgt, "relationship_type": "depends_on", "verification_state": "guessed"})

    def test_invalid_confidence_rejected(self, db_session):
        src = _seed_tech(db_session, 1, name="A")
        tgt = _seed_tech(db_session, 1, name="B")
        from backend.services.technology_dependency_service import create_dependency
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            create_dependency(db_session, 1, {"source_id": src, "target_id": tgt, "relationship_type": "depends_on", "confidence": 1.5})

    def test_self_dependency_rejected(self, db_session):
        src = _seed_tech(db_session, 1, name="A")
        from backend.services.technology_dependency_service import create_dependency
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            create_dependency(db_session, 1, {"source_id": src, "target_id": src, "relationship_type": "depends_on"})
        assert exc.value.status_code == 422
        assert "differ" in str(exc.value.detail)

    def test_cross_customer_endpoint_rejected(self, db_session):
        """An endpoint from another customer's inventory is rejected 422 —
        never silently adopted (customer isolation)."""
        src = _seed_tech(db_session, 1, name="A")
        other = _seed_tech(db_session, 2, name="Other Co Tech")
        from backend.services.technology_dependency_service import create_dependency
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            create_dependency(db_session, 1, {"source_id": src, "target_id": other, "relationship_type": "depends_on"})
        assert exc.value.status_code == 422
        assert "target_id" in str(exc.value.detail)
        # And the reverse (source from another customer).
        with pytest.raises(HTTPException):
            create_dependency(db_session, 1, {"source_id": other, "target_id": src, "relationship_type": "depends_on"})

    def test_exact_duplicate_rejected(self, db_session):
        """Same (source, target, type) twice -> 409 (canonical orientation;
        the UNIQUE constraint is the final guard)."""
        src = _seed_tech(db_session, 1, name="A")
        tgt = _seed_tech(db_session, 1, name="B")
        from backend.services.technology_dependency_service import create_dependency
        from fastapi import HTTPException

        create_dependency(db_session, 1, {"source_id": src, "target_id": tgt, "relationship_type": "depends_on"})
        with pytest.raises(HTTPException) as exc:
            create_dependency(db_session, 1, {"source_id": src, "target_id": tgt, "relationship_type": "depends_on"})
        assert exc.value.status_code == 409

    def test_mirrored_relationship_rejected(self, db_session):
        """The mirrored direction of the same logical relationship 409s —
        a relationship is never stored twice from either entity's
        perspective (the graph projection must not emit duplicate edges)."""
        src = _seed_tech(db_session, 1, name="vSphere")
        tgt = _seed_tech(db_session, 1, name="R720")
        from backend.services.technology_dependency_service import create_dependency
        from fastapi import HTTPException

        create_dependency(db_session, 1, {"source_id": src, "target_id": tgt, "relationship_type": "runs_on"})
        # Mirror: R720 hosts vSphere — the same logical relationship.
        with pytest.raises(HTTPException) as exc:
            create_dependency(db_session, 1, {"source_id": tgt, "target_id": src, "relationship_type": "hosts"})
        assert exc.value.status_code == 409
        # But a DIFFERENT relationship type between the same pair is allowed
        # (e.g. vSphere also consumes storage from R720 is a distinct fact).
        dep2 = create_dependency(db_session, 1, {"source_id": src, "target_id": tgt, "relationship_type": "consumes_storage"})
        assert dep2.id is not None

    def test_associated_with_mirror_rejected(self, db_session):
        """associated_with is symmetric — its mirror is always the duplicate."""
        src = _seed_tech(db_session, 1, name="A")
        tgt = _seed_tech(db_session, 1, name="B")
        from backend.services.technology_dependency_service import create_dependency
        from fastapi import HTTPException

        create_dependency(db_session, 1, {"source_id": src, "target_id": tgt, "relationship_type": "associated_with"})
        with pytest.raises(HTTPException):
            create_dependency(db_session, 1, {"source_id": tgt, "target_id": src, "relationship_type": "associated_with"})

    def test_list_filters(self, db_session):
        from backend.services.technology_dependency_service import (
            create_dependency,
            list_dependencies,
        )

        vSphere = _seed_tech(db_session, 1, name="VMware vSphere", vendor="VMware", category="virtualization")
        r720 = _seed_tech(db_session, 1, name="Dell R720", vendor="Dell", category="hardware")
        ontap = _seed_tech(db_session, 1, name="NetApp ONTAP", vendor="NetApp", category="storage")
        create_dependency(db_session, 1, {"source_id": vSphere, "target_id": r720, "relationship_type": "runs_on"})
        create_dependency(db_session, 1, {"source_id": vSphere, "target_id": ontap, "relationship_type": "consumes_storage", "verification_state": "inferred", "confidence": 0.8})

        assert len(list_dependencies(db_session, 1)) == 2
        assert len(list_dependencies(db_session, 1, relationship_type="runs_on")) == 1
        assert len(list_dependencies(db_session, 1, verification_state="inferred")) == 1
        # Search matches source or target name/vendor.
        assert len(list_dependencies(db_session, 1, search="netapp")) == 1
        assert len(list_dependencies(db_session, 1, search="vmware")) == 2
        # Other customer's dependencies never leak.
        other_a = _seed_tech(db_session, 2, name="Other A")
        other_b = _seed_tech(db_session, 2, name="Other B")
        create_dependency(db_session, 2, {"source_id": other_a, "target_id": other_b, "relationship_type": "depends_on"})
        assert len(list_dependencies(db_session, 1)) == 2


class TestTechnologyDependencyRoutes:
    """Route-level authorization and CRUD for technology dependencies."""

    def test_unauthenticated_gets_401(self, client, db_session):
        _seed_customer(db_session, 1)
        assert client.get("/api/customers/1/technology-dependencies/").status_code == 401
        assert (
            client.post(
                "/api/customers/1/technology-dependencies/",
                json={"source_id": 1, "target_id": 2, "relationship_type": "depends_on"},
            ).status_code
            == 401
        )
        assert client.get("/api/technology-dependencies/1/").status_code == 401
        assert client.put("/api/technology-dependencies/1/", json={"notes": "x"}).status_code == 401
        assert client.delete("/api/technology-dependencies/1/").status_code == 401

    def test_missing_customer_gets_404(self, client, db_session):
        assert (
            client.get(
                "/api/customers/9999/technology-dependencies/", headers=_admin_headers(db_session)
            ).status_code
            == 404
        )

    def test_user_without_customer_access_gets_404(self, client, db_session):
        # 404-first (R4/Q7): out-of-scope is the same 404 as a missing customer.
        _seed_customer(db_session, 1)
        _seed_customer(db_session, 2)
        headers = _non_admin_headers(db_session, customer_id=2)
        assert client.get("/api/customers/1/technology-dependencies/", headers=headers).status_code == 404
        assert (
            client.post(
                "/api/customers/1/technology-dependencies/",
                json={"source_id": 1, "target_id": 2, "relationship_type": "depends_on"},
                headers=headers,
            ).status_code
            == 404
        )

    def test_member_can_create_list_get_update_delete(self, client, db_session):
        _seed_customer(db_session, 1)
        headers = _non_admin_headers(db_session, customer_id=1)
        src = _seed_tech(db_session, 1, name="VMware vSphere", category="virtualization")
        tgt = _seed_tech(db_session, 1, name="Dell R720", category="hardware")

        r = client.post(
            "/api/customers/1/technology-dependencies/",
            json={
                "source_id": src,
                "target_id": tgt,
                "relationship_type": "runs_on",
                "verification_state": "verified",
                "source_provenance": "discovery call",
            },
            headers=headers,
        )
        assert r.status_code == 201
        dep_id = r.json()["id"]
        assert r.json()["customer_id"] == 1
        assert r.json()["source_name"] == "VMware vSphere"
        assert r.json()["target_name"] == "Dell R720"

        r = client.get("/api/customers/1/technology-dependencies/", headers=headers)
        assert r.status_code == 200
        assert len(r.json()) == 1

        r = client.get(f"/api/technology-dependencies/{dep_id}/", headers=headers)
        assert r.status_code == 200
        assert r.json()["relationship_type"] == "runs_on"

        r = client.put(
            f"/api/technology-dependencies/{dep_id}/",
            json={"verification_state": "inferred", "confidence": 0.9, "notes": "refined"},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["verification_state"] == "inferred"
        assert r.json()["confidence"] == 0.9
        assert r.json()["relationship_type"] == "runs_on"  # untouched

        r = client.delete(f"/api/technology-dependencies/{dep_id}/", headers=headers)
        assert r.status_code == 204
        assert client.get("/api/customers/1/technology-dependencies/", headers=headers).json() == []

    def test_member_cannot_access_other_customers_dependency(self, client, db_session):
        """Cross-customer isolation: member of customer 2 gets 404 (not 403)
        on a customer-1 dependency — no existence leakage."""
        _seed_customer(db_session, 1)
        _seed_customer(db_session, 2)
        admin = _admin_headers(db_session)
        src = _seed_tech(db_session, 1, name="A")
        tgt = _seed_tech(db_session, 1, name="B")
        dep_id = client.post(
            "/api/customers/1/technology-dependencies/",
            json={"source_id": src, "target_id": tgt, "relationship_type": "depends_on"},
            headers=admin,
        ).json()["id"]

        member2 = _non_admin_headers(db_session, customer_id=2)
        assert client.get(f"/api/technology-dependencies/{dep_id}/", headers=member2).status_code == 404
        assert (
            client.put(f"/api/technology-dependencies/{dep_id}/", json={"notes": "hacked"}, headers=member2).status_code
            == 404
        )
        assert client.delete(f"/api/technology-dependencies/{dep_id}/", headers=member2).status_code == 404
        # Still intact for the admin.
        assert client.get(f"/api/technology-dependencies/{dep_id}/", headers=admin).status_code == 200

    def test_cross_customer_endpoint_gets_422_via_route(self, client, db_session):
        _seed_customer(db_session, 1)
        _seed_customer(db_session, 2)
        admin = _admin_headers(db_session)
        src = _seed_tech(db_session, 1, name="A")
        other = _seed_tech(db_session, 2, name="Other Co Tech")
        r = client.post(
            "/api/customers/1/technology-dependencies/",
            json={"source_id": src, "target_id": other, "relationship_type": "depends_on"},
            headers=admin,
        )
        assert r.status_code == 422

    def test_invalid_relationship_type_gets_422_via_route(self, client, db_session):
        _seed_customer(db_session, 1)
        admin = _admin_headers(db_session)
        src = _seed_tech(db_session, 1, name="A")
        tgt = _seed_tech(db_session, 1, name="B")
        r = client.post(
            "/api/customers/1/technology-dependencies/",
            json={"source_id": src, "target_id": tgt, "relationship_type": "vibes"},
            headers=admin,
        )
        assert r.status_code == 422

    def test_mirrored_relationship_gets_409_via_route(self, client, db_session):
        _seed_customer(db_session, 1)
        admin = _admin_headers(db_session)
        src = _seed_tech(db_session, 1, name="vSphere")
        tgt = _seed_tech(db_session, 1, name="R720")
        assert (
            client.post(
                "/api/customers/1/technology-dependencies/",
                json={"source_id": src, "target_id": tgt, "relationship_type": "runs_on"},
                headers=admin,
            ).status_code
            == 201
        )
        # Mirror direction of the same logical relationship -> 409.
        r = client.post(
            "/api/customers/1/technology-dependencies/",
            json={"source_id": tgt, "target_id": src, "relationship_type": "hosts"},
            headers=admin,
        )
        assert r.status_code == 409

    def test_missing_dependency_gets_404(self, client, db_session):
        admin = _admin_headers(db_session)
        assert client.get("/api/technology-dependencies/9999/", headers=admin).status_code == 404
        assert client.put("/api/technology-dependencies/9999/", json={"notes": "x"}, headers=admin).status_code == 404
        assert client.delete("/api/technology-dependencies/9999/", headers=admin).status_code == 404

    def test_empty_put_gets_400(self, client, db_session):
        _seed_customer(db_session, 1)
        admin = _admin_headers(db_session)
        src = _seed_tech(db_session, 1, name="A")
        tgt = _seed_tech(db_session, 1, name="B")
        dep_id = client.post(
            "/api/customers/1/technology-dependencies/",
            json={"source_id": src, "target_id": tgt, "relationship_type": "depends_on"},
            headers=admin,
        ).json()["id"]
        assert client.put(f"/api/technology-dependencies/{dep_id}/", json={}, headers=admin).status_code == 400


class TestTechnologyDependencyAdminBypass:
    """Admins bypass the CustomerUser junction (own all customers)."""

    def test_admin_without_junction_can_create_and_read(self, client, db_session):
        _seed_customer(db_session, 1)
        headers = _admin_headers(db_session)
        src = _seed_tech(db_session, 1, name="A")
        tgt = _seed_tech(db_session, 1, name="B")
        r = client.post(
            "/api/customers/1/technology-dependencies/",
            json={"source_id": src, "target_id": tgt, "relationship_type": "depends_on"},
            headers=headers,
        )
        assert r.status_code == 201
        dep_id = r.json()["id"]
        assert client.get(f"/api/technology-dependencies/{dep_id}/", headers=headers).status_code == 200
        assert client.delete(f"/api/technology-dependencies/{dep_id}/", headers=headers).status_code == 204
