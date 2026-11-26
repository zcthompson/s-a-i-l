"""Customer Intelligence tests — deterministic overview aggregation.

Verifies the CustomerIntelligenceService aggregates the four source tables
(Customer Knowledge, Technology Inventory, Sales Notes, Use Cases) into the
per-customer Overview: counts, groupings, derived indicators — all
deterministic (no LLM), unknowns stay unknown (zero/None, never fabricated),
and cross-customer data never leaks. Route auth follows the repo's
TestClient pattern (401/403/404 + admin bypass).
"""

from datetime import UTC, date, datetime

import pytest
from backend.models.sales_note import SalesNote

from tests.backend._shared import add_pipeline_batch
from tests.backend.common import _admin_headers


def _non_admin_headers(db_session, customer_id: int = 1) -> dict:
    from backend.auth import create_access_token
    from backend.models.use_case import Customer, CustomerUser, User

    username = f"intel_member_{customer_id}"
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
        db_session.add(Customer(id=customer_id, name=f"Intel Test Customer {customer_id}"))
        db_session.commit()
    existing_cu = (
        db_session.query(CustomerUser)
        .filter(CustomerUser.customer_id == customer_id)
        .filter(CustomerUser.user_id == user.id)
        .first()
    )
    if not existing_cu:
        db_session.add(CustomerUser(customer_id=customer_id, user_id=user.id, role="member"))
        db_session.commit()
    token = create_access_token({"sub": user.username, "is_admin": False})
    return {"Authorization": f"Bearer {token}"}


def _seed_customer(db_session, customer_id: int = 1) -> None:
    from backend.models.use_case import Customer

    if not db_session.query(Customer).filter(Customer.id == customer_id).first():
        db_session.add(Customer(id=customer_id, name=f"Intel Test Customer {customer_id}"))
        db_session.commit()


def _seed_tech(db_session, customer_id: int, **fields) -> int:
    from backend.services.technology_inventory_service import create_technology

    payload = {"name": fields.pop("name", "Seed Tech"), "category": fields.pop("category", "software")}
    payload.update(fields)
    return create_technology(db_session, customer_id, payload).id


def _seed_note(db_session, customer_id: int, **fields) -> int:
    from backend.schemas.sales_note import SalesNoteCreate
    from backend.services.sales_note_service import create_sales_note

    payload = {
        "category": fields.pop("category", "meeting"),
        "title": fields.pop("title", "Seed note"),
        "content": fields.pop("content", "Seed note content"),
    }
    payload.update(fields)
    return create_sales_note(db_session, customer_id, SalesNoteCreate(**payload)).id


def _seed_use_case(db_session, customer_id: int, **fields) -> int:
    from backend.models.use_case import UseCase

    uc = UseCase(
        title=fields.pop("title", "Seed use case"),
        customer_id=customer_id,
        status=fields.pop("status", "draft"),
        overall_score=fields.pop("overall_score", None),
    )
    db_session.add(uc)
    db_session.commit()
    db_session.refresh(uc)
    return uc.id


