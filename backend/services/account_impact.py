"""Account-impact service (shift-to-global-customer-management, phase 4).

Replaces the legacy use-case-only ``total_impact = savings + revenue`` headline
with an EXPLAINABLE, money-safe account-impact summary. Per the directive §5:

  * **Separately named measures** — customer benefit (assessment-derived),
    service commitments/cost, qualitative intelligence, and pipeline. NEVER
    one unlabeled number that mixes seller revenue, customer savings,
    third-party spend, pipeline, and realized money.
  * **A monetary Total Impact identifies whose impact it is, the currency,
    the period, and the realization basis.** The safe default total is the
    sum of eligible, non-overlapping benefits on a single perspective/currency/
    period/realization basis. Because the only recorded monetary *benefit*
    source (use-case savings/revenue) is an **estimated** customer benefit, the
    total is that figure with ``realization_basis='estimated'`` and
    ``perspective='customer_benefit'``.
  * **Service fees are NOT annualized, NOT treated as contract value/revenue.**
    ``fee_amount`` stays its monthly 30-day figure and is reported as a service
    commitment *pending economic classification* — excluded from the total
    (with a stated reason) because it has no recorded period basis or economic
    perspective to combine with the estimated benefits.
  * **Qualitative intelligence (notes/evaluations) never produces authoritative
    money from prose.** It is reported as counts + verification states only.
  * **Weighted pipeline is "not quantified"** without an explicitly recorded
    probability. Unweighted source-labelled line estimates are separate.
  * **Unknown is distinct from zero.** Missing inputs are listed as exclusions
    with reasons; the summary reports ``coverage`` = quantified / partial /
    not_quantified rather than presenting incomplete totals as complete.
  * **Decimal-safe** arithmetic (Decimal over str to avoid float drift),
    rounded at the JSON boundary.
  * **Provenance + as-of** so historical values stay explainable
    (calculation_version + as_of).

This is a PURE, additive service over the existing schema. It deliberately
does NOT change the global/assessment KPIs — those stay assessment-labeled.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.models.sales_evaluation import SalesEvaluation
from backend.models.sales_note import SalesNote
from backend.models.third_party_service import ThirdPartyService
from backend.models.use_case import CustomerUser, UseCase, User
from backend.services import pipeline_read_model

CALC_VERSION = "account-impact/2"

# A use case is an *eligible benefit* only if it is not explicitly cancelled/
# lost and has at least one recorded amount. Statuses that mean "no benefit"
# are excluded and reported with a reason.
_BENEFIT_INELIGIBLE_STATUS = {"cancelled", "lost", "dropped"}


def primary_reps_for(db: Session, customer_ids: list[int]) -> dict[int, str | None]:
    """Resolve display owners in one batch, matching build_customer_response."""
    owners_by_customer: dict[int, list[User]] = {cid: [] for cid in customer_ids}
    if not owners_by_customer:
        return {}
    owners = (
        db.query(CustomerUser.customer_id, User)
        .select_from(CustomerUser)
        .join(User, CustomerUser.user_id == User.id)
        .filter(CustomerUser.customer_id.in_(owners_by_customer), CustomerUser.role == "owner")
        .order_by(CustomerUser.customer_id, CustomerUser.id)
        .all()
    )
    for cid, owner in owners:
        owners_by_customer[cid].append(owner)
    result = {}
    for cid, customer_owners in owners_by_customer.items():
        rep_owners = [owner for owner in customer_owners if owner.sales_role == "rep"]
        owner = rep_owners[0] if len(rep_owners) == 1 else (
            customer_owners[0] if customer_owners else None
        )
        result[cid] = (owner.display_name or owner.username) if owner is not None else None
    return result


def _d(value: float | None) -> Decimal:
    """Decimal from a possibly-None float, without float drift."""
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


def _r(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def compute_account_impact(db: Session, customer_id: int) -> dict:
    """Build the explainable account-impact summary for one customer.

    Returns a dict (JSON-serializable). See the module docstring for the
    contract and money-safety rules.
    """
    return _compute_account_impact(
        db, customer_id, pipeline_read_model.pipeline_summary_for(db, customer_id),
    )


def _compute_account_impact(db: Session, customer_id: int, pipeline_summary: dict) -> dict:
    """Same benefit calculation, with an already-read pipeline snapshot.

    Portfolio callers reuse their authorized batch instead of querying pipeline
    once per customer. The public single-account signature stays unchanged.
    """
    exclusions: list[dict] = []

    # ── 1. Customer benefit — assessment-derived (use-case savings + revenue) ─
    use_cases = (
        db.query(UseCase).filter(UseCase.customer_id == customer_id).all()
    )
    savings_total = Decimal(0)
    revenue_total = Decimal(0)
    eligible_count = 0
    excluded_uc = []
    for uc in use_cases:
        s = _d(uc.estimated_savings)
        r = _d(uc.estimated_revenue)
        has_amount = bool(uc.estimated_savings is not None or uc.estimated_revenue is not None)
        if not has_amount:
            continue  # no amount recorded -> not a (positive) contribution; unknown, not zero
        status = (uc.status or "").strip().lower()
        if status in _BENEFIT_INELIGIBLE_STATUS:
            excluded_uc.append({"title": uc.title, "status": status,
                                "reason": f"use case status '{status}' is not an active benefit"})
            exclusions.append({"source": "use_case", "id": uc.id, "title": uc.title,
                               "reason": f"excluded: status '{status}'"})
            continue
        savings_total += s
        revenue_total += r
        eligible_count += 1

    benefit_subtotal = savings_total + revenue_total

    # ── 2. Service commitments/cost — third-party fee_amount (monthly, as-is) ─
    services = (
        db.query(ThirdPartyService).filter(ThirdPartyService.customer_id == customer_id).all()
    )
    monthly_commit_total = Decimal(0)
    svc_count = 0
    billing_models = set()
    for svc in services:
        if svc.fee_amount is None:
            continue  # NULL until known -> unknown, distinct from zero
        monthly_commit_total += _d(svc.fee_amount)
        svc_count += 1
        if svc.billing_model:
            billing_models.add(svc.billing_model)

    # ── 3. Qualitative intelligence — sales notes + evaluations (NO money) ─
    note_categories = (
        db.query(SalesNote.category, SalesNote.verification_state)
        .filter(SalesNote.customer_id == customer_id).all()
    )
    opportunities = sum(1 for c, _ in note_categories if c == "opportunity")
    risks = sum(1 for c, _ in note_categories if c == "risk")
    initiatives = sum(1 for c, _ in note_categories if c == "initiative")
    notes_verified = sum(1 for _, v in note_categories if v == "verified")
    notes_inferred = sum(1 for _, v in note_categories if v in ("inferred", "unverified"))
    n_notes = len(note_categories)

    evals = (
        db.query(SalesEvaluation).filter(SalesEvaluation.customer_id == customer_id).all()
    )
    eval_opportunities = 0
    eval_risks = 0
    for e in evals:
        go = e.growth_opportunities or []
        rf = e.risk_factors or []
        if isinstance(go, list):
            eval_opportunities += len(go)
        if isinstance(rf, list):
            eval_risks += len(rf)

    # ── 4. Pipeline — separate unweighted estimates; no recorded probability ─
    pipeline_value: float | None = None
    pipeline_currency: str | None = None
    pipeline_status = "not_quantified"
    pipeline_reason = (
        "no explicitly recorded probability; weighted pipeline requires one, "
        "not a guess or a forecast category"
    )
    pipeline_excluded_reason = (
        "weighted pipeline requires an explicitly recorded probability (none recorded); "
        "the separate unweighted vendor estimate is reported in "
        "measures.pipeline.unweighted_estimate"
    )
    unweighted_estimate = None
    if pipeline_summary["source"] is not None:
        amounts = pipeline_summary["amounts"]
        source = pipeline_summary["source"]
        unweighted_estimate = {
            "acv": amounts["acv"]["total"],
            "tcv": amounts["tcv"]["total"],
            "currency": "USD (source-labelled)",
            "coverage": {key: amount["coverage"] for key, amount in amounts.items()},
            "lines": pipeline_summary["grain"]["line_count"],
            "opportunity_count": pipeline_summary["grain"]["opportunity_count"],
            "snapshot": {key: source[key] for key in ("import_id", "source_file", "imported_at")},
        }

    # ── Total Impact (monetary, safe default) ─────────────────────────────────
    # Single perspective + realization basis + (no recorded currency/period).
    # = eligible assessment customer benefit. Service commitments are EXCLUDED
    # (different/undetermined basis); qualitative + pipeline carry no money.
    #
    # The monetary total is reported ONLY when a comparable total can be
    # established (at least one eligible benefit). Otherwise it is None
    # (unknown — distinct from zero), per directive §5: "display 'Not
    # quantified' or 'Partial' with the missing inputs rather than inventing
    # assumptions."
    total_value = _r(benefit_subtotal) if eligible_count > 0 else None
    total_perspective = "customer_benefit"
    total_basis = "estimated"
    total_currency: str | None = None  # no source records a currency
    total_period: str | None = None

    # Coverage: quantified when there's at least one eligible benefit; partial
    # when there's service-commitment or qualitative info but no benefit total;
    # not_quantified when nothing monetary is recorded at all.
    if eligible_count > 0:
        coverage = "quantified"
    elif svc_count > 0 or n_notes > 0 or evals:
        coverage = "partial"
    else:
        coverage = "not_quantified"

    service_excluded_reason = (
        "monthly 30-day fee figure without a recorded period basis or economic "
        "perspective; not annualized and not treated as contract value/revenue"
    )

    return {
        "customer_id": customer_id,
        "as_of": _now_iso(),
        "calculation_version": CALC_VERSION,
        "coverage": coverage,
        "currency_note": ("no monetary source records a currency; amounts are a "
                          "single unrecorded unit and must not be combined across "
                          "currencies without a defined conversion basis"),
        "total_impact": {
            "value": total_value if coverage != "not_quantified" else None,
            "currency": total_currency,
            "perspective": total_perspective,
            "realization_basis": total_basis,
            "period": total_period,
            "included_sources": ["customer_benefit_assessment"],
            "excluded_sources": ["service_commitments", "qualitative_intelligence", "pipeline"],
            "excluded_reasons": {
                "service_commitments": service_excluded_reason,
                "qualitative_intelligence": "qualitative observations; no authoritative money derived from prose",
                "pipeline": pipeline_excluded_reason,
            },
        },
        "measures": {
            "customer_benefit_assessment": {
                "savings": _r(savings_total),
                "revenue": _r(revenue_total),
                "subtotal": _r(benefit_subtotal),
                "use_case_count": eligible_count,
                "realization_basis": "estimated",
                "currency": None,
                "in_total": True,
                "excluded_use_cases": excluded_uc,
                "label": "Assessment-derived customer benefit (supporting source — estimated, not booked)",
            },
            "service_commitments": {
                "monthly_amount": _r(monthly_commit_total),
                "billing_basis": "30-day (monthly); as recorded, not annualized",
                "billing_models": sorted(billing_models),
                "service_count": svc_count,
                "economic_perspective": "unclassified",
                "currency": None,
                "in_total": False,
                "excluded_reason": service_excluded_reason,
                "label": "Third-party service spend/commitment (pending economic classification)",
            },
            "qualitative_intelligence": {
                "opportunities": opportunities + eval_opportunities,
                "risks": risks + eval_risks,
                "initiatives": initiatives,
                "note_count": n_notes,
                "evaluation_count": len(evals),
                "verified": notes_verified,
                "inferred_or_unverified": notes_inferred,
                "monetary": False,
                "in_total": False,
                "label": "Evidence-backed observations (inferred/unverified; no money attributed)",
            },
            "pipeline": {
                "value": pipeline_value,
                "currency": pipeline_currency,
                "status": pipeline_status,
                "reason": pipeline_reason,
                "in_total": False,
                "unweighted_estimate": unweighted_estimate,
            },
        },
        "exclusions": exclusions,
    }


def compute_portfolio_impact(db: Session, customer_ids, *, pipeline_summaries=None) -> dict:
    """Portfolio-level roll-up over an AUTHORIZED set of customers.

    Only sums the same safe total (assessment customer benefit, estimated),
    de-duplicates customers (never double-count a customer for having multiple
    team members — input is a set of ids), and reports coverage honestly.
    """
    ids = sorted(set(customer_ids))
    if pipeline_summaries is None:
        pipeline_summaries = pipeline_read_model.pipeline_summaries_for(db, ids)
    total = Decimal(0)
    quantified = 0
    partial = 0
    not_quantified = 0
    for cid in ids:
        summary = _compute_account_impact(db, cid, pipeline_summaries[cid])
        v = summary["total_impact"]["value"]
        cov = summary["coverage"]
        if v is not None:
            total += _d(v)
            quantified += 1
        elif cov == "partial":
            partial += 1
        else:
            not_quantified += 1
    coverage = (
        "quantified" if quantified > 0
        else ("partial" if partial > 0 else "not_quantified")
    )
    return {
        "customer_count": len(ids),
        "as_of": _now_iso(),
        "calculation_version": CALC_VERSION,
        "coverage": coverage,
        "total_impact": {
            "value": _r(total) if quantified > 0 else None,
            "perspective": "customer_benefit",
            "realization_basis": "estimated",
            "currency": None,
        },
        "rollup": {"quantified": quantified, "partial": partial, "not_quantified": not_quantified},
        "pipeline": _portfolio_pipeline(ids, pipeline_summaries),
    }


def _portfolio_pipeline(ids, summaries):
    """Roll up only the supplied authorized snapshots, separately for ACV/TCV."""
    result = {
        "calculation_version": pipeline_read_model.PIPELINE_CALC_VERSION,
        "as_of": summaries[ids[0]]["as_of"] if ids else _now_iso(),
        "note": "latest retained snapshot per account; source-labelled USD; unweighted; "
                "import time is not a business effective date",
    }
    for key in ("acv", "tcv"):
        amounts = [summaries[cid]["amounts"][key] for cid in ids]
        recorded = [amount["total"] for amount in amounts if amount["total"] is not None]
        result[key] = {
            "total": _r(sum((_d(value) for value in recorded), Decimal(0))) if recorded else None,
            "lines": sum(summaries[cid]["grain"]["line_count"] for cid in ids),
            **{f"accounts_{state}": sum(amount["coverage"] == state for amount in amounts)
               for state in ("quantified", "partial", "recorded_zero", "all_unknown", "no_data")},
        }
    return result
