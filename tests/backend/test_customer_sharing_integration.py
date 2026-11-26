
"""Integration tests for customer sharing workflow.

Tests the full lifecycle of multi-user multi-customer access:
1. Create customers via API
2. Register two users
3. Add user to customer with role (owner/member/auditor)
4. Verify junction table entries
5. Test access control: owner, member, auditor restrictions
6. Test remove user from customer
7. Test update role within customer
8. Test get-my-customers endpoint
9. Test access denied scenarios

Run: pytest tests/backend/test_customer_sharing_integration.py -v
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

from unittest.mock import patch

import pytest
from backend.dependencies import get_db
from sqlalchemy.orm import sessionmaker

from tests.backend._shared import engine

_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"


def _fake_hash_password(password: str) -> str:
    return _FAKE_BCRYPT_HASH


with patch("backend.auth.hash_password", side_effect=_fake_hash_password):
    from backend.main import app
    from backend.models.use_case import Customer, CustomerUser, User
    from fastapi.testclient import TestClient

    @pytest.fixture()
    def client():
        def override_get_db():
            session = sessionmaker(bind=engine)()
            try:
                yield session
            finally:
                session.rollback()
                session.close()
        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.clear()

    @pytest.fixture()
    def db_session():
        """Reset the selected integration backend; no secondary SQLite fallback."""
        from tests.backend.database_support import reset_tables

        session = sessionmaker(bind=engine, autoflush=False)()
        try:
            reset_tables(session)
            yield session
        finally:
            session.rollback()
            session.close()

    @pytest.fixture()
    def mock_user_lookup(db_session, monkeypatch):
        """Patch _get_user_by_username to use the test DB session."""
        from backend import auth as auth_module

        def _fake_get_user_by_username(username):
            user = db_session.query(User).filter(User.username == username).first()
            if user and user.is_active:
                return {
                    "username": user.username,
                    "email": user.email,
                    "display_name": user.display_name,
                    "department": user.department,
                    "is_admin": user.is_admin,
                    "role": user.role,
                    "user_id": user.id,
                }
            return None

        monkeypatch.setattr(auth_module, "_get_user_by_username", _fake_get_user_by_username)

    @pytest.fixture()
    def admin_auth(client, db_session):
        """Get admin user auth headers (creates admin if not exists)."""
        existing = db_session.query(User).filter(User.username == "admin").first()
        if existing:
            from backend.auth import create_access_token
            token = create_access_token({"sub": "admin", "is_admin": True})
            return {"Authorization": f"Bearer {token}"}

        admin = User(
            username="admin",
            email="admin@example.com",
            hashed_password=_fake_hash_password("adminpass"),
            role="admin",
            is_admin=True,
            approved=1,
            is_active=1,
        )
        db_session.add(admin)
        db_session.commit()
        db_session.refresh(admin)
        from backend.auth import create_access_token
        token = create_access_token({"sub": "admin", "is_admin": True})
        return {"Authorization": f"Bearer {token}"}

    @pytest.fixture()
    def user_auth(client, db_session):
        """Get regular user auth headers (creates user if not exists)."""
        existing = db_session.query(User).filter(User.username == "testuser").first()
        if existing:
            from backend.auth import create_access_token
            token = create_access_token({"sub": "testuser", "is_admin": False})
            return {"Authorization": f"Bearer {token}"}

        user = User(
            username="testuser",
            email="user@example.com",
            hashed_password=_fake_hash_password("userpass"),
            role="user",
            approved=1,
            is_active=1,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        from backend.auth import create_access_token
        token = create_access_token({"sub": "testuser", "is_admin": False})
        return {"Authorization": f"Bearer {token}"}

    # ───────────────── Create Customers ─────────────────

    class TestCustomerCreation:
        def test_create_customer(self, client, admin_auth):
            r = client.post("/api/customers/", json={
                "name": "Acme Corp",
                "description": "A test company",
            }, headers=admin_auth)
            assert r.status_code == 201
            data = r.json()
            assert data["name"] == "Acme Corp"
            assert "id" in data
            assert data["description"] == "A test company"

        def test_list_customers(self, client, admin_auth):
            client.post("/api/customers/", json={"name": "Customer A"}, headers=admin_auth)
            client.post("/api/customers/", json={"name": "Customer B"}, headers=admin_auth)
            r = client.get("/api/customers/", headers=admin_auth)
            assert r.status_code == 200
            data = r.json()
            assert isinstance(data, list)
            assert len(data) >= 2

        def test_get_customer_by_name(self, client, admin_auth):
            client.post("/api/customers/", json={"name": "GetMe"}, headers=admin_auth)
            r = client.get("/api/customers/GetMe/", headers=admin_auth)
            assert r.status_code == 200
            assert r.json()["name"] == "GetMe"

        def test_update_customer(self, client, admin_auth):
            client.post("/api/customers/", json={"name": "UpdateMe", "description": "Old"}, headers=admin_auth)
            r = client.put("/api/customers/UpdateMe/", json={"description": "Updated"}, headers=admin_auth)
            assert r.status_code == 200
            assert r.json()["description"] == "Updated"

        def test_delete_customer(self, client, admin_auth):
            client.post("/api/customers/", json={"name": "DeleteMe"}, headers=admin_auth)
            r = client.delete("/api/customers/DeleteMe/", headers=admin_auth)
            assert r.status_code == 204
            r2 = client.get("/api/customers/DeleteMe/", headers=admin_auth)
            assert r2.status_code == 404

        def test_duplicate_customer_fails(self, client, admin_auth):
            r1 = client.post("/api/customers/", json={"name": "Dup"}, headers=admin_auth)
            assert r1.status_code == 201
            r2 = client.post("/api/customers/", json={"name": "Dup"}, headers=admin_auth)
            assert r2.status_code == 400

    # ───────────────── Add User to Customer ─────────────────

    class TestAddUserToCustomer:
        def test_add_owner(self, client, admin_auth, db_session):
            client.post("/api/customers/", json={"name": "OwnerCust"}, headers=admin_auth)
            customer = db_session.query(Customer).filter(Customer.name == "OwnerCust").first()
            customer_id = customer.id
            user = User(username="owneruser", email="owner@test.example",
                       hashed_password="pass", role="user", approved=1, is_active=1)
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            r = client.post(
                "/api/customers/OwnerCust/users/",
                params={"user_id": user.id, "role": "owner"},
                headers=admin_auth,
            )
            assert r.status_code == 200
            data = r.json()
            assert data["role"] == "owner"
            assert data["customer_id"] == customer_id
            junction = db_session.query(CustomerUser).filter_by(
                customer_id=customer_id, user_id=user.id).first()
            assert junction is not None
            assert junction.role == "owner"

        def test_add_member(self, client, admin_auth, db_session):
            client.post("/api/customers/", json={"name": "MemberCust"}, headers=admin_auth)
            customer = db_session.query(Customer).filter(Customer.name == "MemberCust").first()
            customer_id = customer.id
            user = User(username="memberuser", email="member@test.example",
                       hashed_password="pass", role="user", approved=1, is_active=1)
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            r = client.post(
                "/api/customers/MemberCust/users/",
                params={"user_id": user.id, "role": "member"},
                headers=admin_auth,
            )
            assert r.status_code == 200
            assert r.json()["role"] == "member"
            junction = db_session.query(CustomerUser).filter_by(
                customer_id=customer_id, user_id=user.id).first()
            assert junction.role == "member"

        def test_add_auditor(self, client, admin_auth, db_session):
            client.post("/api/customers/", json={"name": "AuditorCust"}, headers=admin_auth)
            user = User(username="auditoruser", email="auditor@test.example",
                       hashed_password="pass", role="user", approved=1, is_active=1)
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            r = client.post(
                "/api/customers/AuditorCust/users/",
                params={"user_id": user.id, "role": "auditor"},
                headers=admin_auth,
            )
            assert r.status_code == 200
            assert r.json()["role"] == "auditor"

        def test_add_duplicate_user(self, client, admin_auth, db_session):
            client.post("/api/customers/", json={"name": "DupCust"}, headers=admin_auth)
            user = User(username="dupuser", email="dup@test.example",
                       hashed_password="pass", role="user", approved=1, is_active=1)
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            r1 = client.post(
                "/api/customers/DupCust/users/",
                params={"user_id": user.id, "role": "member"},
                headers=admin_auth,
            )
            assert r1.status_code == 200
            r2 = client.post(
                "/api/customers/DupCust/users/",
                params={"user_id": user.id, "role": "member"},
                headers=admin_auth,
            )
            assert r2.status_code == 400

        def test_add_invalid_role(self, client, admin_auth, db_session):
            client.post("/api/customers/", json={"name": "InvRole"}, headers=admin_auth)
            user = User(username="invalidroleuser", email="inv@test.example",
                       hashed_password="pass", role="user", approved=1, is_active=1)
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            r = client.post(
                "/api/customers/InvRole/users/",
                params={"user_id": user.id, "role": "superadmin"},
                headers=admin_auth,
            )
            assert r.status_code == 400

        def test_non_admin_cannot_add_user(self, client, user_auth, db_session, admin_auth):
            client.post("/api/customers/", json={"name": "NonAdmin"}, headers=admin_auth)
            user = User(username="otheruser", email="other@test.example",
                       hashed_password="pass", role="user", approved=1, is_active=1)
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            r = client.post(
                "/api/customers/NonAdmin/users/",
                params={"user_id": user.id, "role": "member"},
                headers=user_auth,
            )
            # 404-first (R4/Q7): out of scope for the owner/admin surface.
            assert r.status_code == 404

        def test_unauthenticated_cannot_add_user(self, client, db_session):
            user = User(username="unauthuser", email="unauth@test.example",
                       hashed_password="pass", role="user", approved=1, is_active=1)
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            r = client.post(
                "/api/customers/UnauthCust1/users/",
                params={"user_id": user.id, "role": "member"},
            )
            assert r.status_code == 401

    # ───────────────── List Users ─────────────────

    class TestListCustomerUsers:
        def test_list_users_for_customer(self, client, admin_auth, db_session):
            client.post("/api/customers/", json={"name": "ListCust"}, headers=admin_auth)
            customer = db_session.query(Customer).filter(Customer.name == "ListCust").first()
            admin = db_session.query(User).filter(User.username == "admin").first()
            customer_user = CustomerUser(customer_id=customer.id, user_id=admin.id, role="owner")
            db_session.add(customer_user)
            db_session.commit()
            for i in range(3):
                user = User(username=f"listuser{i}", email=f"list{i}@test.example",
                           hashed_password="pass", role="user", approved=1, is_active=1)
                db_session.add(user)
                db_session.commit()
                db_session.refresh(user)
                client.post(
                    "/api/customers/ListCust/users/",
                    params={"user_id": user.id, "role": "member"},
                    headers=admin_auth,
                )
            r = client.get("/api/customers/ListCust/users/", headers=admin_auth)
            assert r.status_code == 200
            data = r.json()
            assert "users" in data
            assert len(data["users"]) >= 3

        def test_no_access_can_not_list(self, client, user_auth, db_session, admin_auth):
            client.post("/api/customers/", json={"name": "SecretCust"}, headers=admin_auth)
            r = client.get("/api/customers/SecretCust/users/", headers=user_auth)
            # 404-first (R4/Q7): out-of-scope is the same 404 as a missing customer.
            assert r.status_code == 404

    # ───────────────── Check Access ─────────────────

    class TestCheckAccess:
        def test_has_access_owner(self, client, admin_auth, db_session):
            client.post("/api/customers/", json={"name": "HasOwner"}, headers=admin_auth)
            user = User(username="ownercheck", email="ownercheck@test.example",
                       hashed_password="pass", role="user", approved=1, is_active=1)
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            client.post(
                "/api/customers/HasOwner/users/",
                params={"user_id": user.id, "role": "owner"},
                headers=admin_auth,
            )
            from backend.auth import create_access_token
            user_token = create_access_token({"sub": "ownercheck", "is_admin": False})
            user_headers = {"Authorization": f"Bearer {user_token}"}
            r = client.get("/api/customers/HasOwner/access/", headers=user_headers)
            assert r.status_code == 200
            data = r.json()
            assert data["has_access"] is True
            assert data["permission_level"] == "owner"

        def test_no_access(self, client, user_auth, db_session, admin_auth):
            client.post("/api/customers/", json={"name": "NoAccess"}, headers=admin_auth)
            r = client.get("/api/customers/NoAccess/access/", headers=user_auth)
            assert r.status_code == 200
            data = r.json()
            assert data["has_access"] is False
            assert data["permission_level"] == "none"

        def test_central_read_without_junction_grants_access(self, client, db_session, admin_auth):
            # Part 13 R1 (2026-10-29): /access/ follows the CENTRAL read
            # policy — a membership without a legacy junction row now reports
            # has_access=true (the legacy junction-only check reported false;
            # DV3). permission_level stays the junction-role display ("none")
            # — the server enforces every write capability per route.
            from backend.models.account_membership import AccountMembership
            from backend.models.use_case import Customer
            client.post("/api/customers/", json={"name": "CentralRead"}, headers=admin_auth)
            customer = db_session.query(Customer).filter_by(name="CentralRead").first()
            user = User(username="centralread", email="centralread@test.example",
                        hashed_password="pass", role="user", approved=1, is_active=1)
            db_session.add(user)
            db_session.flush()
            db_session.add(AccountMembership(customer_id=customer.id, user_id=user.id, role="co_owner"))
            db_session.commit()
            from backend.auth import create_access_token
            headers = {"Authorization": f"Bearer {create_access_token({'sub': 'centralread', 'is_admin': False})}"}
            r = client.get("/api/customers/CentralRead/access/", headers=headers)
            assert r.status_code == 200
            data = r.json()
            assert data["has_access"] is True
            assert data["permission_level"] == "none"

    # ───────────────── Update Role ─────────────────

    class TestUpdateRole:
        def test_update_member_to_auditor(self, client, admin_auth, db_session):
            client.post("/api/customers/", json={"name": "UpdateRole"}, headers=admin_auth)
            customer = db_session.query(Customer).filter(Customer.name == "UpdateRole").first()
            customer_id = customer.id
            user = User(username="updaterole", email="updaterole@test.example",
                       hashed_password="pass", role="user", approved=1, is_active=1)
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            client.post(
                "/api/customers/UpdateRole/users/",
                params={"user_id": user.id, "role": "member"},
                headers=admin_auth,
            )
            r = client.put(
                f"/api/customers/UpdateRole/users/{user.id}/",
                params={"role": "auditor"},
                headers=admin_auth,
            )
            assert r.status_code == 200
            assert r.json()["role"] == "auditor"
            junction = db_session.query(CustomerUser).filter_by(
                customer_id=customer_id, user_id=user.id).first()
            assert junction.role == "auditor"

    # ───────────────── Remove User ─────────────────

    class TestRemoveUser:
        def test_remove_user(self, client, admin_auth, db_session):
            client.post("/api/customers/", json={"name": "RemoveCust"}, headers=admin_auth)
            customer = db_session.query(Customer).filter(Customer.name == "RemoveCust").first()
            customer_id = customer.id
            user = User(username="removeuser", email="remove@test.example",
                       hashed_password="pass", role="user", approved=1, is_active=1)
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            client.post(
                "/api/customers/RemoveCust/users/",
                params={"user_id": user.id, "role": "member"},
                headers=admin_auth,
            )
            junction = db_session.query(CustomerUser).filter_by(
                customer_id=customer_id, user_id=user.id).first()
            assert junction is not None
            r = client.delete(
                f"/api/customers/RemoveCust/users/{user.id}/",
                headers=admin_auth,
            )
            assert r.status_code == 200
            junction = db_session.query(CustomerUser).filter_by(
                customer_id=customer_id, user_id=user.id).first()
            assert junction is None

    # ───────────────── Get My Customers ─────────────────

    class TestGetMyCustomers:
        def test_get_my_customers(self, client, admin_auth, db_session):
            client.post("/api/customers/", json={"name": "MyCust"}, headers=admin_auth)
            admin = db_session.query(User).filter(User.username == "admin").first()
            client.post(
                "/api/customers/MyCust/users/",
                params={"user_id": admin.id, "role": "member"},
                headers=admin_auth,
            )
            r = client.get("/api/customers/me/customers/", headers=admin_auth)
            assert r.status_code == 200
            data = r.json()
            assert isinstance(data, list)
            assert len(data) >= 1

    # ───────────────── Access Control ─────────────────

    class TestAccessControl:
        def test_auditor_cannot_add_users(self, client, db_session, admin_auth):
            client.post("/api/customers/", json={"name": "AuditOnly"}, headers=admin_auth)
            user = User(username="auditoruser", email="auditor@test.example",
                       hashed_password="pass", role="user", approved=1, is_active=1)
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            client.post(
                "/api/customers/AuditOnly/users/",
                params={"user_id": user.id, "role": "auditor"},
                headers=admin_auth,
            )
            from backend.auth import create_access_token
            user_token = create_access_token({"sub": "auditoruser", "is_admin": False})
            user_headers = {"Authorization": f"Bearer {user_token}"}
            other = User(username="otheruser2", email="other2@test.example",
                        hashed_password="pass", role="user", approved=1, is_active=1)
            db_session.add(other)
            db_session.commit()
            db_session.refresh(other)
            r = client.post(
                "/api/customers/AuditOnly/users/",
                params={"user_id": other.id, "role": "member"},
                headers=user_headers,
            )
            # 404-first (R4/Q7): an auditor junction is out of scope for the
            # owner/admin mutation surface.
            assert r.status_code == 404

        def test_member_cannot_add_users(self, client, db_session, admin_auth):
            client.post("/api/customers/", json={"name": "MemberOnly"}, headers=admin_auth)
            user = User(username="memberuser2", email="member2@test.example",
                       hashed_password="pass", role="user", approved=1, is_active=1)
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            client.post(
                "/api/customers/MemberOnly/users/",
                params={"user_id": user.id, "role": "member"},
                headers=admin_auth,
            )
            from backend.auth import create_access_token
            user_token = create_access_token({"sub": "memberuser2", "is_admin": False})
            user_headers = {"Authorization": f"Bearer {user_token}"}
            other = User(username="otheruser3", email="other3@test.example",
                        hashed_password="pass", role="user", approved=1, is_active=1)
            db_session.add(other)
            db_session.commit()
            db_session.refresh(other)
            r = client.post(
                "/api/customers/MemberOnly/users/",
                params={"user_id": other.id, "role": "member"},
                headers=user_headers,
            )
            # 404-first (R4/Q7): a member is out of scope for the owner/admin
            # mutation surface.
            assert r.status_code == 404

        def test_owner_can_add_users(self, client, db_session, admin_auth):
            client.post("/api/customers/", json={"name": "OwnerOnly"}, headers=admin_auth)
            user = User(username="ownertest2", email="owner2@test.example",
                       hashed_password="pass", role="user", approved=1, is_active=1)
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            client.post(
                "/api/customers/OwnerOnly/users/",
                params={"user_id": user.id, "role": "owner"},
                headers=admin_auth,
            )
            from backend.auth import create_access_token
            user_token = create_access_token({"sub": "ownertest2", "is_admin": False})
            user_headers = {"Authorization": f"Bearer {user_token}"}
            other = User(username="otheruser4", email="other4@test.example",
                        hashed_password="pass", role="user", approved=1, is_active=1)
            db_session.add(other)
            db_session.commit()
            db_session.refresh(other)
            r = client.post(
                "/api/customers/OwnerOnly/users/",
                params={"user_id": other.id, "role": "member"},
                headers=user_headers,
            )
            assert r.status_code == 200
