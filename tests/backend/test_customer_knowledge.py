"""Customer knowledge base tests — service CRUD, route authorization, and CSV ingestion.

Route tests follow the repo's TestClient auth pattern (test_integration.py):
a real JWT via create_access_token. Access is gated by the CustomerUser
junction WITH admin bypass (admins own all customers — the customers.py /
sales_section.py / sales_evaluations.py convention): non-admin tests use a
member user + junction row; admin-bypass tests use the junction-less admin.
"""


import pytest
from backend.models.customer_knowledge import CustomerKnowledge as CKModel

from tests.backend.common import _admin_headers


def _seed_customer_with_junction(db_session, customer_id: int = 1) -> None:
    """Seed a Customer row plus a CustomerUser junction row for the admin user.

    Admins bypass the junction on these routes (own all customers), so this
    helper exists for tests that assert scoped behavior for a specific
    customer id; the admin works either way.
    """
    from backend.models.use_case import Customer, CustomerUser, User

    admin = db_session.query(User).filter(User.is_admin == 1).first()
    existing = db_session.query(Customer).filter(Customer.id == customer_id).first()
    if not existing:
        db_session.add(Customer(id=customer_id, name=f"Test Customer {customer_id}"))
    existing_cu = (
        db_session.query(CustomerUser)
        .filter(CustomerUser.customer_id == customer_id)
        .filter(CustomerUser.user_id == admin.id)
        .first()
    )
    if not existing_cu:
        db_session.add(
            CustomerUser(customer_id=customer_id, user_id=admin.id, role="owner")
        )
    db_session.commit()


def _non_admin_headers(db_session, customer_id: int = 1) -> dict:
    """Authorization header for a non-admin user with a CustomerUser row.

    Seeds a non-admin User + Customer row + member junction row and returns
    a real JWT header — the junction row is this user's ONLY access to the
    customer (no admin bypass), making it the right caller for 403 tests.
    """
    from backend.auth import create_access_token
    from backend.models.use_case import Customer, CustomerUser, User

    username = f"member_{customer_id}"
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
        db_session.add(Customer(id=customer_id, name=f"Test Customer {customer_id}"))
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


def _csv_bytes(rows: int = 2) -> bytes:
    rows_data = [
        "software,version,status,vendor",
        "PostgreSQL,13,commercial,ACME Corp",
        "Redis,7,open_source,ACME Corp",
        "Elasticsearch,8,commercial,ACME Corp",
        "Kafka,3,open_source,ACME Corp",
    ]
    return ("\n".join(rows_data[: 1 + rows]) + "\n").encode()


