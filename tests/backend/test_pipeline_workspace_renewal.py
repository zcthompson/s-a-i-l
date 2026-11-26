"""workspace renewal attention: urgency selection, evidence, legacy paths."""

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta

import pytest
from backend.models.use_case import Customer
from backend.services import customer_intelligence as intelligence
from backend.services import pipeline_read_model as pipeline

from tests.backend._shared import add_pipeline_batch
from tests.backend.test_account_workspace import (
    _seed_evaluation,
    _seed_note,
    _seed_tech,
    _seed_uc,
)

REFERENCE = date(2026, 10, 27)


def _attention(**buckets):
    return {
        "snapshot": {"import_id": 2, "imported_at": "2026-10-25T10:00:00Z"},
        "buckets": {bucket: buckets.get(bucket, []) for bucket in (
            "overdue", "within_30", "within_60", "within_90", "within_180", "unknown_date",
        )},
    }


def _card(number="123", days=20, **extra):
    return {
        "opportunity_number": number, "opportunity_name": None,
        "renewal_date": (REFERENCE + timedelta(days=days)).isoformat() if days is not None else None,
        "days": days, "lines": 2, "est_acv": {"total": 5000.0, "coverage": "quantified"},
        "conflicting_end_dates": [], "original_contract_end": "2025-11-15", **extra,
    }


@pytest.mark.parametrize(("bucket", "days", "severity"), [
    ("overdue", -26, "high"), ("within_30", 0, "high"),
    ("within_30", 20, "high"), ("within_60", 31, "medium"),
    ("within_90", 61, "medium"), ("within_180", 91, "low"),
    ("unknown_date", None, "medium"),
])
def test_workspace_renewal_severity_titles_and_source_evidence(bucket, days, severity):
    card = intelligence._renewal_opportunity_cards(_attention(**{bucket: [_card(days=days)]}))[0]
    assert card["severity"] == severity
    assert card["id"] == "renewal-attention-123" and card["type"] == "renewal_attention"
    assert card["evidence"] == {
        "source": "partner_pipeline", "source_id": 2, "source_name": "123",
    }
    if days is None:
        assert card["title"] == "Reported renewal — 123: no current contract end date recorded"
        assert "current contract end date not recorded" in card["detail"]
    elif days < 0:
        assert card["title"] == "Renewal — 123: current contract ended 2026-10-01 (overdue)"
    elif days == 0:
        assert card["title"] == "Renewal — 123: current contract ends today"
    else:
        assert card["title"] == f"Renewal — 123: current contract ends in {days} days"
    assert "snapshot import #2, imported 2026-10-25" in card["detail"]
    assert "2 lines; est. ACV $5,000.00 (quantified)." in card["detail"]
    assert "Original end 2025-11-15 (historical)." in card["detail"]
    assert all(word not in card["detail"].lower() for word in ("churn", "loss", "completion"))


def test_workspace_renewal_detail_exact_example_conflicts_and_unknown_exposure():
    card = intelligence._renewal_opportunity_cards(_attention(within_30=[_card()]))[0]
    assert card["detail"] == (
        "Vendor-reported current contract end 2026-11-16 (snapshot import #2, imported "
        "2026-10-25). 2 lines; est. ACV $5,000.00 (quantified). "
        "Original end 2025-11-15 (historical)."
    )
    card = intelligence._renewal_opportunity_cards(_attention(within_30=[_card(
        opportunity_name=" Named renewal ", est_acv={"total": None, "coverage": "all_unknown"},
        conflicting_end_dates=["2026-11-16", "2026-12-31"], original_contract_end=None,
    )]))[0]
    assert card["title"] == "Renewal — Named renewal (123): current contract ends in 20 days"
    assert "est. ACV not recorded" in card["detail"]
    assert "lines disagree on the end date: 2026-11-16, 2026-12-31." in card["detail"]
    assert "Original end" not in card["detail"]


def test_workspace_renewal_candidates_urgency_order_and_five_card_cap():
    attention = _attention(
        overdue=[_card("later", -1), _card("first-b", -10), _card("first-a", -10)],
        within_30=[_card("soon", 1)], within_60=[_card("sixty", 31)],
        within_90=[_card("ninety", 61)], within_180=[_card("far", 91)],
        unknown_date=[_card("unknown", None)],
    )
    original = deepcopy(attention)
    cards = intelligence._renewal_opportunity_cards(attention)
    assert [card["evidence"]["source_name"] for card in cards] == [
        "first-a", "first-b", "later", "soon", "sixty",
    ]
    assert len(cards) == intelligence.MAX_RENEWAL_CARDS == 5
    assert attention == original
    attention["buckets"]["overdue"] = []
    attention["buckets"]["within_30"] = []
    assert [card["evidence"]["source_name"] for card in
            intelligence._renewal_opportunity_cards(attention)] == ["sixty", "ninety", "far", "unknown"]


