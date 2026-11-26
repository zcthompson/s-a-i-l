"""Account workspace tests — summaries + Opportunities & Attention.

Verifies get_account_workspace: four actionable summaries (Technology
Landscape, Knowledge, Sales Activity, Assessment & Use Case), consolidated
Business Impact, latest-evaluation reference, and the typed, evidence-backed
opportunities synthesis (lifecycle_risk, observed_gap, growth_opportunity,
discovery_needed, follow_up) — deterministic, nothing invented, degrades
gracefully for empty customers. Route auth follows the repo TestClient
pattern (401/403/404 + admin bypass).
"""

from datetime import UTC, date, datetime, timedelta

from backend.models.customer_knowledge import CustomerKnowledge
from backend.models.customer_technology import CustomerTechnology
from backend.models.sales_evaluation import SalesEvaluation
from backend.models.sales_note import SalesNote
from backend.models.use_case import (
    Customer,
    CustomerAssessment,
    CustomerUser,
    UseCase,
    User,
)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _seed_customer(db_session, customer_id: int = 1) -> None:
    if not db_session.query(Customer).filter(Customer.id == customer_id).first():
        db_session.add(
            Customer(id=customer_id, name=f"WS Test Customer {customer_id}")
        )
        db_session.commit()


def _seed_tech(db_session, customer_id: int, **fields) -> int:
    _seed_customer(db_session, customer_id)
    t = CustomerTechnology(customer_id=customer_id, name=fields.pop("name", "WS Tech"), **fields)
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t.id


def _seed_note(db_session, customer_id: int, **fields) -> int:
    _seed_customer(db_session, customer_id)
    n = SalesNote(customer_id=customer_id, **fields)
    db_session.add(n)
    db_session.commit()
    db_session.refresh(n)
    return n.id