class TestCustomerKnowledgeService:
    @pytest.fixture(autouse=True)
    def _existing_customer_parents(self, db_session):
        from backend.models.use_case import Customer
        db_session.add_all([Customer(id=1, name="Synthetic parent 1"), Customer(id=2, name="Synthetic parent 2")])
        db_session.commit()

    """Service-level CRUD tests for customer knowledge entries."""

    def test_create_and_list_knowledge(self, db_session):
        """Create a knowledge entry and list it back."""
        from backend.services.customer_knowledge_service import (
            create_customer_knowledge as _create,
        )
        from backend.services.customer_knowledge_service import (
            get_customer_knowledge_list,
        )

        entry = _create(
            db=db_session,
            customer_id=1,
            knowledge_type="software_inventory",
            file_name="test_software.csv",
            file_data=_csv_bytes(1),
            extracted_text="PostgreSQL 13 commercial ACME Corp",
        )
        assert entry is not None
        assert entry.knowledge_type == "software_inventory"
        assert entry.file_name == "test_software.csv"
        assert entry.uploaded_at is not None

        entries = get_customer_knowledge_list(db=db_session, customer_id=1)
        assert len(entries) >= 1
        assert entries[0].id == entry.id

    def test_update_knowledge(self, db_session):
        """Update a knowledge entry's classified type and category."""
        from backend.services.customer_knowledge_service import (
            create_customer_knowledge as _create,
        )
        from backend.services.customer_knowledge_service import (
            update_customer_knowledge,
        )

        entry = _create(
            db=db_session,
            customer_id=1,
            knowledge_type="software_inventory",
            file_name="test_update.csv",
            file_data=_csv_bytes(1),
            extracted_text="PostgreSQL 13 commercial ACME Corp",
        )

        updated = update_customer_knowledge(
            db=db_session,
            knowledge_id=entry.id,
            customer_id=1,
            payload={"classified_type": "process_document", "category": "db_tools"},
        )
        assert updated is not None
        # The service maps the payload key "classified_type" onto the model's
        # knowledge_type column (see update_customer_knowledge).
        assert updated.knowledge_type == "process_document"
        assert updated.category == "db_tools"

    def test_update_missing_entry_returns_none(self, db_session):
        from backend.services.customer_knowledge_service import (
            update_customer_knowledge,
        )

        assert (
            update_customer_knowledge(
                db=db_session, knowledge_id=9999, customer_id=1, payload={"category": "x"}
            )
            is None
        )

    def test_delete_knowledge(self, db_session):
        """Delete a knowledge entry."""
        from backend.services.customer_knowledge_service import (
            create_customer_knowledge as _create,
        )
        from backend.services.customer_knowledge_service import (
            delete_customer_knowledge,
            get_customer_knowledge_list,
        )

        entry = _create(
            db=db_session,
            customer_id=1,
            knowledge_type="software_inventory",
            file_name="test_delete.csv",
            file_data=_csv_bytes(1),
            extracted_text="PostgreSQL 13 commercial ACME Corp",
        )

        assert delete_customer_knowledge(
            db=db_session, knowledge_id=entry.id, customer_id=1
        ) is True
        remaining = get_customer_knowledge_list(db=db_session, customer_id=1)
        assert len(remaining) == 0

    def test_ingest_csv_knowledge(self, db_session):
        """CSV ingestion pipeline parses, classifies, and creates a DB record."""
        from backend.services.customer_knowledge_service import (
            ingest_knowledge_for_customer,
        )

        result = ingest_knowledge_for_customer(
            db=db_session, customer_id=1, file_data=_csv_bytes(2), file_type="csv"
        )

        assert result["success"] is True
        assert result["classified_type"] in {
            "software_inventory",
            "hardware_inventory",
            "process_document",
            "policy_document",
            "other",
        }
        assert len(result["entries"]) > 0
        assert result["errors"] == []

        # A row exists in the database for this customer
        rows = db_session.query(CKModel).filter(CKModel.customer_id == 1).all()
        assert len(rows) > 0

    def test_ingest_unsupported_file_type_fails(self, db_session):
        from backend.services.customer_knowledge_service import (
            ingest_knowledge_for_customer,
        )

        result = ingest_knowledge_for_customer(
            db=db_session, customer_id=1, file_data=b"junk", file_type="docx"
        )
        assert result["success"] is False
        assert len(result["errors"]) > 0


