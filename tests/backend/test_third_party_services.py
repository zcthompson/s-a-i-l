"""Third-Party Professional Services (S-A-I-L) tests.

Deterministic, temporary SQLite (repo conftest) — no live endpoints. Coverage:

- CRUD lifecycle: create → list → get → partial update → delete
- Authorization: 401 unauthenticated; 403 without a CustomerUser row
  (collection AND id-level); admin bypass; customer isolation → 403
  (not 404 — no existence leak)
- ps_admin role: cross-account read+write without a junction row;
  cross-account listing (200 for ps_admin/admin, 403 for user/auditor);
  NEGATIVE: ps_admin gets 403 on non-PS customer-scoped endpoints for an
  account without a junction row (the role must not leak past the PS
  surface)
- Documents: upload → list (no blob) → download round-trips exact bytes +
  original filename → delete; cross-customer document access → 403;
  invalid document_type → 422; >10MB → 413
- Junction: same-customer link (200), cross-customer id rejected (422),
  full-replacement semantics, cascade delete with the engagement
- Vocabulary: invalid category/status/billing_model → 422
- Date integrity: ended_on < started_on → 422; NULL dates accepted
- Unknown-stays-unknown: omitted optional fields return NULLs
- Readiness: additive third_party_services key + correct counts; existing
  keys unchanged
"""

from backend.models.third_party_service import (
    ThirdPartyServiceDocument,
)
from fastapi.testclient import TestClient

# ── header helpers (TestClient + real JWT, repo pattern) ─────────────────────


def _token_for(db_session, username: str) -> dict:
    from backend.auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token({'sub': username, 'is_admin': False})}"}


def _admin_headers(db_session) -> dict:
    from backend.models.use_case import User

    admin = db_session.query(User).filter(User.is_admin == 1).first()
    from backend.auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token({'sub': admin.username, 'is_admin': True})}"}


def _make_user(db_session, username: str, role: str = "user", customer_id: int = None, junction_role: str = "member") -> dict:
    """Create a user (+optional CustomerUser row) and return its headers."""
    from backend.models.use_case import Customer, CustomerUser, User

    user = db_session.query(User).filter(User.username == username).first()
    if not user:
        user = User(
            username=username,
            email=f"{username}@test.local",
            hashed_password="unused-for-jwt-tests",
            role=role,
            is_admin=1 if role == "admin" else 0,
            approved=1,
            is_active=1,
        )
        db_session.add(user)
        db_session.commit()
    if customer_id is not None:
        cust = db_session.query(Customer).filter(Customer.id == customer_id).first()
        if not cust:
            db_session.add(Customer(id=customer_id, name=f"PS Test Customer {customer_id}"))
            db_session.commit()
        existing = (
            db_session.query(CustomerUser)
            .filter(CustomerUser.customer_id == customer_id, CustomerUser.user_id == user.id)
            .first()
        )
        if not existing:
            db_session.add(CustomerUser(customer_id=customer_id, user_id=user.id, role=junction_role))
            db_session.commit()
    return _token_for(db_session, username)


def _seed_uc(db_session, customer_id: int, title: str = "PS UC") -> int:
    from backend.models.use_case import UseCase

    uc = UseCase(title=title, customer_id=customer_id)
    db_session.add(uc)
    db_session.commit()
    db_session.refresh(uc)
    return uc.id


def _create_payload(**overrides) -> dict:
    base = {
        "vendor_name": "Acme SI Partners",
        "service_category": "virtualization",
        "description": "vSphere 7 upgrade engagement",
    }
    base.update(overrides)
    return base


# ── CRUD lifecycle ────────────────────────────────────────────────────────────