def _seed_knowledge(db_session, customer_id: int, **fields) -> int:
    from backend.models.customer_knowledge import CustomerKnowledge

    entry = CustomerKnowledge(
        customer_id=customer_id,
        knowledge_type=fields.pop("knowledge_type", "file"),
        file_name=fields.pop("file_name", "seed.pdf"),
        file_data=fields.pop("file_data", b"seed-bytes"),
        uploaded_at=fields.pop("uploaded_at", datetime.now(UTC)),
        processed=fields.pop("processed", 0),
        ingestion_status=fields.pop("ingestion_status", "pending"),
        classification=fields.pop("classification", None),
        category=fields.pop("category", None),
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry.id


def _overview(db_session, customer_id: int = 1) -> dict:
    from backend.services.customer_intelligence import get_customer_overview

    return get_customer_overview(db_session, customer_id)


class TestCustomerIntelligenceService:
    @pytest.fixture(autouse=True)
    def _existing_customer_parents(self, db_session):
        from backend.models.use_case import Customer
        db_session.add_all([Customer(id=1, name="Synthetic parent 1"), Customer(id=2, name="Synthetic parent 2")])
        db_session.commit()

    """Deterministic aggregation over the four source tables."""

    def test_empty_customer_overview(self, db_session):
        """No data anywhere: every indicator is zero/None — unknowns stay
        unknown, nothing fabricated, no exceptions."""
        ov = _overview(db_session, 1)
        assert ov["customer_id"] == 1
        assert ov["method"] == "deterministic_aggregation"
        assert ov["technology_inventory"]["total"] == 0
        assert ov["technology_inventory"]["by_category"] == {}
        assert ov["technology_inventory"]["unverified_pct"] is None
        assert ov["technology_inventory"]["average_confidence"] is None
        assert ov["sales_notes"]["total"] == 0
        assert ov["sales_notes"]["latest_note_date"] is None
        assert ov["sales_notes"]["days_since_latest_note"] is None
        assert ov["sales_notes"]["notes_stale"] is False
        assert ov["use_cases"]["total"] == 0
        assert ov["use_cases"]["scored_ratio"] is None
        assert ov["use_cases"]["average_overall_score"] is None
        assert ov["customer_knowledge"]["total"] == 0
        assert ov["indicators"]["eol_tech_count"] == 0
        assert ov["indicators"]["critical_tech_at_risk_count"] == 0

    def test_technology_aggregation(self, db_session):
        _seed_tech(db_session, 1, name="ESXi", vendor="VMware", category="virtualization",
                   version_edition="7.0 U3", lifecycle_state="eol_announced",
                   support_state="support_expiring", business_criticality="critical",
                   verification_state="verified", confidence=0.9)
        _seed_tech(db_session, 1, name="Windows Server", category="operating_system",
                   lifecycle_state="eol", support_state="no_support",
                   business_criticality="high", verification_state="inferred", confidence=0.6)
        _seed_tech(db_session, 1, name="Mystery Appliance", category="other",
                   verification_state="unverified")
        tech = _overview(db_session, 1)["technology_inventory"]
        assert tech["total"] == 3
        assert tech["by_category"] == {"virtualization": 1, "operating_system": 1, "other": 1}
        assert tech["by_verification"] == {"verified": 1, "inferred": 1, "unverified": 1}
        assert tech["by_lifecycle"] == {"eol_announced": 1, "eol": 1, "unknown": 1}
        assert tech["eol_count"] == 2
        assert tech["unverified_pct"] == round(100.0 * 2 / 3, 1)
        assert tech["average_confidence"] == round((0.9 + 0.6) / 2, 3)
        # At-risk: critical/high AND (no_support OR eol/eol_announced).
        at_risk = tech["critical_tech_at_risk"]
        assert tech["critical_tech_at_risk_count"] == 2
        names = {t["name"] for t in at_risk}
        assert names == {"ESXi", "Windows Server"}
        # Mystery Appliance: no criticality → not at risk.
        assert "Mystery Appliance" not in names

    def test_notes_freshness(self, db_session):
        old = date.today().replace(year=date.today().year - 1, day=1)
        _seed_note(db_session, 1, title="Old", note_date=old, category="meeting")
        _seed_note(db_session, 1, title="Recent", note_date=date.today(), category="risk",
                   content="Recent risk note", verification_state="verified")
        notes = _overview(db_session, 1)["sales_notes"]
        assert notes["total"] == 2
        assert notes["by_category"] == {"meeting": 1, "risk": 1}
        assert notes["latest_note_date"] == date.today().isoformat()
        assert notes["days_since_latest_note"] == 0
        assert notes["notes_stale"] is False
        # Only an old note → stale.
        db_session.query(SalesNote).filter(SalesNote.title == "Recent").delete()
        db_session.commit()
        notes = _overview(db_session, 1)["sales_notes"]
        assert notes["total"] == 1
        assert notes["days_since_latest_note"] > 90
        assert notes["notes_stale"] is True

    def test_use_case_aggregation(self, db_session):
        _seed_use_case(db_session, 1, title="UC draft")
        _seed_use_case(db_session, 1, title="UC scored", status="in_progress", overall_score=72.5)
        _seed_use_case(db_session, 1, title="UC scored 2", status="completed", overall_score=88.0)
        ucs = _overview(db_session, 1)["use_cases"]
        assert ucs["total"] == 3
        assert ucs["by_status"] == {"draft": 1, "in_progress": 1, "completed": 1}
        assert ucs["scored_count"] == 2
        assert ucs["scored_ratio"] == round(2 / 3, 3)
        assert ucs["average_overall_score"] == 80.25

    def test_knowledge_aggregation(self, db_session):
        _seed_knowledge(db_session, 1, knowledge_type="file", processed=0, ingestion_status="pending")
        _seed_knowledge(db_session, 1, knowledge_type="csv", processed=1, ingestion_status="processed", file_name="a.csv")
        _seed_knowledge(db_session, 1, knowledge_type="file", processed=0, ingestion_status="failed", file_name="b.pdf")
        kn = _overview(db_session, 1)["customer_knowledge"]
        assert kn["total"] == 3
        assert kn["by_type"] == {"file": 2, "csv": 1}
        assert kn["by_ingestion_status"] == {"pending": 1, "processed": 1, "failed": 1}
        assert kn["unprocessed_count"] == 2

    def test_cross_customer_no_leak(self, db_session):
        """Customer 2's sources never appear in customer 1's Overview."""
        _seed_tech(db_session, 2, name="Other Co Tech", category="software", verification_state="verified")
        _seed_note(db_session, 2, title="Other Co note")
        _seed_use_case(db_session, 2, title="Other Co UC", overall_score=50.0)
        _seed_knowledge(db_session, 2, knowledge_type="file")
        ov1 = _overview(db_session, 1)
        assert ov1["technology_inventory"]["total"] == 0
        assert ov1["sales_notes"]["total"] == 0
        assert ov1["use_cases"]["total"] == 0
        assert ov1["customer_knowledge"]["total"] == 0
        ov2 = _overview(db_session, 2)
        assert ov2["technology_inventory"]["total"] == 1
        assert ov2["sales_notes"]["total"] == 1
        assert ov2["use_cases"]["total"] == 1
        assert ov2["customer_knowledge"]["total"] == 1

    def test_deterministic_across_calls(self, db_session):
        """Two calls with the same data produce identical indicators —
        rule-based, no inference variance."""
        _seed_tech(db_session, 1, name="D1", category="software", verification_state="verified")
        _seed_note(db_session, 1, title="D2", note_date=date.today())
        _seed_use_case(db_session, 1, title="D3", overall_score=10.0)
        a = _overview(db_session, 1)
        b = _overview(db_session, 1)
        for key in ("technology_inventory", "sales_notes", "use_cases", "customer_knowledge", "indicators"):
            assert a[key] == b[key]
        assert a["method"] == b["method"] == "deterministic_aggregation"

    def test_partner_pipeline_is_additive_and_matches_pipeline_route(self, client, db_session, monkeypatch):
        from backend.models.use_case import Customer
        from backend.services import pipeline_read_model

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 10, 26, 15, 30, tzinfo=UTC)

        monkeypatch.setattr(pipeline_read_model, "datetime", FixedDatetime)
        _seed_customer(db_session)
        _seed_tech(db_session, 1, name="Synthetic Tech", category="software")
        _seed_note(db_session, 1, title="Synthetic observation", note_date=date.today())
        before = _overview(db_session)
        assert before["partner_pipeline"]["source"] is None
        customer = db_session.get(Customer, 1)
        add_pipeline_batch(db_session, [(customer, [
            {"est_acv_usd": 0.1}, {"est_acv_usd": 0.2, "est_tcv_usd": 9.99},
        ])])
        db_session.commit()
        headers = _admin_headers(db_session)
        overview = client.get("/api/customers/1/intelligence/overview/", headers=headers)
        route = client.get(f"/api/customers/{customer.name}/pipeline/", headers=headers)
        assert overview.status_code == route.status_code == 200
        after = overview.json()
        assert after["partner_pipeline"] == route.json()["summary"]
        for key in before.keys() - {"generated_at", "partner_pipeline"}:
            assert after[key] == before[key]
        assert after["partner_pipeline"]["amounts"]["acv"]["total"] == 0.3


