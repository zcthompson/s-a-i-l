"""Sales persona registry + persona-driven evaluation tests (S-A-I-L P5).

Covers CHANGELOG 0.0.80 items 27-39:
- centralized deterministic persona registry (min 8 personas, extensible)
- persona persisted with the generated evaluation (historical context)
- source-context metadata / provenance on every evaluation
- persona-tailored sections (10 sections, each labeled by epistemic status)
- evidence traceability: recommendations cite evidence or are marked hypothesis
- missing knowledge surfaced as actionable discovery gaps (never fabricated)
- pre-generation preview endpoint (no persist)
- route auth (401/403/404), persona validation (422), persona filter

The engine is fully deterministic — no LLM calls in these tests.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from backend.models.customer_technology import CustomerTechnology
from backend.models.sales_evaluation import SalesEvaluation
from backend.models.sales_note import SalesNote
from backend.services.evaluation_engine import (
    create_sales_evaluation,
    preview_sales_evaluation,
)
from backend.services.sales_personas import (
    PERSONA_ORDER,
    PERSONAS,
    READINESS_DIMENSIONS,
    get_persona,
    list_personas,
    validate_persona,
)

from tests.backend.common import _admin_headers

SECTION_KEYS = [
    "account_snapshot",
    "relevant_environment",
    "business_technical_priorities",
    "observed_gaps",
    "growth_opportunities",
    "risks",
    "competitive_considerations",
    "recommended_solutions",
    "discovery_questions",
    "suggested_next_actions",
]


# ── helpers (repo conventions: test_sales_evaluations.py) ────────────────────


def _non_admin_headers(db_session) -> dict:
    """Non-admin user with NO CustomerUser row (403 pattern)."""
    from backend.auth import create_access_token, hash_password
    from backend.models.use_case import User

    member = User(
        username="member_p5_403",
        email="memberp5403@test.local",
        hashed_password=hash_password("member_p5_403"),
        display_name="Member P5 403",
        department="Sales",
        is_admin=0,
        approved=1,
        is_active=1,
    )
    db_session.add(member)
    db_session.commit()
    return {
        "Authorization": f"Bearer {create_access_token({'sub': 'member_p5_403', 'is_admin': False})}"
    }


@pytest.fixture()
def customer_1(db_session):
    from backend.models.use_case import Customer

    c = Customer(name="Persona Eval Test Customer", description="p5 deterministic test")
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)
    return c


def _seed_context(
    db_session,
    customer_id: int,
    eol_tech: bool = True,
    competitive_note: bool = True,
    stale_note: bool = False,
) -> None:
    """Seed scored UC + knowledge + tech (+ optional competitive/stale note)."""
    from backend.models.customer_knowledge import CustomerKnowledge as CKModel
    from backend.models.use_case import UseCase

    uc = UseCase(
        title="P5 Use Case",
        description="persona eval test",
        customer_id=customer_id,
        overall_score=72.5,
        scores={"technical_feasibility": 80.0, "financial_viability": 65.0},
    )
    db_session.add(uc)

    kw = CKModel(
        customer_id=customer_id,
        knowledge_type="software_inventory",
        file_name="p5_sw.csv",
        file_data=b"software,version\nOracle VM,3.4.2\n",
        uploaded_at=datetime.now(UTC),
        extracted_text="Oracle VM 3.4.2",
    )
    db_session.add(kw)

    techs = [
        CustomerTechnology(
            customer_id=customer_id,
            name="PowerEdge R730",
            vendor="Dell",
            category="hardware",
            lifecycle_state="eol" if eol_tech else "current",
            support_state="no_support" if eol_tech else "under_support",
            business_criticality="critical",
            verification_state="verified",
        ),
        CustomerTechnology(
            customer_id=customer_id,
            name="VMware vSphere 7",
            vendor="VMware",
            category="virtualization",
            lifecycle_state="previous_generation",
            support_state="under_support",
            business_criticality="high",
            verification_state="verified",
        ),
    ]
    db_session.add_all(techs)

    if competitive_note:
        note = SalesNote(
            customer_id=customer_id,
            author="sales.test",
            source="discovery call",
            note_date=date.today() - timedelta(days=5),
            category="competitive",
            title="Competitor mentioned: Nutanix",
            content="Customer mentioned Nutanix is in the shortlist for the refresh.",
            verification_state="verified",
        )
        db_session.add(note)
    if stale_note:
        stale = SalesNote(
            customer_id=customer_id,
            author="sales.test",
            note_date=date.today() - timedelta(days=300),
            category="meeting",
            title="Old meeting",
            content="Q1 discovery meeting notes.",
            verification_state="verified",
        )
        db_session.add(stale)

    db_session.commit()


# ── registry ─────────────────────────────────────────────────────────────────


class TestPersonaRegistry:
    def test_registry_has_minimum_personas(self):
        """v2 item 28: the 8 minimum personas, extensible registry."""
        ids = {p["id"] for p in list_personas()}
        assert ids == {
            "executive",
            "cio_cto",
            "infrastructure",
            "security",
            "data_ai",
            "application",
            "it_operations",
            "architect",
        }
        assert len(list_personas()) == len(PERSONA_ORDER) == 8

    def test_registry_fields_complete(self):
        for p in list_personas():
            assert p["id"] in PERSONAS
            assert p["label"] and p["description"]
            assert p["technical_depth"] in {"low", "medium", "high"}
            assert p["business_framing"] and p["risk_framing"]
            assert set(p["focus_dimensions"]) <= set(READINESS_DIMENSIONS)
            assert p["concerns"], f"{p['id']} needs concerns"
            assert p["question_base"], f"{p['id']} needs base questions"
            assert p["priority_angles"] and p["next_action_angles"]

    def test_get_persona_and_validate(self):
        assert get_persona("security") is not None
        assert get_persona("nope") is None
        assert get_persona(None) is None
        assert validate_persona(None) is None
        assert validate_persona("security") is None
        err = validate_persona("bogus")
        assert err is not None and "security" in err  # error lists valid personas


# ── engine: persona, provenance, sections ────────────────────────────────────


class TestPersonaEngine:
    def test_persona_persisted_and_sections_built(self, db_session, customer_1):
        _seed_context(db_session, customer_1.id)
        ev = create_sales_evaluation(
            db_session, customer_1.id, "Persona Eval", persona_id="security"
        )
        assert ev.persona == "security"
        assert isinstance(ev.persona_sections, dict)
        assert set(ev.persona_sections["sections"].keys()) == set(SECTION_KEYS)
        # re-read from DB (persistence)
        reloaded = (
            db_session.query(SalesEvaluation)
            .filter(SalesEvaluation.id == ev.id)
            .first()
        )
        assert reloaded.persona == "security"
        assert reloaded.persona_sections["persona"] == "security"

    def test_generic_eval_no_sections_but_has_provenance(self, db_session, customer_1):
        _seed_context(db_session, customer_1.id)
        ev = create_sales_evaluation(db_session, customer_1.id, "Generic Eval")
        assert ev.persona is None
        assert ev.persona_sections is None
        # provenance is always set (v2 item 39)
        assert isinstance(ev.source_context, dict)
        assert ev.source_context["method"] == "deterministic_engine"
        assert ev.source_context["persona"] is None

    def test_source_context_counts_match_seeded_data(self, db_session, customer_1):
        _seed_context(db_session, customer_1.id, eol_tech=True)
        ev = create_sales_evaluation(
            db_session, customer_1.id, "Provenance Eval", persona_id="infrastructure"
        )
        src = ev.source_context
        assert src["sources"]["use_cases_total"] == 1
        assert src["sources"]["use_cases_scored"] == 1
        assert src["sources"]["technology_items"] == 2
        assert src["sources"]["sales_notes"] == 1
        assert src["sources"]["competitive_notes"] == 1
        assert src["sources"]["knowledge_entries"] == 1
        assert src["indicators"]["eol_tech_count"] == 1
        assert "PowerEdge R730" in src["indicators"]["critical_tech_at_risk"]
        assert src["persona"] == "infrastructure"
        assert "provenance_note" in src

    def test_persona_tailoring_materially_differs(self, db_session, customer_1):
        """v2 item 29: selection changes emphasis/framing/questions/actions."""
        _seed_context(db_session, customer_1.id)
        exec_ev = create_sales_evaluation(
            db_session, customer_1.id, "Exec Eval", persona_id="executive"
        )
        sec_ev = create_sales_evaluation(
            db_session, customer_1.id, "Sec Eval", persona_id="security"
        )
        a = exec_ev.persona_sections["sections"]
        b = sec_ev.persona_sections["sections"]
        assert (
            a["business_technical_priorities"]["content"]["framing"]
            != b["business_technical_priorities"]["content"]["framing"]
        )
        assert (
            a["discovery_questions"]["content"]["persona_questions"]
            != b["discovery_questions"]["content"]["persona_questions"]
        )
        assert (
            a["suggested_next_actions"]["content"]["persona_angles"]
            != b["suggested_next_actions"]["content"]["persona_angles"]
        )
        # persona identity is recorded inside the section set
        assert exec_ev.persona_sections["persona"] == "executive"
        assert sec_ev.persona_sections["persona"] == "security"

    def test_all_sections_labeled_with_epistemic_status(self, db_session, customer_1):
        _seed_context(db_session, customer_1.id)
        ev = create_sales_evaluation(
            db_session, customer_1.id, "Label Eval", persona_id="cio_cto"
        )
        for key in SECTION_KEYS:
            section = ev.persona_sections["sections"][key]
            assert "label" in section, f"{key} missing epistemic label"
            assert "content" in section

    def test_recommendations_evidence_or_hypothesis(self, db_session, customer_1):
        """v2 item 34: no generic fluff — each recommendation cites evidence
        or is explicitly labeled a hypothesis requiring discovery."""
        _seed_context(db_session, customer_1.id)
        ev = create_sales_evaluation(
            db_session, customer_1.id, "Recs Eval", persona_id="architect"
        )
        recs = ev.persona_sections["sections"]["recommended_solutions"]["content"]
        assert recs, "expected at least one recommendation"
        for r in recs:
            assert isinstance(r["evidence"], list)
            if not r["evidence"]:
                assert r["hypothesis"] is True
            else:
                assert r["hypothesis"] is False

    def test_competitive_considerations_evidence_based(self, db_session, customer_1):
        _seed_context(db_session, customer_1.id, competitive_note=True)
        ev = create_sales_evaluation(
            db_session, customer_1.id, "Comp Eval", persona_id="executive"
        )
        comp = ev.persona_sections["sections"]["competitive_considerations"]
        assert "evidence-based" in comp["label"]
        notes = comp["content"]["notes"]
        assert len(notes) == 1
        assert "Nutanix" in notes[0]["title"]
        assert notes[0]["verification_state"] == "verified"

    def test_competitive_missing_is_discovery_not_fabrication(self, db_session, customer_1):
        _seed_context(db_session, customer_1.id, competitive_note=False)
        ev = create_sales_evaluation(
            db_session, customer_1.id, "NoComp Eval", persona_id="executive"
        )
        comp = ev.persona_sections["sections"]["competitive_considerations"]
        assert "discovery needed" in comp["label"]
        assert comp["content"]["recorded"] is False
        assert "action" in comp["content"]

    def test_discovery_gaps_for_missing_knowledge(self, db_session, customer_1):
        """v2 item 35: missing knowledge → actionable discovery gaps."""
        # No seeding at all — bare customer.
        ev = create_sales_evaluation(
            db_session, customer_1.id, "Empty Eval", persona_id="executive"
        )
        areas = {d["area"] for d in ev.persona_sections["discovery_gaps"]}
        assert "technology_inventory" in areas
        assert "sales_notes" in areas
        assert "customer_knowledge" in areas
        # every gap carries an actionable action
        for d in ev.persona_sections["discovery_gaps"]:
            assert d["action"]

    def test_evidence_grounded_questions(self, db_session, customer_1):
        # competitive_note=False so the 300-day note is the LATEST note →
        # notes_stale=True and the freshness question fires.
        _seed_context(
            db_session,
            customer_1.id,
            eol_tech=True,
            competitive_note=False,
            stale_note=True,
        )
        ev = create_sales_evaluation(
            db_session, customer_1.id, "Q Eval", persona_id="infrastructure"
        )
        q = ev.persona_sections["sections"]["discovery_questions"]["content"][
            "evidence_grounded_questions"
        ]
        assert any("PowerEdge R730" in x for x in q)  # at-risk item question
        assert any("end-of-life" in x for x in q)  # EOL count question
        assert any("300 days old" in x for x in q)  # stale note question


# ── preview ───────────────────────────────────────────────────────────────────


class TestPreview:
    def test_preview_structure_and_no_persist(self, db_session, customer_1):
        _seed_context(db_session, customer_1.id)
        before = (
            db_session.query(SalesEvaluation)
            .filter(SalesEvaluation.customer_id == customer_1.id)
            .count()
        )
        prev = preview_sales_evaluation(db_session, customer_1.id, "cio_cto")
        after = (
            db_session.query(SalesEvaluation)
            .filter(SalesEvaluation.customer_id == customer_1.id)
            .count()
        )
        assert before == after  # preview persists nothing
        assert prev["customer"]["id"] == customer_1.id
        assert prev["persona"]["id"] == "cio_cto"
        assert prev["available_intelligence"]["technology_items"] == 2
        assert prev["available_intelligence"]["use_cases"] == {"total": 1, "scored": 1}
        assert prev["available_intelligence"]["eol_tech_count"] == 1
        assert set(prev["sections"].keys()) == set(SECTION_KEYS)
        assert "deterministic" in prev["generation_intent"].lower()
        assert prev["source_context"]["persona"] == "cio_cto"

    def test_preview_generic_without_persona(self, db_session, customer_1):
        prev = preview_sales_evaluation(db_session, customer_1.id, None)
        assert prev["persona"]["id"] is None
        assert set(prev["sections"].keys()) == set(SECTION_KEYS)

    def test_preview_unknown_customer_raises(self, db_session):
        with pytest.raises(ValueError):
            preview_sales_evaluation(db_session, 999999, "security")


# ── routes ────────────────────────────────────────────────────────────────────


class TestPersonaRoutes:
    def test_personas_endpoint_auth_and_list(self, client, db_session):
        assert client.get("/api/sales-evaluations/personas/").status_code == 401
        r = client.get(
            "/api/sales-evaluations/personas/", headers=_admin_headers(db_session)
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 8
        assert {"id", "label", "description"} <= set(data[0].keys())

    def test_preview_route_auth(self, client, db_session, customer_1):
        body = {"customer_id": customer_1.id, "persona": "security"}
        assert client.post("/api/sales-evaluations/preview/", json=body).status_code == 401
        r = client.post(
            "/api/sales-evaluations/preview/",
            json=body,
            headers=_non_admin_headers(db_session),
        )
        # 404-first (R4/Q7): out of scope == missing customer.
        assert r.status_code == 404
        r = client.post(
            "/api/sales-evaluations/preview/",
            json=body,
            headers=_admin_headers(db_session),
        )
        assert r.status_code == 200
        assert r.json()["persona"]["id"] == "security"

    def test_preview_route_invalid_persona_422(self, client, db_session, customer_1):
        r = client.post(
            "/api/sales-evaluations/preview/",
            json={"customer_id": customer_1.id, "persona": "bogus"},
            headers=_admin_headers(db_session),
        )
        assert r.status_code == 422

    def test_preview_route_missing_customer_404(self, client, db_session):
        r = client.post(
            "/api/sales-evaluations/preview/",
            json={"customer_id": 999999, "persona": None},
            headers=_admin_headers(db_session),
        )
        assert r.status_code == 404

    def test_create_with_persona_persists_and_validates(
        self, client, db_session, customer_1
    ):
        bad = client.post(
            f"/api/sales-evaluations/?customer_id={customer_1.id}",
            json={"evaluation_name": "Bad Persona", "persona": "bogus"},
            headers=_admin_headers(db_session),
        )
        assert bad.status_code == 422

        r = client.post(
            f"/api/sales-evaluations/?customer_id={customer_1.id}",
            json={"evaluation_name": "Persona Route Eval", "persona": "data_ai"},
            headers=_admin_headers(db_session),
        )
        assert r.status_code == 200
        assert r.json()["persona"] == "data_ai"
        assert r.json()["persona_sections"] is not None
        assert r.json()["source_context"]["persona"] == "data_ai"

    def test_list_persona_filter(self, client, db_session, customer_1):
        for persona in ("security", "executive"):
            r = client.post(
                f"/api/sales-evaluations/?customer_id={customer_1.id}",
                json={"evaluation_name": f"Filter {persona}", "persona": persona},
                headers=_admin_headers(db_session),
            )
            assert r.status_code == 200

        r = client.get(
            f"/api/sales-evaluations/?customer_id={customer_1.id}&persona=security",
            headers=_admin_headers(db_session),
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["persona"] == "security"
        assert data[0]["evaluation_name"] == "Filter security"