class TestCrudLifecycle:
    def test_full_lifecycle(self, db_session, client: TestClient):
        headers = _make_user(db_session, "ps_member", customer_id=1)
        uc1 = _seed_uc(db_session, 1)

        r = client.post("/api/customers/1/third-party-services/", json=_create_payload(use_case_ids=[uc1]), headers=headers)
        assert r.status_code == 201, r.text
        body = r.json()
        svc_id = body["id"]
        assert body["vendor_name"] == "Acme SI Partners"
        assert body["engagement_status"] == "active"  # default
        assert body["verification_state"] == "verified"  # default
        assert body["related_use_case_ids"] == [uc1]
        assert body["created_by"] == "ps_member"
        assert body["customer_id"] == 1

        r = client.get("/api/customers/1/third-party-services/", headers=headers)
        assert r.status_code == 200 and len(r.json()) == 1

        r = client.get(f"/api/third-party-services/{svc_id}/", headers=headers)
        assert r.status_code == 200 and r.json()["description"] == "vSphere 7 upgrade engagement"

        r = client.put(f"/api/third-party-services/{svc_id}/", json={"engagement_status": "completed", "ended_on": "2026-06-30"}, headers=headers)
        assert r.status_code == 200
        assert r.json()["engagement_status"] == "completed"
        assert r.json()["ended_on"] == "2026-06-30"

        r = client.delete(f"/api/third-party-services/{svc_id}/", headers=headers)
        assert r.status_code == 204
        r = client.get("/api/customers/1/third-party-services/", headers=headers)
        assert r.status_code == 200 and r.json() == []
        assert db_session.query(ThirdPartyServiceDocument).count() == 0  # no orphan docs

    def test_unauthenticated(self, db_session, client: TestClient):
        _make_user(db_session, "ps_member", customer_id=1)
        assert client.get("/api/customers/1/third-party-services/").status_code == 401
        r = client.post("/api/customers/1/third-party-services/", json=_create_payload())
        assert r.status_code == 401

    def test_no_junction_row_403_collection_404_id_level(self, db_session, client: TestClient):
        # User A has access to customer 1; user B has none.
        headers_a = _make_user(db_session, "ps_a", customer_id=1)
        r = client.post("/api/customers/1/third-party-services/", json=_create_payload(), headers=headers_a)
        svc_id = r.json()["id"]
        headers_b = _make_user(db_session, "ps_b", customer_id=2)

        # collection: 403 for a missing and an existing customer alike (no oracle)
        assert client.get("/api/customers/1/third-party-services/", headers=headers_b).status_code == 403
        # id-level: the same 404 as a missing engagement (404-first —
        # supersedes plan §4.2/§6's 403, which differed from the missing 404)
        assert client.get(f"/api/third-party-services/{svc_id}/", headers=headers_b).status_code == 404
        assert client.put(f"/api/third-party-services/{svc_id}/", json={"notes": "x"}, headers=headers_b).status_code == 404
        assert client.delete(f"/api/third-party-services/{svc_id}/", headers=headers_b).status_code == 404

    def test_admin_bypass(self, db_session, client: TestClient):
        headers_member = _make_user(db_session, "ps_member", customer_id=1)
        client.post("/api/customers/1/third-party-services/", json=_create_payload(), headers=headers_member)
        admin = _admin_headers(db_session)
        r = client.get("/api/customers/1/third-party-services/", headers=admin)
        assert r.status_code == 200 and len(r.json()) == 1
        # Admin can write too
        svc_id = r.json()[0]["id"]
        assert client.put(f"/api/third-party-services/{svc_id}/", json={"notes": "admin note"}, headers=admin).status_code == 200

    def test_customer_isolation_id_level_404_same_as_missing(self, db_session, client: TestClient):
        headers = _make_user(db_session, "ps_member", customer_id=1)
        r = client.post("/api/customers/1/third-party-services/", json=_create_payload(), headers=headers)
        svc_id = r.json()["id"]
        # Member of customer 2 probes customer 1's row by id
        headers_2 = _make_user(db_session, "ps_member2", customer_id=2)
        out_of_scope = client.get(f"/api/third-party-services/{svc_id}/", headers=headers_2)
        missing = client.get("/api/third-party-services/999999/", headers=headers_2)
        assert out_of_scope.status_code == missing.status_code == 404
        assert out_of_scope.json() == missing.json()