class TestCustomerIntelligenceRoutes:
    """Route-level authorization for the Overview endpoint."""

    def test_unauthenticated_gets_401(self, client, db_session):
        assert client.get("/api/customers/1/intelligence/overview/").status_code == 401

    def test_missing_customer_gets_404(self, client, db_session):
        admin = _admin_headers(db_session)
        assert client.get("/api/customers/9999/intelligence/overview/", headers=admin).status_code == 404

    def test_user_without_customer_access_gets_404(self, client, db_session):
        _seed_customer(db_session, 1)
        _seed_customer(db_session, 2)
        headers = _non_admin_headers(db_session, customer_id=2)
        # 404-first: out-of-scope is the same 404 as a missing customer.
        assert client.get("/api/customers/1/intelligence/overview/", headers=headers).status_code == 404

    def test_member_can_read_overview(self, client, db_session):
        _seed_customer(db_session, 1)
        headers = _non_admin_headers(db_session, customer_id=1)
        r = client.get("/api/customers/1/intelligence/overview/", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["customer_id"] == 1
        assert body["method"] == "deterministic_aggregation"
        for section in ("technology_inventory", "sales_notes", "use_cases", "customer_knowledge"):
            assert section in body
        assert "indicators" in body

    def test_admin_without_junction_can_read(self, client, db_session):
        """Junction-less admin still reads any customer's Overview."""
        _seed_customer(db_session, 1)
        _seed_tech(db_session, 1, name="Admin View Tech", category="software")
        headers = _admin_headers(db_session)
        r = client.get("/api/customers/1/intelligence/overview/", headers=headers)
        assert r.status_code == 200
        assert r.json()["technology_inventory"]["total"] == 1
        assert r.json()["technology_inventory"]["by_category"] == {"software": 1}