class TestCustomerKnowledgeRoutes:
    """Route authorization and CRUD tests for the customer-knowledge endpoints."""

    def test_unauthenticated_gets_401(self, client, db_session):
        assert client.get("/api/customer-knowledge/").status_code == 401
        # A POST that satisfies file validation but carries no Bearer token
        # reaches the auth gate and 401s.
        files = {"file": ("t.csv", b"software,version\nA,1\n", "text/csv")}
        assert client.post("/api/customer-knowledge/", files=files).status_code == 401

    def test_authenticated_user_with_customer_access_gets_list(self, client, db_session):
        """Authenticated user WITH a CustomerUser row for customer N can GET the list."""
        _seed_customer_with_junction(db_session, customer_id=1)
        from backend.services.customer_knowledge_service import (
            create_customer_knowledge as _create,
        )

        _create(
            db=db_session,
            customer_id=1,
            knowledge_type="software_inventory",
            file_name="test_entry.csv",
            file_data=_csv_bytes(1),
            extracted_text="PostgreSQL 13 commercial ACME Corp",
        )

        r = client.get("/api/customer-knowledge/", headers=_admin_headers(db_session))
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1
        assert any(e["customer_id"] == 1 for e in data)

    def test_authenticated_user_with_customer_access_can_delete(self, client, db_session):
        """Authenticated user WITH a CustomerUser row can DELETE an entry."""
        _seed_customer_with_junction(db_session, customer_id=1)
        from backend.services.customer_knowledge_service import (
            create_customer_knowledge as _create,
        )

        entry = _create(
            db=db_session,
            customer_id=1,
            knowledge_type="software_inventory",
            file_name="to_delete.csv",
            file_data=_csv_bytes(1),
            extracted_text="PostgreSQL 13 commercial ACME Corp",
        )

        r = client.delete(
            f"/api/customer-knowledge/{entry.id}", headers=_admin_headers(db_session)
        )
        assert r.status_code == 200
        remaining = db_session.query(CKModel).filter(CKModel.customer_id == 1).all()
        assert len(remaining) == 0

    def test_user_without_customer_access_gets_404_on_get_list(self, client, db_session):
        """Non-admin user with a CustomerUser row for customer 1 but NOT
        customer 2 gets the same 404 as a missing customer on GET with
        customer_id=2 (404-first, R4/Q7)."""
        headers = _non_admin_headers(db_session, customer_id=1)
        from backend.models.use_case import Customer

        db_session.add(Customer(id=2, name="Test Customer 2"))
        db_session.commit()

        r = client.get(
            "/api/customer-knowledge/?customer_id=2", headers=headers
        )
        assert r.status_code == 404

    def test_user_without_customer_access_gets_404_on_post(self, client, db_session):
        """Non-admin user without a CustomerUser row for the target customer
        gets the same 404 as a missing customer on POST (R4/Q7)."""
        headers = _non_admin_headers(db_session, customer_id=1)
        from backend.models.use_case import Customer

        db_session.add(Customer(id=2, name="Test Customer 2"))
        db_session.commit()

        files = {"file": ("test.csv", _csv_bytes(1), "text/csv")}
        r = client.post(
            "/api/customer-knowledge/",
            files=files,
            data={"customer_id": "2"},
            headers=headers,
        )
        assert r.status_code == 404

    def test_customer_id_query_filter_returns_only_that_customers_entries(
        self, client, db_session
    ):
        """customer_id query filter returns only that customer's entries when the
        user has access to two customers."""
        _seed_customer_with_junction(db_session, customer_id=1)
        _seed_customer_with_junction(db_session, customer_id=2)
        from backend.services.customer_knowledge_service import (
            create_customer_knowledge as _create,
        )

        _create(
            db=db_session,
            customer_id=1,
            knowledge_type="software_inventory",
            file_name="c1_entry.csv",
            file_data=_csv_bytes(1),
            extracted_text="PostgreSQL 13 commercial ACME Corp",
        )
        _create(
            db=db_session,
            customer_id=2,
            knowledge_type="software_inventory",
            file_name="c2_entry.csv",
            file_data=_csv_bytes(2),
            extracted_text="PostgreSQL 13 commercial ACME Corp",
        )

        r = client.get(
            "/api/customer-knowledge/?customer_id=1", headers=_admin_headers(db_session)
        )
        assert r.status_code == 200
        assert {e["customer_id"] for e in r.json()} == {1}

        r = client.get(
            "/api/customer-knowledge/?customer_id=2", headers=_admin_headers(db_session)
        )
        assert r.status_code == 200
        assert {e["customer_id"] for e in r.json()} == {2}

    def test_csv_upload_success(self, client, db_session):
        """CSV upload: deterministic CSV, POST multipart with customer_id form
        field — 200, success true, entries_count > 0, and a row exists."""
        _seed_customer_with_junction(db_session, customer_id=1)

        files = {"file": ("inventory.csv", _csv_bytes(2), "text/csv")}
        r = client.post(
            "/api/customer-knowledge/",
            files=files,
            data={"customer_id": "1"},
            headers=_admin_headers(db_session),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["entries_count"] > 0
        assert body["classified_type"] in {
            "software_inventory",
            "hardware_inventory",
            "process_document",
            "policy_document",
            "other",
        }

        rows = db_session.query(CKModel).filter(CKModel.customer_id == 1).all()
        assert len(rows) > 0

    def test_csv_upload_without_customer_id_uses_first_accessible(self, client, db_session):
        """CSV upload without an explicit customer_id uses the user's first
        accessible customer."""
        _seed_customer_with_junction(db_session, customer_id=1)

        files = {"file": ("es.csv", _csv_bytes(1), "text/csv")}
        r = client.post(
            "/api/customer-knowledge/",
            files=files,
            headers=_admin_headers(db_session),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        rows = db_session.query(CKModel).filter(CKModel.customer_id == 1).all()
        assert len(rows) > 0

    def test_get_missing_entry_gets_404(self, client, db_session):
        _seed_customer_with_junction(db_session, customer_id=1)
        r = client.get(
            "/api/customer-knowledge/9999", headers=_admin_headers(db_session)
        )
        assert r.status_code == 404


class TestCustomerKnowledgeAdminBypass:
    """Admins own all customers WITHOUT CustomerUser junction rows (the
    customers.py / sales_section.py / sales_evaluations.py convention).
    The conftest-seeded admin user has no junction rows by default — exactly
    the dev situation that produced 403 'Not authorized for this customer'
    in the Customer Knowledge UI."""

    def test_admin_without_junction_row_gets_200_on_scoped_list(self, client, db_session):
        """Admin with no CustomerUser rows can read a customer's entries by id
        (regression: was 403 'Not authorized for this customer')."""
        from backend.models.use_case import Customer
        from backend.services.customer_knowledge_service import (
            create_customer_knowledge as _create,
        )

        db_session.add(Customer(id=7, name="Admin Scope Customer"))
        db_session.commit()
        _create(
            db=db_session,
            customer_id=7,
            knowledge_type="software_inventory",
            file_name="admin_entry.csv",
            file_data=_csv_bytes(1),
            extracted_text="PostgreSQL 13 commercial ACME Corp",
        )

        r = client.get(
            "/api/customer-knowledge/?customer_id=7", headers=_admin_headers(db_session)
        )
        assert r.status_code == 200
        assert any(e["customer_id"] == 7 for e in r.json())

    def test_admin_unscoped_list_sees_entries_from_all_customers(self, client, db_session):
        """Admin without a customer_id filter sees entries from every customer."""
        from backend.models.use_case import Customer
        from backend.services.customer_knowledge_service import (
            create_customer_knowledge as _create,
        )

        db_session.add(Customer(id=8, name="Admin All Customer A"))
        db_session.add(Customer(id=9, name="Admin All Customer B"))
        db_session.commit()
        _create(
            db=db_session,
            customer_id=8,
            knowledge_type="software_inventory",
            file_name="a.csv",
            file_data=_csv_bytes(1),
        )
        _create(
            db=db_session,
            customer_id=9,
            knowledge_type="software_inventory",
            file_name="b.csv",
            file_data=_csv_bytes(1),
        )

        r = client.get("/api/customer-knowledge/", headers=_admin_headers(db_session))
        assert r.status_code == 200
        assert {e["customer_id"] for e in r.json()} == {8, 9}

    def test_admin_can_upload_without_junction_row(self, client, db_session):
        """Admin CSV upload targeting a customer with no junction row — 200
        (regression: was 403 'Not authorized for this customer')."""
        from backend.models.use_case import Customer

        db_session.add(Customer(id=10, name="Admin Upload Customer"))
        db_session.commit()

        files = {"file": ("admin_inv.csv", _csv_bytes(1), "text/csv")}
        r = client.post(
            "/api/customer-knowledge/",
            files=files,
            data={"customer_id": "10"},
            headers=_admin_headers(db_session),
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
        rows = db_session.query(CKModel).filter(CKModel.customer_id == 10).all()
        assert len(rows) > 0

    def test_admin_per_id_get_put_delete(self, client, db_session):
        """Admin per-id GET/PUT/DELETE work without junction rows (PUT also
        pins the former TypeError: service called with 3 of 4 arguments)."""
        from backend.models.use_case import Customer
        from backend.services.customer_knowledge_service import (
            create_customer_knowledge as _create,
        )

        db_session.add(Customer(id=11, name="Admin PerId Customer"))
        db_session.commit()
        entry = _create(
            db=db_session,
            customer_id=11,
            knowledge_type="software_inventory",
            file_name="per_id.csv",
            file_data=_csv_bytes(1),
        )
        headers = _admin_headers(db_session)

        r = client.get(f"/api/customer-knowledge/{entry.id}", headers=headers)
        assert r.status_code == 200
        assert r.json()["id"] == entry.id

        r = client.put(
            f"/api/customer-knowledge/{entry.id}",
            json={"category": "databases"},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["category"] == "databases"

        r = client.delete(f"/api/customer-knowledge/{entry.id}", headers=headers)
        assert r.status_code == 200
        assert db_session.query(CKModel).filter(CKModel.id == entry.id).first() is None