def test_workspace_legacy_five_card_types_unchanged_and_total_cap_applies_after(db_session, monkeypatch):
    monkeypatch.setattr(intelligence, "_utcnow_naive", lambda: datetime(2026, 10, 27, 12))
    customer = Customer(name="Synthetic legacy workspace")
    db_session.add(customer)
    db_session.flush()
    cid = customer.id
    _seed_tech(db_session, cid, name="Old technology", category="software", lifecycle_state="eol",
               support_state="no_support", business_criticality="critical")
    _seed_evaluation(db_session, cid, risk_factors=[{"category": "risk", "description": "Observed"}])
    _seed_uc(db_session, cid, overall_score=80)
    _seed_note(db_session, cid, title="Follow up", content="Synthetic follow-up evidence",
               category="risk", note_date=REFERENCE)
    tech = intelligence._technology_landscape_section(db_session, cid)
    knowledge = intelligence._knowledge_summary_section(db_session, cid)
    activity = intelligence._sales_activity_section(db_session, cid)
    evaluation = intelligence._latest_evaluation(db_session, cid)
    # Ensure all five legacy families are present independently of wall-clock staleness.
    tech["unverified_pct"] = 30
    args = (db_session, cid, tech, knowledge, activity, evaluation)
    before = intelligence._opportunities_section(*args)
    assert {card["type"] for card in before} == {
        "lifecycle_risk", "observed_gap", "growth_opportunity", "discovery_needed", "follow_up",
    }
    assert intelligence._opportunities_section(*args, renewal_cards=None) == before
    assert intelligence._opportunities_section(*args, renewal_cards=[]) == before
    renewals = intelligence._renewal_opportunity_cards(_attention(overdue=[_card()]))
    after = intelligence._opportunities_section(*args, renewal_cards=renewals)
    assert [card for card in after if card["type"] != "renewal_attention"] == before
    # Competing high-severity findings consume the overall cap after selection.
    evaluation["risk_factors"] = [{"category": f"risk-{i}", "description": "Observed"} for i in range(5)]
    tech["critical_tech_at_risk"] *= 5
    pooled = intelligence._opportunities_section(*args, renewal_cards=renewals * 5)
    assert len(pooled) == intelligence.MAX_OPPORTUNITY_CARDS == 12
    assert pooled == sorted(pooled, key=lambda card: (
        intelligence._SEVERITY_RANK[card["severity"]], card["type"], card["id"],
    ))


def test_workspace_reads_selected_snapshot_and_graph_shows_renewal_attention(db_session, monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 27, 12, tzinfo=UTC)

    monkeypatch.setattr(pipeline, "datetime", FixedDatetime)
    customer = Customer(name="Synthetic renewal workspace")
    db_session.add(customer)
    db_session.flush()
    cid = customer.id
    before = intelligence.get_account_workspace(db_session, cid)
    assert not any(card["type"] == "renewal_attention" for card in before["opportunities"])
    batch = add_pipeline_batch(db_session, [(customer, [
        {"opportunity_number": "WORK-1", "current_contract_end_date": REFERENCE,
         "est_acv_usd": None},
    ])])
    after = intelligence.get_account_workspace(db_session, cid)
    renewal_cards = [card for card in after["opportunities"] if card["type"] == "renewal_attention"]
    assert len(renewal_cards) == 1
    assert renewal_cards[0]["title"] == "Renewal — WORK-1: current contract ends today"
    assert renewal_cards[0]["evidence"] == {
        "source": "partner_pipeline", "source_id": batch.id, "source_name": "WORK-1",
    }
    assert "est. ACV not recorded" in renewal_cards[0]["detail"]
    assert [card for card in after["opportunities"] if card["type"] != "renewal_attention"] == before["opportunities"]
    for key in before.keys() - {"generated_at", "opportunities", "headline"}:
        assert after[key] == before[key]
    assert after["headline"]["open_opportunities_count"] == before["headline"]["open_opportunities_count"] + 1

    # The graph uses the panel synthesis, so the renewal card appears once,
    # as an Opportunities node with the panel's title and pipeline evidence.
    graph = intelligence.build_customer_intelligence_graph(db_session, cid)
    renewal_nodes = [n for n in graph["nodes"] if n["status"] == "renewal_attention"]
    assert len(renewal_nodes) == 1
    assert renewal_nodes[0]["type"] == "opportunity" and renewal_nodes[0]["category"] == "opportunity"
    assert renewal_nodes[0]["label"] == renewal_cards[0]["title"]
    assert renewal_nodes[0]["metadata"]["evidence"] == renewal_cards[0]["evidence"]
    assert {n["category"] for n in graph["nodes"]} <= {
        "customer", "domain", "technology", "use_case", "sales_note", "assessment", "assessment_generic",
        "sales_evaluation", "risk", "opportunity"}