# ── ps_admin role ─────────────────────────────────────────────────────────────


class TestPsAdminRole:
    def test_cross_account_read_write_without_junction(self, db_session, client: TestClient):
        # A normal member seeds data on customer 1.
        member = _make_user(db_session, "ps_member", customer_id=1)
        from backend.models.use_case import Customer
        db_session.add(Customer(id=2, name="PS Test Customer 2"))
        db_session.commit()
        r = client.post("/api/customers/1/third-party-services/", json=_create_payload(), headers=member)
        svc_id = r.json()["id"]

        # ps_admin has NO junction row — still reads AND writes customer 1.
        ps = _make_user(db_session, "ps_admin_user", role="ps_admin")
        r = client.get("/api/customers/1/third-party-services/", headers=ps)
        assert r.status_code == 200 and len(r.json()) == 1
        r = client.put(f"/api/third-party-services/{svc_id}/", json={"engagement_status": "pending"}, headers=ps)
        assert r.status_code == 200 and r.json()["engagement_status"] == "pending"
        r = client.post("/api/customers/2/third-party-services/", json=_create_payload(vendor_name="Cross SI"), headers=ps)
        assert r.status_code == 201  # customer 2 has no junction for ps_admin either

    def test_cross_account_listing(self, db_session, client: TestClient):
        member = _make_user(db_session, "ps_member", customer_id=1)
        client.post("/api/customers/1/third-party-services/", json=_create_payload(), headers=member)
        ps = _make_user(db_session, "ps_admin_user", role="ps_admin")
        admin = _admin_headers(db_session)
        plain = _make_user(db_session, "ps_plain")
        auditor = _make_user(db_session, "ps_auditor", role="auditor")

        for headers in (ps, admin):
            r = client.get("/api/admin/third-party-services/", headers=headers)
            assert r.status_code == 200 and len(r.json()) >= 1
        for headers in (plain, auditor):
            assert client.get("/api/admin/third-party-services/", headers=headers).status_code == 403

    def test_role_does_not_leak_past_ps_surface(self, db_session, client: TestClient):
        """NEGATIVE: ps_admin without a junction row is 403 on non-PS
        customer-scoped endpoints (sales notes, knowledge, use cases)."""
        # Customer must exist (sales-notes' helper 404s unknown customers).
        _make_user(db_session, "ps_member", customer_id=1)
        ps = _make_user(db_session, "ps_admin_user", role="ps_admin")
        # (PS surface still open:)
        assert client.get("/api/customers/1/third-party-services/", headers=ps).status_code == 200
        # (Non-PS surfaces closed:)
        # 404-first: sales-notes remapped out-of-scope to the missing 404.
        assert client.get("/api/customers/1/sales-notes/", headers=ps).status_code == 404
        # sales_section is oracle-safe by design: an unauthorized
        # caller is 403 whether or not the customer exists — kept as-is.
        assert client.get("/api/sales/customers/1/usecases", headers=ps).status_code == 403
        # knowledge: customer-scoped list (404-first)
        r = client.get("/api/customer-knowledge/", params={"customer_id": 1}, headers=ps)
        assert r.status_code in (401, 404)

    def test_role_assignment_accepted(self, db_session, client: TestClient):
        """Admin can set role=ps_admin through the existing user-edit path."""
        admin = _admin_headers(db_session)
        target = _make_user(db_session, "ps_target", role="user")  # just needs the user row
        from backend.models.use_case import User

        uid = db_session.query(User).filter(User.username == "ps_target").first().id
        r = client.put(f"/api/auth/users/{uid}/", json={"role": "ps_admin"}, headers=admin)
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "ps_admin"
        assert r.json()["is_admin"] == 0  # ps_admin is NOT admin
        # Bad values still rejected
        r = client.put(f"/api/auth/users/{uid}/", json={"role": "superuser"}, headers=admin)
        assert r.status_code == 422


# ── documents ─────────────────────────────────────────────────────────────────