def _seed_knowledge(db_session, customer_id: int, **fields) -> int:
    _seed_customer(db_session, customer_id)
    entry = CustomerKnowledge(
        customer_id=customer_id,
        knowledge_type=fields.pop("knowledge_type", "file"),
        file_name=fields.pop("file_name", "ws.pdf"),
        file_data=fields.pop("file_data", b"ws-bytes"),
        uploaded_at=fields.pop("uploaded_at", _utcnow()),
        processed=fields.pop("processed", 1),
        ingestion_status=fields.pop("ingestion_status", "processed"),
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry.id


def _seed_uc(db_session, customer_id: int, **fields) -> int:
    _seed_customer(db_session, customer_id)
    uc = UseCase(customer_id=customer_id, title=fields.pop("title", "WS UC"), **fields)
    db_session.add(uc)
    db_session.commit()
    db_session.refresh(uc)
    return uc.id


def _seed_evaluation(db_session, customer_id: int, **fields) -> int:
    _seed_customer(db_session, customer_id)
    ev = SalesEvaluation(
        customer_id=customer_id,
        evaluation_name=fields.pop("evaluation_name", "WS Evaluation"),
        persona=fields.pop("persona", None),
        risk_factors=fields.pop("risk_factors", None),
        growth_opportunities=fields.pop("growth_opportunities", None),
        persona_sections=fields.pop("persona_sections", None),
    )
    db_session.add(ev)
    db_session.commit()
    db_session.refresh(ev)
    return ev.id


def _workspace(db_session, customer_id: int = 1) -> dict:
    from backend.services.customer_intelligence import get_account_workspace

    return get_account_workspace(db_session, customer_id)


def _admin_headers(db_session) -> dict:
    from backend.auth import create_access_token

    admin = db_session.query(User).filter(User.is_admin == 1).first()
    token = create_access_token({"sub": admin.username, "is_admin": True})
    return {"Authorization": f"Bearer {token}"}


def _non_admin_headers(db_session, customer_id: int = 1) -> dict:
    from backend.auth import create_access_token

    username = f"ws_member_{customer_id}"
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


class TestAccountWorkspaceService:
    """Deterministic summaries + opportunities synthesis."""

    def test_empty_customer_workspace_degrades(self, db_session):
        """No data anywhere: every summary is zero/None, discovery cards
        surface the gaps, nothing fabricated, no exceptions."""
        ws = _workspace(db_session, 1)
        assert ws["method"] == "deterministic_aggregation"
        assert ws["technology_landscape"]["total"] == 0
        assert ws["knowledge"]["total"] == 0
        assert ws["sales_activity"]["total_notes"] == 0
        assert ws["sales_activity"]["last_interaction"] is None
        assert ws["assessment"]["active_assessment"] is None
        assert ws["assessment"]["average_score"] is None
        assert ws["business_impact"]["total_impact"] == 0.0
        assert ws["latest_evaluation"] is None
        ids = {c["id"] for c in ws["opportunities"]}
        assert "discovery-needed-technology" in ids
        assert "discovery-needed-sales-activity" in ids
        assert ws["headline"]["open_opportunities_count"] == len(ws["opportunities"])

    def test_technology_landscape_summary(self, db_session):
        _seed_tech(db_session, 1, name="ESXi 6.5", vendor="VMware",
                   category="virtualization", lifecycle_state="eol",
                   support_state="no_support", business_criticality="critical",
                   purpose="Core VM hosting", verification_state="verified")
        _seed_tech(db_session, 1, name="vSAN", vendor="VMware",
                   category="storage", lifecycle_state="current",
                   support_state="under_support", business_criticality="medium",
                   verification_state="verified")
        _seed_tech(db_session, 1, name="Catalyst 3750", vendor="Cisco",
                   category="networking", lifecycle_state="current",
                   support_state="under_support", business_criticality="medium",
                   verification_state="verified")
        tl = _workspace(db_session, 1)["technology_landscape"]
        assert tl["total"] == 3
        assert tl["key_vendors"][0] == {"key": "VMware", "count": 2}
        assert tl["eol_count"] == 1
        assert tl["unsupported_count"] == 1
        assert tl["at_risk_count"] == 1
        assert "1 item(s) at end-of-life" in tl["important_gaps"]
        assert "1 item(s) with no vendor support" in tl["important_gaps"]

    def test_knowledge_summary(self, db_session):
        _seed_knowledge(db_session, 1, file_name="recent.pdf",
                        uploaded_at=_utcnow() - timedelta(days=5))
        _seed_knowledge(db_session, 1, file_name="old.csv", processed=0,
                        ingestion_status="pending",
                        uploaded_at=_utcnow() - timedelta(days=40))
        kn = _workspace(db_session, 1)["knowledge"]
        assert kn["total"] == 2
        assert kn["sources"] == {"processed": 1, "pending": 1}
        assert kn["unprocessed_count"] == 1
        assert kn["recently_added_count"] == 1  # only the 5-day-old entry
        assert kn["latest_uploaded"] is not None
        assert 0 <= kn["days_since_latest"] <= 5

    def test_sales_activity_summary(self, db_session):
        _seed_note(db_session, 1, category="meeting", title="Old meeting",
                   content="old", note_date=date.today() - timedelta(days=120),
                   verification_state="verified")
        _seed_note(db_session, 1, category="risk", title="Recent risk",
                   content="new", note_date=date.today() - timedelta(days=2),
                   verification_state="verified")
        _seed_note(db_session, 1, category="account_observation",
                   title="Account observation", content="obs",
                   note_date=date.today() - timedelta(days=1),
                   verification_state="verified")
        sa = _workspace(db_session, 1)["sales_activity"]
        assert sa["total_notes"] == 3
        # The 1-day-old observation is the most recent interaction.
        assert sa["last_interaction"]["title"] == "Account observation"
        assert sa["days_since_last_interaction"] == 1
        assert sa["notes_stale"] is False
        obs_titles = {n["title"] for n in sa["active_observations"]}
        assert obs_titles == {"Account observation"}
        assert len(sa["recent"]) == 3

    def test_assessment_summary(self, db_session):
        _seed_customer(db_session, 1)
        assessment = CustomerAssessment(customer_id=1, name="WS Round 1", status="active")
        db_session.add(assessment)
        db_session.commit()
        ids = [_seed_uc(db_session, 1, title="Strong", overall_score=85.0),
               _seed_uc(db_session, 1, title="Weak", overall_score=40.0),
               _seed_uc(db_session, 1, title="Draft")]
        for uid in ids:
            db_session.query(UseCase).filter(UseCase.id == uid).update({"assessment_id": assessment.id})
        db_session.commit()
        a = _workspace(db_session, 1)["assessment"]
        assert a["active_assessment"]["status"] == "active"
        assert a["active_assessment"]["total_count"] == 3
        assert a["active_assessment"]["scored_count"] == 2
        assert a["active_assessment"]["progress_pct"] == 66.7
        assert a["top_use_cases"][0]["title"] == "Strong"
        assert a["unscored_count"] == 1
        assert a["average_score"] == 62.5
        # Account-level stats are customer-wide (all UCs happen to be
        # linked to the round, so they agree with the round's numbers).
        assert a["total_count"] == 3
        assert a["scored_count"] == 2
        assert _workspace(db_session, 1)["headline"]["active_use_cases"] == 3

    def test_assessment_summary_unlinked_use_cases(self, db_session):
        """Regression: the active round must not shrink the account-level
        use-case counts. Legacy use cases predate round linkage and carry
        assessment_id=NULL; when an active round exists, scoping the
        account stats to the round's linked use cases made the Customer
        Overview report "0 use cases total / 0 scored" while the same
        card showed the customer-wide average score and top use cases,
        and the Assessments section showed the completed use cases
        (user-reported defect, the Overview Use Case card bug)."""
        _seed_customer(db_session, 1)
        assessment = CustomerAssessment(customer_id=1, name="WS Round 1", status="active")
        db_session.add(assessment)
        db_session.commit()
        # Scored use cases NOT linked to the round (legacy state).
        for i, score in enumerate((85.0, 40.0, 72.5)):
            _seed_uc(db_session, 1, title=f"Legacy UC {i}", overall_score=score,
                     status="completed")
        _seed_uc(db_session, 1, title="Legacy draft")
        # One new use case linked to the round (UI-created state).
        linked = _seed_uc(db_session, 1, title="Round UC", overall_score=90.0)
        db_session.query(UseCase).filter(UseCase.id == linked).update(
            {"assessment_id": assessment.id})
        db_session.commit()
        ws = _workspace(db_session, 1)
        a = ws["assessment"]
        # Round progress stays round-scoped.
        assert a["active_assessment"]["total_count"] == 1
        assert a["active_assessment"]["scored_count"] == 1
        assert a["active_assessment"]["progress_pct"] == 100.0
        # Account-level stats are customer-wide — NOT 0, NOT 1 (the round).
        assert a["total_count"] == 5
        assert a["scored_count"] == 4
        assert a["unscored_count"] == 1
        assert a["average_score"] is not None and a["average_score"] > 0
        assert ws["headline"]["active_use_cases"] == 5

    def test_assessment_summary_no_round_keeps_customer_wide_stats(self, db_session):
        """With no round at all the account stats are customer-wide
        (the pre-existing behavior, kept stable)."""
        _seed_customer(db_session, 1)
        for i, score in enumerate((85.0, 40.0)):
            _seed_uc(db_session, 1, title=f"UC {i}", overall_score=score)
        _seed_uc(db_session, 1, title="Draft")
        a = _workspace(db_session, 1)["assessment"]
        assert a["active_assessment"] is None
        assert a["total_count"] == 3
        assert a["scored_count"] == 2
        assert a["unscored_count"] == 1

    def test_business_impact_consolidated(self, db_session):
        _seed_uc(db_session, 1, title="UC A", estimated_savings=1000.0, estimated_revenue=500.0)
        _seed_uc(db_session, 1, title="UC B", estimated_savings=250.0)
        _seed_uc(db_session, 1, title="UC C")
        bi = _workspace(db_session, 1)["business_impact"]
        assert bi["total_savings"] == 1250.0
        assert bi["total_revenue"] == 500.0
        assert bi["total_impact"] == 1750.0
        assert bi["contributing_use_cases"] == 2

    def test_opportunities_lifecycle_risk(self, db_session):
        tid = _seed_tech(db_session, 1, name="Legacy DB", vendor="Oracle",
                         category="software", lifecycle_state="eol",
                         support_state="no_support", business_criticality="critical",
                         purpose="Core OLTP", verification_state="verified")
        ws = _workspace(db_session, 1)
        lr = [c for c in ws["opportunities"] if c["type"] == "lifecycle_risk"]
        assert len(lr) == 1
        assert lr[0]["severity"] == "high"
        assert lr[0]["evidence"] == {
            "source": "technology", "source_id": tid, "source_name": "Legacy DB",
        }
        # High-severity cards sort first; contact coverage is the deterministic head.
        head = ws["opportunities"][0]
        assert head["id"] == "contact-coverage-1"
        assert head["severity"] == "high"
        assert head["type"] == "contact_coverage"
        assert head["evidence"]["source"] == "customer_contacts"
        assert ws["opportunities"][1]["id"] == f"lifecycle-risk-tech-{tid}"

    def test_opportunities_observed_gap_and_evaluation_ref(self, db_session):
        _seed_evaluation(
            db_session, 1, evaluation_name="WS Eval", persona="ciso",
            risk_factors=[
                {"category": "security_posture",
                 "description": "Risk: no patching on 3 systems",
                 "mitigation": "Targeted assessment"}
            ],
            persona_sections={
                "discovery_gaps": [
                    {"area": "technology_inventory", "gap": "No inventory",
                     "action": "Run discovery"}
                ]
            },
        )
        ws = _workspace(db_session, 1)
        og = [c for c in ws["opportunities"] if c["type"] == "observed_gap"]
        assert len(og) == 1
        assert og[0]["severity"] == "high"
        assert og[0]["title"] == "Security Posture"
        assert og[0]["detail"].startswith("Risk:")
        assert og[0]["evidence"]["source"] == "sales_evaluation"
        le = ws["latest_evaluation"]
        assert le["persona"] == "ciso"
        assert le["discovery_gaps"][0]["area"] == "technology_inventory"

    def test_opportunities_growth_opportunity_threshold(self, db_session):
        hi = _seed_uc(db_session, 1, title="Strong UC", overall_score=82.0)
        lo = _seed_uc(db_session, 1, title="Weak UC", overall_score=55.0)
        ws = _workspace(db_session, 1)
        go_ids = {
            c["evidence"]["source_id"]
            for c in ws["opportunities"]
            if c["type"] == "growth_opportunity"
        }
        assert hi in go_ids
        assert lo not in go_ids

    def test_opportunities_discovery_needed(self, db_session):
        _seed_customer(db_session, 2)
        ws_empty = _workspace(db_session, 2)
        ids = {c["id"]: c["type"] for c in ws_empty["opportunities"]}
        assert ids.get("discovery-needed-technology") == "discovery_needed"
        assert ids.get("discovery-needed-sales-activity") == "discovery_needed"
        # Unprocessed knowledge adds the knowledge card.
        _seed_knowledge(db_session, 2, processed=0, ingestion_status="pending")
        ids = {c["id"] for c in _workspace(db_session, 2)["opportunities"]}
        assert "discovery-needed-knowledge" in ids
        # A stale note swaps "no activity" for the stale-interaction card.
        _seed_note(db_session, 2, category="meeting", title="Old note",
                   content="old", note_date=date.today() - timedelta(days=120),
                   verification_state="verified")
        ids = {c["id"] for c in _workspace(db_session, 2)["opportunities"]}
        assert "discovery-needed-sales-stale" in ids
        assert "discovery-needed-sales-activity" not in ids

    def test_opportunities_follow_up_window(self, db_session):
        nid = _seed_note(db_session, 1, category="risk", title="Risky note",
                         content="x", note_date=date.today() - timedelta(days=5),
                         verification_state="verified")
        _seed_note(db_session, 1, category="risk", title="Old risky note",
                   content="x", note_date=date.today() - timedelta(days=90),
                   verification_state="verified")
        ws = _workspace(db_session, 1)
        fu = [c for c in ws["opportunities"] if c["type"] == "follow_up"]
        assert len(fu) == 1
        assert fu[0]["id"] == f"follow-up-note-{nid}"
        assert fu[0]["severity"] == "medium"
        assert fu[0]["evidence"]["source_id"] == nid

    def test_opportunities_capped(self, db_session):
        # 5 at-risk tech (the evidence list caps at 5) + 5 growth UCs
        # (score >= 70) + 3 high-severity evaluation findings + 1 discovery
        # card (no notes) = 14 candidates -> capped at 12.
        for i in range(5):
            _seed_tech(db_session, 1, name=f"Risk-{i}", vendor="V",
                       category="software", lifecycle_state="eol",
                       support_state="no_support", business_criticality="critical",
                       verification_state="verified")
        for i in range(5):
            _seed_uc(db_session, 1, title=f"Growth-{i}", overall_score=75.0 + i)
        _seed_evaluation(
            db_session, 1,
            risk_factors=[
                {"category": f"gap_{i}", "description": f"Risk {i}",
                 "mitigation": "m"}
                for i in range(3)
            ],
        )
        ws = _workspace(db_session, 1)
        assert len(ws["opportunities"]) == 12

    def test_cross_customer_no_leak(self, db_session):
        _seed_tech(db_session, 2, name="Other Co Tech", category="software",
                   verification_state="verified")
        _seed_note(db_session, 2, category="meeting", title="Other note",
                   content="x", note_date=date.today(), verification_state="verified")
        ws1 = _workspace(db_session, 1)
        assert ws1["technology_landscape"]["total"] == 0
        assert ws1["sales_activity"]["total_notes"] == 0
        ws2 = _workspace(db_session, 2)
        assert ws2["technology_landscape"]["total"] == 1
        assert ws2["sales_activity"]["total_notes"] == 1

    def test_deterministic_across_calls(self, db_session):
        _seed_tech(db_session, 1, name="D1", category="software",
                   verification_state="verified")
        _seed_note(db_session, 1, category="meeting", title="D2", content="x",
                   note_date=date.today(), verification_state="verified")
        a = _workspace(db_session, 1)
        b = _workspace(db_session, 1)
        for key in ("technology_landscape", "knowledge", "sales_activity",
                    "assessment", "business_impact", "opportunities", "headline"):
            assert a[key] == b[key]
        assert a["method"] == b["method"] == "deterministic_aggregation"


class TestAccountWorkspaceRoutes:
    """Route-level authorization for the workspace endpoint."""

    def test_unauthenticated_gets_401(self, client, db_session):
        assert client.get("/api/customers/1/intelligence/workspace/").status_code == 401

    def test_missing_customer_gets_404(self, client, db_session):
        headers = _admin_headers(db_session)
        assert client.get("/api/customers/9999/intelligence/workspace/", headers=headers).status_code == 404

    def test_user_without_customer_access_gets_404(self, client, db_session):
        _seed_customer(db_session, 1)
        _seed_customer(db_session, 2)
        headers = _non_admin_headers(db_session, customer_id=2)
        # 404-first: out-of-scope is the same 404 as a missing customer.
        assert client.get("/api/customers/1/intelligence/workspace/", headers=headers).status_code == 404

    def test_member_can_read_workspace(self, client, db_session):
        _seed_customer(db_session, 1)
        headers = _non_admin_headers(db_session, customer_id=1)
        r = client.get("/api/customers/1/intelligence/workspace/", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["customer_id"] == 1
        assert body["method"] == "deterministic_aggregation"
        assert body["account"]["name"] == "WS Test Customer 1"
        for section in ("technology_landscape", "knowledge", "sales_activity",
                        "assessment", "business_impact", "opportunities", "headline"):
            assert section in body

    def test_admin_can_read_workspace_with_data(self, client, db_session):
        _seed_customer(db_session, 1)
        _seed_tech(db_session, 1, name="Admin View Tech", category="software",
                   verification_state="verified")
        headers = _admin_headers(db_session)
        r = client.get("/api/customers/1/intelligence/workspace/", headers=headers)
        assert r.status_code == 200
        assert r.json()["technology_landscape"]["total"] == 1
        assert r.json()["headline"]["technologies_known"] == 1
