"""Phase 4 account-impact service — money-safety + provenance + honesty tests.

Deterministic (no LLM). Pins the directive §5 invariants:
  * separate named measures; total = assessment customer benefit (estimated)
  * service fees NOT annualized, NOT revenue, excluded with a reason
  * qualitative carries no money; pipeline not quantified (no recorded prob)
  * unknown != zero; coverage quantified/partial/not_quantified
  * cancelled/lost use cases excluded with a reason; decimal-safe rounding
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")


from backend.models.sales_evaluation import SalesEvaluation
from backend.models.sales_note import SalesNote
from backend.models.third_party_service import ThirdPartyService
from backend.models.use_case import Customer, UseCase
from backend.services import account_impact as ai

from tests.backend._shared import add_pipeline_batch


def _cust(db_session, name):
    c = Customer(name=name)
    db_session.add(c)
    db_session.flush()
    return c


def _uc(db_session, cust, **kw):
    uc = UseCase(title=kw.pop("title", "UC"), customer_id=cust.id,
                 status=kw.pop("status", "active"), **kw)
    db_session.add(uc)
    db_session.flush()
    return uc


def test_primary_reps_empty_scope_does_not_query(db_session):
    from sqlalchemy import event

    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", record)
    try:
        assert ai.primary_reps_for(db_session, []) == {}
        assert statements == []
    finally:
        event.remove(db_session.bind, "before_cursor_execute", record)


def test_benefit_total_is_assessment_savings_plus_revenue(db_session):
    c = _cust(db_session, "Benefit Co")
    _uc(db_session, c, title="A", estimated_savings=1000.0, estimated_revenue=500.0, status="active")
    _uc(db_session, c, title="B", estimated_savings=0.1, estimated_revenue=0.2, status="active")
    s = ai.compute_account_impact(db_session, c.id)
    m = s["measures"]["customer_benefit_assessment"]
    assert m["savings"] == 1000.1
    assert m["revenue"] == 500.2
    assert m["subtotal"] == 1500.3  # decimal-safe (not 1500.2999...)
    assert s["total_impact"]["value"] == 1500.3
    assert s["total_impact"]["perspective"] == "customer_benefit"
    assert s["total_impact"]["realization_basis"] == "estimated"
    assert s["coverage"] == "quantified"
    # provenance + as-of present
    assert s["as_of"] and s["calculation_version"] == ai.CALC_VERSION


def test_service_fees_excluded_and_not_annualized(db_session):
    c = _cust(db_session, "Svc Co")
    _uc(db_session, c, title="A", estimated_savings=100.0, status="active")
    svc = ThirdPartyService(customer_id=c.id, vendor_name="V", service_category="c",
                            description="d", engagement_status="active",
                            billing_model="t&m", fee_amount=999.0)
    db_session.add(svc)
    db_session.flush()
    s = ai.compute_account_impact(db_session, c.id)
    sc = s["measures"]["service_commitments"]
    assert sc["monthly_amount"] == 999.0
    assert sc["in_total"] is False
    assert sc["economic_perspective"] == "unclassified"
    # total must NOT include the service fee (100.0, not 1099.0)
    assert s["total_impact"]["value"] == 100.0
    assert "service_commitments" in s["total_impact"]["excluded_sources"]


def test_cancelled_use_case_excluded_with_reason(db_session):
    c = _cust(db_session, "Cancel Co")
    _uc(db_session, c, title="Good", estimated_savings=10.0, status="active")
    _uc(db_session, c, title="Gone", estimated_savings=90.0, status="cancelled")
    s = ai.compute_account_impact(db_session, c.id)
    assert s["total_impact"]["value"] == 10.0
    excl_titles = {e["title"] for e in s["exclusions"]}
    assert "Gone" in excl_titles
    assert s["measures"]["customer_benefit_assessment"]["excluded_use_cases"][0]["title"] == "Gone"


def test_no_data_is_not_quantified_not_zero(db_session):
    c = _cust(db_session, "Empty Co")
    s = ai.compute_account_impact(db_session, c.id)
    assert s["coverage"] == "not_quantified"
    assert s["total_impact"]["value"] is None  # unknown, not 0.0
    assert s["measures"]["pipeline"]["unweighted_estimate"] is None
    assert s["calculation_version"] == "account-impact/2"


def test_partial_coverage_when_only_services(db_session):
    c = _cust(db_session, "Partial Co")
    db_session.add(ThirdPartyService(customer_id=c.id, vendor_name="V", service_category="c",
                                     description="d", engagement_status="active",
                                     billing_model="fixed", fee_amount=50.0))
    db_session.flush()
    s = ai.compute_account_impact(db_session, c.id)
    assert s["coverage"] == "partial"
    assert s["total_impact"]["value"] is None
    assert s["measures"]["service_commitments"]["monthly_amount"] == 50.0


def test_qualitative_never_produces_money(db_session):
    c = _cust(db_session, "Qual Co")
    for cat in ("opportunity", "risk", "initiative"):
        db_session.add(SalesNote(customer_id=c.id, category=cat, title="t",
                                 content="x", verification_state="verified"))
    db_session.add(SalesEvaluation(customer_id=c.id, evaluation_name="E",
                                   growth_opportunities=["g1", "g2"], risk_factors=["r1"]))
    db_session.flush()
    s = ai.compute_account_impact(db_session, c.id)
    q = s["measures"]["qualitative_intelligence"]
    assert q["opportunities"] == 1 + 2  # 1 note opportunity + 2 eval
    assert q["risks"] == 1 + 1
    assert q["monetary"] is False
    assert q["in_total"] is False
    # still not quantified (no monetary benefit)
    assert s["coverage"] == "partial"
    assert s["total_impact"]["value"] is None


def test_pipeline_not_quantified(db_session):
    c = _cust(db_session, "Pipe Co")
    _uc(db_session, c, title="A", estimated_savings=5.0, status="active")
    s = ai.compute_account_impact(db_session, c.id)
    p = s["measures"]["pipeline"]
    assert p["status"] == "not_quantified"
    assert p["value"] is None
    assert p["in_total"] is False


def test_portfolio_rollup_dedupes_and_sums(db_session):
    c1 = _cust(db_session, "PF1")
    c2 = _cust(db_session, "PF2")
    c3 = _cust(db_session, "PF3")
    _uc(db_session, c1, title="a", estimated_savings=10.0, status="active")
    _uc(db_session, c2, title="b", estimated_savings=20.0, status="active")
    # c3 has no data
    pf = ai.compute_portfolio_impact(db_session, {c1.id, c2.id, c3.id, c1.id})  # c1 duped in input
    assert pf["customer_count"] == 3  # deduped
    assert pf["total_impact"]["value"] == 30.0
    assert pf["rollup"] == {"quantified": 2, "partial": 0, "not_quantified": 1}


def test_unweighted_estimate_matches_pipeline_without_changing_benefit(db_session, monkeypatch):
    from backend.services import pipeline_read_model
    from backend.services.intelligence_import_service import customer_pipeline

    customer = _cust(db_session, "Synthetic Estimate Account")
    _uc(db_session, customer, estimated_savings=0.1, estimated_revenue=0.2)
    before = ai.compute_account_impact(db_session, customer.id)
    batch = add_pipeline_batch(db_session, [(customer, [
        {"est_acv_usd": 123456.78, "est_tcv_usd": None, "forecast_category": "Commit"},
        {"est_acv_usd": None, "est_tcv_usd": 999999.99, "forecast_category": "Best Case"},
    ])])
    calls = []
    original = pipeline_read_model.pipeline_summary_for

    def read(db, customer_id):
        calls.append(customer_id)
        return original(db, customer_id)

    monkeypatch.setattr(pipeline_read_model, "pipeline_summary_for", read)
    after = ai.compute_account_impact(db_session, customer.id)
    assert calls == [customer.id]
    assert after["total_impact"]["value"] == before["total_impact"]["value"] == 0.3
    assert after["total_impact"] == before["total_impact"]
    assert after["measures"]["customer_benefit_assessment"] == before["measures"]["customer_benefit_assessment"]
    route_summary = customer_pipeline(db_session, customer.name)["summary"]
    measure = after["measures"]["pipeline"]
    assert measure == {
        "value": None, "currency": None, "status": "not_quantified", "in_total": False,
        "reason": "no explicitly recorded probability; weighted pipeline requires one, "
                  "not a guess or a forecast category",
        "unweighted_estimate": {
            "acv": route_summary["amounts"]["acv"]["total"],
            "tcv": route_summary["amounts"]["tcv"]["total"],
            "currency": "USD (source-labelled)",
            "coverage": {"acv": "partial", "tcv": "partial"},
            "lines": 2, "opportunity_count": 1,
            "snapshot": {
                "import_id": batch.id, "source_file": "synthetic-pipeline.csv",
                "imported_at": route_summary["source"]["imported_at"],
            },
        },
    }
    assert after["total_impact"]["excluded_reasons"]["pipeline"] == (
        "weighted pipeline requires an explicitly recorded probability (none recorded); "
        "the separate unweighted vendor estimate is reported in measures.pipeline.unweighted_estimate"
    )


def test_portfolio_pipeline_preserves_every_account_coverage_and_empty_scope(db_session, monkeypatch):
    from backend.services import pipeline_read_model

    accounts = [_cust(db_session, f"Synthetic Coverage {i}") for i in range(6)]
    add_pipeline_batch(db_session, [
        (accounts[0], [{"est_acv_usd": 0.1}, {"est_acv_usd": 0.2}]),
        (accounts[1], [{"est_acv_usd": 12.34}, {"est_acv_usd": None}]),
        (accounts[2], [{"est_acv_usd": 0.0}]),
        (accounts[3], [{"est_acv_usd": None}]),
        (accounts[5], [{"est_acv_usd": 999999}]),
    ])
    ids = [account.id for account in accounts[:5]]
    calls = []
    original = pipeline_read_model.pipeline_summaries_for

    def read(db, customer_ids):
        calls.append(list(customer_ids))
        return original(db, customer_ids)

    monkeypatch.setattr(pipeline_read_model, "pipeline_summaries_for", read)
    portfolio = ai.compute_portfolio_impact(db_session, [*ids, ids[0]])
    assert calls == [ids]
    assert portfolio["total_impact"]["value"] is None
    assert portfolio["customer_count"] == 5
    assert portfolio["pipeline"]["acv"] == {
        "total": 12.64, "lines": 6, "accounts_quantified": 1, "accounts_partial": 1,
        "accounts_recorded_zero": 1, "accounts_all_unknown": 1, "accounts_no_data": 1,
    }
    assert portfolio["pipeline"]["tcv"] == {
        "total": None, "lines": 6, "accounts_quantified": 0, "accounts_partial": 0,
        "accounts_recorded_zero": 0, "accounts_all_unknown": 4, "accounts_no_data": 1,
    }
    summaries = original(db_session, ids)
    calls.clear()
    reused = ai.compute_portfolio_impact(db_session, ids, pipeline_summaries=summaries)
    assert reused["pipeline"]["acv"] == portfolio["pipeline"]["acv"]
    assert calls == []
    empty = ai.compute_portfolio_impact(db_session, [])
    assert calls == [[]]
    assert empty["customer_count"] == 0
    for key in ("acv", "tcv"):
        assert empty["pipeline"][key] == {
            "total": None, "lines": 0, "accounts_quantified": 0, "accounts_partial": 0,
            "accounts_recorded_zero": 0, "accounts_all_unknown": 0, "accounts_no_data": 0,
        }