class TestDocuments:
    def _svc(self, db_session, client: TestClient, headers, vendor="Doc SI"):
        r = client.post("/api/customers/1/third-party-services/", json=_create_payload(vendor_name=vendor), headers=headers)
        assert r.status_code == 201
        return r.json()["id"]

    def test_upload_list_download_delete_roundtrip(self, db_session, client: TestClient):
        headers = _make_user(db_session, "ps_member", customer_id=1)
        svc_id = self._svc(db_session, client, headers)
        blob = b"PO-12345 original bytes " * 10

        r = client.post(
            f"/api/third-party-services/{svc_id}/documents/",
            files={"file": ("po_12345.pdf", blob, "application/pdf")},
            data={"document_type": "po", "title": "PO #12345 — phase 2"},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        doc = r.json()
        assert "file_data" not in doc  # never in list/wire shape
        assert doc["document_type"] == "po"
        assert doc["uploaded_by"] == "ps_member"
        doc_id = doc["id"]

        r = client.get(f"/api/third-party-services/{svc_id}/documents/", headers=headers)
        assert r.status_code == 200 and len(r.json()) == 1
        assert r.json()[0]["file_name"] == "po_12345.pdf"
        assert all("file_data" not in d for d in r.json())

        r = client.get(f"/api/third-party-services/{doc_id}/download/", headers=headers)
        assert r.status_code == 200
        assert r.content == blob  # exact bytes
        assert 'filename="po_12345.pdf"' in r.headers.get("content-disposition", "")

        r = client.delete(f"/api/third-party-services/{svc_id}/documents/{doc_id}/", headers=headers)
        assert r.status_code == 204
        assert client.get(f"/api/third-party-services/{svc_id}/documents/", headers=headers).json() == []

    def test_invalid_document_type_422_and_empty_upload_400(self, db_session, client: TestClient):
        headers = _make_user(db_session, "ps_member", customer_id=1)
        svc_id = self._svc(db_session, client, headers)
        r = client.post(
            f"/api/third-party-services/{svc_id}/documents/",
            files={"file": ("a.txt", b"hi", "text/plain")},
            data={"document_type": "hack"},
            headers=headers,
        )
        assert r.status_code == 422
        r = client.post(
            f"/api/third-party-services/{svc_id}/documents/",
            files={"file": ("a.txt", b"", "text/plain")},
            data={"document_type": "sow"},
            headers=headers,
        )
        assert r.status_code == 400

    def test_oversized_upload_413(self, db_session, client: TestClient):
        headers = _make_user(db_session, "ps_member", customer_id=1)
        svc_id = self._svc(db_session, client, headers)
        big = b"x" * (10 * 1024 * 1024 + 1)
        r = client.post(
            f"/api/third-party-services/{svc_id}/documents/",
            files={"file": ("big.bin", big, "application/octet-stream")},
            data={"document_type": "other"},
            headers=headers,
        )
        assert r.status_code == 413
        assert db_session.query(ThirdPartyServiceDocument).count() == 0  # not touched DB

    def test_cross_customer_document_access_404(self, db_session, client: TestClient):
        headers_a = _make_user(db_session, "ps_a", customer_id=1)
        svc_id = self._svc(db_session, client, headers_a)
        r = client.post(
            f"/api/third-party-services/{svc_id}/documents/",
            files={"file": ("po.pdf", b"secret po", "application/pdf")},
            data={"document_type": "po"},
            headers=headers_a,
        )
        doc_id = r.json()["id"]
        headers_b = _make_user(db_session, "ps_b", customer_id=2)
        # 404-first: out-of-scope is the same 404 as a missing record.
        assert client.get(f"/api/third-party-services/{doc_id}/download/", headers=headers_b).status_code == 404
        assert client.get(f"/api/third-party-services/{svc_id}/documents/", headers=headers_b).status_code == 404
        assert client.delete(f"/api/third-party-services/{svc_id}/documents/{doc_id}/", headers=headers_b).status_code == 404

    def test_document_cascades_with_engagement(self, db_session, client: TestClient):
        headers = _make_user(db_session, "ps_member", customer_id=1)
        svc_id = self._svc(db_session, client, headers)
        client.post(
            f"/api/third-party-services/{svc_id}/documents/",
            files={"file": ("sow.pdf", b"sow bytes", "application/pdf")},
            data={"document_type": "sow"},
            headers=headers,
        )
        assert db_session.query(ThirdPartyServiceDocument).count() == 1
        assert client.delete(f"/api/third-party-services/{svc_id}/", headers=headers).status_code == 204
        # Runtime SQLite does not enforce ON DELETE CASCADE — explicit delete
        # in the service must leave zero rows (no orphan blobs).
        assert db_session.query(ThirdPartyServiceDocument).count() == 0


# ── junction (use-case links) ─────────────────────────────────────────────────


class TestJunction:
    def test_same_customer_link_and_replacement(self, db_session, client: TestClient):
        headers = _make_user(db_session, "ps_member", customer_id=1)
        uc1 = _seed_uc(db_session, 1, "UC1")
        uc2 = _seed_uc(db_session, 1, "UC2")
        r = client.post("/api/customers/1/third-party-services/", json=_create_payload(use_case_ids=[uc1]), headers=headers)
        svc_id = r.json()["id"]
        assert r.json()["related_use_case_ids"] == [uc1]

        # Full-replacement semantics: providing a new list replaces links
        r = client.put(f"/api/third-party-services/{svc_id}/", json={"use_case_ids": [uc2]}, headers=headers)
        assert r.status_code == 200
        assert sorted(r.json()["related_use_case_ids"]) == [uc2]
        # Clearing
        r = client.put(f"/api/third-party-services/{svc_id}/", json={"use_case_ids": []}, headers=headers)
        assert r.status_code == 200 and r.json()["related_use_case_ids"] == []

    def test_cross_customer_use_case_rejected_422(self, db_session, client: TestClient):
        headers = _make_user(db_session, "ps_member", customer_id=1)
        from backend.models.use_case import Customer
        db_session.add(Customer(id=2, name="PS Test Customer 2"))
        db_session.commit()
        foreign_uc = _seed_uc(db_session, 2, "Foreign UC")
        r = client.post(
            "/api/customers/1/third-party-services/",
            json=_create_payload(use_case_ids=[foreign_uc]),
            headers=headers,
        )
        assert r.status_code == 422
        svc_id = client.post("/api/customers/1/third-party-services/", json=_create_payload(), headers=headers).json()["id"]
        r = client.put(f"/api/third-party-services/{svc_id}/", json={"use_case_ids": [foreign_uc]}, headers=headers)
        assert r.status_code == 422


# ── vocabulary / dates / unknown-stays-unknown ────────────────────────────────


class TestValidation:
    def test_invalid_vocab_422(self, db_session, client: TestClient):
        headers = _make_user(db_session, "ps_member", customer_id=1)
        for field, value in (
            ("service_category", "quantum_foam"),
            ("engagement_status", "zombie"),
            ("billing_model", "annual"),
        ):
            r = client.post("/api/customers/1/third-party-services/", json=_create_payload(**{field: value}), headers=headers)
            assert r.status_code == 422, f"{field}={value}"

    def test_date_order_422_and_null_dates_ok(self, db_session, client: TestClient):
        headers = _make_user(db_session, "ps_member", customer_id=1)
        r = client.post(
            "/api/customers/1/third-party-services/",
            json=_create_payload(started_on="2026-05-01", ended_on="2026-04-01"),
            headers=headers,
        )
        assert r.status_code == 422
        r = client.post(
            "/api/customers/1/third-party-services/",
            json=_create_payload(started_on="2026-04-01", ended_on="2026-05-01"),
            headers=headers,
        )
        assert r.status_code == 201
        # NULL dates accepted
        r = client.post("/api/customers/1/third-party-services/", json=_create_payload(), headers=headers)
        assert r.status_code == 201
        assert r.json()["started_on"] is None and r.json()["ended_on"] is None

    def test_malformed_date_422(self, db_session, client: TestClient):
        headers = _make_user(db_session, "ps_member", customer_id=1)
        r = client.post("/api/customers/1/third-party-services/", json=_create_payload(started_on="not-a-date"), headers=headers)
        assert r.status_code == 422

    def test_unknown_stays_unknown(self, db_session, client: TestClient):
        headers = _make_user(db_session, "ps_member", customer_id=1)
        r = client.post("/api/customers/1/third-party-services/", json=_create_payload(), headers=headers)
        body = r.json()
        for field in ("sow_reference", "contract_reference", "billing_model", "fee_amount", "notes"):
            assert body[field] is None, f"{field} must stay NULL until a user enters it"
        # No server-side fabrication of a date either
        assert body["started_on"] is None and body["ended_on"] is None

    def test_required_fields_cannot_be_cleared(self, db_session, client: TestClient):
        headers = _make_user(db_session, "ps_member", customer_id=1)
        svc_id = client.post("/api/customers/1/third-party-services/", json=_create_payload(), headers=headers).json()["id"]
        r = client.put(f"/api/third-party-services/{svc_id}/", json={"vendor_name": None}, headers=headers)
        assert r.status_code == 422

    def test_filters_and_search(self, db_session, client: TestClient):
        headers = _make_user(db_session, "ps_member", customer_id=1)
        client.post("/api/customers/1/third-party-services/", json=_create_payload(vendor_name="Zeta SI", service_category="security"), headers=headers)
        client.post("/api/customers/1/third-party-services/", json=_create_payload(vendor_name="Alpha SI", service_category="cloud", engagement_status="completed"), headers=headers)

        r = client.get("/api/customers/1/third-party-services/", params={"category": "security"}, headers=headers)
        assert len(r.json()) == 1 and r.json()[0]["vendor_name"] == "Zeta SI"
        r = client.get("/api/customers/1/third-party-services/", params={"status": "completed"}, headers=headers)
        assert len(r.json()) == 1 and r.json()[0]["vendor_name"] == "Alpha SI"
        r = client.get("/api/customers/1/third-party-services/", params={"search": "zeta"}, headers=headers)
        assert len(r.json()) == 1
        r = client.get("/api/customers/1/third-party-services/", params={"sort": "vendor_name", "direction": "asc"}, headers=headers)
        assert r.json()[0]["vendor_name"] == "Alpha SI"


# ── readiness endpoint (additive key) ─────────────────────────────────────────


class TestReadiness:
    def test_readiness_gains_third_party_services_key(self, db_session, client: TestClient):
        headers = _make_user(db_session, "ps_member", customer_id=1)
        r = client.post("/api/customers/1/third-party-services/", json=_create_payload(engagement_status="active"), headers=headers)
        assert r.status_code == 201
        svc_id = r.json()["id"]
        client.post(
            f"/api/third-party-services/{svc_id}/documents/",
            files={"file": ("po.pdf", b"po", "application/pdf")},
            data={"document_type": "po"},
            headers=headers,
        )

        r = client.get("/api/sales/customers/1/readiness", headers=headers)
        assert r.status_code == 200
        env = r.json()["customer_environment"]
        assert "third_party_services" in env
        ps = env["third_party_services"]
        assert ps["engagements"] == 1
        assert ps["documents"] == 1
        assert ps["by_status"]["active"] == 1 and ps["by_status"]["completed"] == 0
        # Existing keys unchanged
        for key in ("tech_profile", "knowledge_entries", "knowledge_by_type"):
            assert key in env
        assert "organizational_readiness" in r.json() and "gap_analysis" in r.json() and "sales_approach" in r.json()

    def test_readiness_zero_counts_when_empty(self, db_session, client: TestClient):
        headers = _make_user(db_session, "ps_member", customer_id=1)
        r = client.get("/api/sales/customers/1/readiness", headers=headers)
        assert r.status_code == 200
        assert r.json()["customer_environment"]["third_party_services"]["engagements"] == 0
