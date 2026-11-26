"""Customer Intelligence service.

Deterministic, rule-based aggregation of the per-customer intelligence
sources (Customer Knowledge, Technology Inventory, Sales Notes, Use Cases)
into a single structured Overview context.

Design constraints:
- No LLM/inference anywhere in this module — pure SQL aggregation
  (user preference: deterministic, rule-based tools).
- No second identity/assignment/visibility model: customer isolation is
  enforced at the route layer (same CustomerUser + admin-bypass convention
  as every other customer-scoped module); this service only reads by
  customer_id.
- Unknowns stay unknown: empty sources yield empty counts / None values,
  never fabricated defaults.
- Derived values are labeled: the response carries
  method="deterministic_aggregation" so consumers (and the UI) can tell
  derived context apart from verified source data.
"""

import re
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.customer_knowledge import CustomerKnowledge
from backend.models.customer_technology import CustomerTechnology
from backend.models.deal import Deal, PipelineStage, deal_notes, deal_technologies
from backend.models.sales_evaluation import SalesEvaluation
from backend.models.sales_note import SalesNote
from backend.models.technology_dependency import TechnologyDependency
from backend.models.use_case import (
    Customer,
    CustomerAssessment,
    CustomerUser,
    Department,
    UseCase,
)
from backend.services.account_health import dated_eol_for
from backend.services.customer_contact_service import contact_coverage_card, contact_coverage_for
from backend.services.pipeline_read_model import (
    pipeline_summary_for,
    renewal_attention_summaries_for,
)

STALE_NOTES_DAYS = 90
AT_RISK_CRITICALITIES = ["critical", "high"]
EOL_STATES = ["eol", "eol_announced"]


def _group_counts(rows, none_label: str = "unknown") -> dict[str, int]:
    """[(key, count), ...] -> {key: count}; None keys map to none_label."""
    out: dict[str, int] = {}
    for key, count in rows:
        label = none_label if key is None else str(key)
        out[label] = out.get(label, 0) + int(count)
    return out


def _count(db: Session, model, customer_id: int, *extra_filters) -> int:
    q = db.query(func.count(model.id)).filter(model.customer_id == customer_id)
    for f in extra_filters:
        q = q.filter(f)
    return int(q.scalar() or 0)


def _technology_inventory_section(db: Session, customer_id: int) -> dict:
    """Technology Inventory aggregates (source)."""
    cust = CustomerTechnology.customer_id == customer_id
    total = _count(db, CustomerTechnology, customer_id)
    by_category = _group_counts(
        db.query(CustomerTechnology.category, func.count())
        .filter(cust)
        .group_by(CustomerTechnology.category)
        .all(),
        none_label="unclassified",
    )
    by_verification = _group_counts(
        db.query(CustomerTechnology.verification_state, func.count())
        .filter(cust)
        .group_by(CustomerTechnology.verification_state)
        .all(),
        none_label="unverified",
    )
    by_lifecycle = _group_counts(
        db.query(CustomerTechnology.lifecycle_state, func.count())
        .filter(cust)
        .group_by(CustomerTechnology.lifecycle_state)
        .all(),
    )
    by_criticality = _group_counts(
        db.query(CustomerTechnology.business_criticality, func.count())
        .filter(cust)
        .group_by(CustomerTechnology.business_criticality)
        .all(),
    )
    eol_count = sum(n for state, n in by_lifecycle.items() if state in EOL_STATES)
    at_risk = (
        db.query(CustomerTechnology)
        .filter(cust)
        .filter(CustomerTechnology.business_criticality.in_(AT_RISK_CRITICALITIES))
        .filter(
            (CustomerTechnology.support_state == "no_support")
            | (CustomerTechnology.lifecycle_state.in_(EOL_STATES))
        )
        .order_by(CustomerTechnology.id)
        .all()
    )
    avg_confidence = (
        db.query(func.avg(CustomerTechnology.confidence))
        .filter(cust, CustomerTechnology.confidence.isnot(None))
        .scalar()
    )
    unverified = (
        by_verification.get("inferred", 0) + by_verification.get("unverified", 0)
    )
    return {
        "total": total,
        "by_category": by_category,
        "by_verification": by_verification,
        "by_lifecycle": by_lifecycle,
        "by_criticality": by_criticality,
        "eol_count": eol_count,
        "average_confidence": round(float(avg_confidence), 3)
        if avg_confidence is not None
        else None,
        "critical_tech_at_risk": [
            {
                "id": t.id,
                "name": t.name,
                "vendor": t.vendor,
                "category": t.category,
                "lifecycle_state": t.lifecycle_state,
                "support_state": t.support_state,
                "business_criticality": t.business_criticality,
                "verification_state": t.verification_state,
            }
            for t in at_risk
        ],
        "critical_tech_at_risk_count": len(at_risk),
        "unverified_pct": round(100.0 * unverified / total, 1) if total else None,
    }


def _sales_notes_section(db: Session, customer_id: int) -> dict:
    """Sales Notes aggregates (source)."""
    cust = SalesNote.customer_id == customer_id
    total = _count(db, SalesNote, customer_id)
    by_category = _group_counts(
        db.query(SalesNote.category, func.count())
        .filter(cust)
        .group_by(SalesNote.category)
        .all()
    )
    by_verification = _group_counts(
        db.query(SalesNote.verification_state, func.count())
        .filter(cust)
        .group_by(SalesNote.verification_state)
        .all(),
        none_label="verified",
    )
    latest = (
        db.query(func.max(SalesNote.note_date)).filter(cust).scalar()
    )
    days_since_latest = (
        (date.today() - latest).days if latest is not None else None
    )
    return {
        "total": total,
        "by_category": by_category,
        "by_verification": by_verification,
        "latest_note_date": latest.isoformat() if latest is not None else None,
        "days_since_latest_note": days_since_latest,
        "stale_after_days": STALE_NOTES_DAYS,
        "notes_stale": (
            days_since_latest is not None and days_since_latest > STALE_NOTES_DAYS
        ),
    }


def _use_cases_section(db: Session, customer_id: int) -> dict:
    """Use Case aggregates (initiatives included; P4 source)."""
    cust = UseCase.customer_id == customer_id
    total = _count(db, UseCase, customer_id)
    by_status = _group_counts(
        db.query(UseCase.status, func.count()).filter(cust).group_by(UseCase.status).all()
    )
    scored = _count(
        db, UseCase, customer_id, UseCase.overall_score.isnot(None)
    )
    avg_overall = (
        db.query(func.avg(UseCase.overall_score))
        .filter(cust, UseCase.overall_score.isnot(None))
        .scalar()
    )
    return {
        "total": total,
        "by_status": by_status,
        "scored_count": scored,
        "scored_ratio": round(scored / total, 3) if total else None,
        "average_overall_score": round(float(avg_overall), 2)
        if avg_overall is not None
        else None,
    }


def _customer_knowledge_section(db: Session, customer_id: int) -> dict:
    """Customer Knowledge aggregates (uploaded source material)."""
    cust = CustomerKnowledge.customer_id == customer_id
    total = _count(db, CustomerKnowledge, customer_id)
    by_type = _group_counts(
        db.query(CustomerKnowledge.knowledge_type, func.count())
        .filter(cust)
        .group_by(CustomerKnowledge.knowledge_type)
        .all(),
        none_label="unclassified",
    )
    by_ingestion = _group_counts(
        db.query(CustomerKnowledge.ingestion_status, func.count())
        .filter(cust)
        .group_by(CustomerKnowledge.ingestion_status)
        .all()
    )
    unprocessed = _count(
        db, CustomerKnowledge, customer_id, CustomerKnowledge.processed == 0
    )
    return {
        "total": total,
        "by_type": by_type,
        "by_ingestion_status": by_ingestion,
        "unprocessed_count": unprocessed,
    }


def get_customer_overview(db: Session, customer_id: int) -> dict:
    """Deterministic per-customer intelligence Overview.

    Pure SQL aggregation over the four source tables. Raises nothing for
    empty customers — every indicator degrades to zero/None (unknowns stay
    unknown). Auth/isolation is enforced by the caller (route layer).
    """
    tech = _technology_inventory_section(db, customer_id)
    notes = _sales_notes_section(db, customer_id)
    use_cases = _use_cases_section(db, customer_id)
    knowledge = _customer_knowledge_section(db, customer_id)
    return {
        "customer_id": customer_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "method": "deterministic_aggregation",
        "technology_inventory": tech,
        "sales_notes": notes,
        "use_cases": use_cases,
        "customer_knowledge": knowledge,
        "partner_pipeline": pipeline_summary_for(db, customer_id),
        "indicators": {
            "eol_tech_count": tech["eol_count"],
            "critical_tech_at_risk_count": tech["critical_tech_at_risk_count"],
            "unverified_tech_pct": tech["unverified_pct"],
            "notes_stale": notes["notes_stale"],
            "days_since_latest_note": notes["days_since_latest_note"],
            "scored_use_case_ratio": use_cases["scored_ratio"],
            "knowledge_unprocessed_count": knowledge["unprocessed_count"],
        },
    }


# ── Account workspace: summaries + Opportunities & Attention ──
# Customer-workspace redesign: richer,
# actionable context for the Overview / Intelligence / Sales workspaces
# without creating a competing source of truth. Reuses the deterministic
# section builders above; everything here is pure SQL aggregation +
# rule-based typing (no LLM, business logic in the service layer).
# Isolation/auth remain enforced at the route layer (CustomerUser + admin
# bypass, same convention as the overview endpoint).

GROWTH_SCORE_THRESHOLD = 70.0
FOLLOW_UP_WINDOW_DAYS = 60
FOLLOW_UP_CATEGORIES = ("opportunity", "risk", "objection", "follow_up")
RECENT_WINDOW_DAYS = 30
MAX_EVIDENCE_ITEMS = 5
MAX_OPPORTUNITY_CARDS = 12
MAX_RENEWAL_CARDS = 5
MAX_EOL_CARDS = 5
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _utcnow_naive() -> datetime:
    """Naive UTC now (the app stores naive-UTC datetimes)."""
    return datetime.now(UTC).replace(tzinfo=None)


def _top_pairs(rows, limit: int, none_label: str = "unknown") -> list[dict]:
    """[(key, count), ...] -> top-N [{key, count}] (count desc, key asc —
    deterministic ordering)."""
    pairs = [(none_label if k is None else str(k), int(n)) for k, n in rows]
    pairs.sort(key=lambda p: (-p[1], p[0]))
    return [{"key": k, "count": n} for k, n in pairs[:limit]]


def _technology_landscape_section(db: Session, customer_id: int) -> dict:
    """Actionable Technology Landscape summary:
    what is known, key vendors/categories, lifecycle risk, important gaps."""
    base = _technology_inventory_section(db, customer_id)
    cust = CustomerTechnology.customer_id == customer_id
    key_vendors = _top_pairs(
        db.query(CustomerTechnology.vendor, func.count(CustomerTechnology.id))
        .filter(cust)
        .group_by(CustomerTechnology.vendor)
        .all(),
        MAX_EVIDENCE_ITEMS,
        none_label="unknown vendor",
    )
    key_categories = _top_pairs(
        list(base["by_category"].items()), MAX_EVIDENCE_ITEMS
    )
    unsupported_count = _count(
        db,
        CustomerTechnology,
        customer_id,
        CustomerTechnology.support_state == "no_support",
    )
    important_gaps: list[str] = []
    if base["total"]:
        if base["eol_count"]:
            important_gaps.append(
                f"{base['eol_count']} item(s) at end-of-life"
            )
        if unsupported_count:
            important_gaps.append(
                f"{unsupported_count} item(s) with no vendor support"
            )
        if base["unverified_pct"] is not None and base["unverified_pct"] >= 30:
            important_gaps.append(
                f"{base['unverified_pct']}% of inventory not yet verified"
            )
    return {
        "total": base["total"],
        "key_vendors": key_vendors,
        "key_categories": key_categories,
        "eol_count": base["eol_count"],
        "unsupported_count": unsupported_count,
        "at_risk_count": base["critical_tech_at_risk_count"],
        "critical_tech_at_risk": base["critical_tech_at_risk"],
        "unverified_pct": base["unverified_pct"],
        "important_gaps": important_gaps,
    }


def _knowledge_summary_section(db: Session, customer_id: int) -> dict:
    """Customer Knowledge summary: sources,
    freshness, recently added, processing state."""
    base = _customer_knowledge_section(db, customer_id)
    cust = CustomerKnowledge.customer_id == customer_id
    now = _utcnow_naive()
    latest = (
        db.query(func.max(CustomerKnowledge.uploaded_at)).filter(cust).scalar()
    )
    if latest is not None and latest.tzinfo is not None:
        latest = latest.astimezone(UTC).replace(tzinfo=None)
    days_since = (now - latest).days if latest is not None else None
    recently_added = _count(
        db,
        CustomerKnowledge,
        customer_id,
        CustomerKnowledge.uploaded_at >= now - timedelta(days=RECENT_WINDOW_DAYS),
    )
    return {
        "total": base["total"],
        "sources": base["by_ingestion_status"],
        "by_type": base["by_type"],
        "latest_uploaded": latest.isoformat() if latest is not None else None,
        "days_since_latest": days_since,
        "recently_added_count": recently_added,
        "unprocessed_count": base["unprocessed_count"],
    }


def _note_brief(n: SalesNote) -> dict:
    return {
        "id": n.id,
        "title": n.title,
        "note_date": n.note_date.isoformat() if n.note_date else None,
        "category": n.category,
        "verification_state": n.verification_state,
    }


def _sales_activity_section(db: Session, customer_id: int) -> dict:
    """Sales Activity summary: last meaningful
    interaction, recent notes, active observations."""
    base = _sales_notes_section(db, customer_id)
    cust = SalesNote.customer_id == customer_id
    latest_note = (
        db.query(SalesNote)
        .filter(cust)
        .order_by(SalesNote.note_date.desc(), SalesNote.id.desc())
        .first()
    )
    recent = (
        db.query(SalesNote)
        .filter(cust)
        .order_by(SalesNote.note_date.desc(), SalesNote.id.desc())
        .limit(MAX_EVIDENCE_ITEMS)
        .all()
    )
    active_observations = (
        db.query(SalesNote)
        .filter(
            cust,
            SalesNote.category.in_(("account_observation", "opportunity")),
        )
        .order_by(SalesNote.note_date.desc(), SalesNote.id.desc())
        .limit(MAX_EVIDENCE_ITEMS)
        .all()
    )
    return {
        "total_notes": base["total"],
        "last_interaction": _note_brief(latest_note) if latest_note else None,
        "days_since_last_interaction": base["days_since_latest_note"],
        "notes_stale": base["notes_stale"],
        "recent": [_note_brief(n) for n in recent],
        "active_observations": [_note_brief(n) for n in active_observations],
    }


def _assessment_summary_section(db: Session, customer_id: int) -> dict:
    """Assessment & Use Case summary: active-round
    progress, average score, highest-impact use cases, unscored items."""
    base = _use_cases_section(db, customer_id)
    cust = UseCase.customer_id == customer_id
    active = (
        db.query(CustomerAssessment)
        .filter(
            CustomerAssessment.customer_id == customer_id,
            CustomerAssessment.status == "active",
        )
        .first()
    )
    if active is not None:
        # Round progress belongs to the ROUND: only use cases explicitly
        # linked to it (assessment_id) count toward the round's
        # total/scored/progress. (Use cases created through the UI are
        # auto-linked; legacy unlinked records are not part of the round.)
        round_total = len(active.use_cases)
        round_scored = sum(
            1 for u in active.use_cases if u.overall_score is not None
        )
        active_assessment = {
            "id": active.id,
            "name": active.name,
            "status": active.status,
            # additive round type + purpose.
            "assessment_type": active.assessment_type or "ai",
            "purpose": active.purpose,
            "total_count": round_total,
            "scored_count": round_scored,
            "progress_pct": round(100.0 * round_scored / round_total, 1)
            if round_total
            else None,
        }
    else:
        active_assessment = None
    # Account-level use-case statistics are CUSTOMER-WIDE — the same scope
    # as average_score / top_use_cases below and as the Assessments
    # use-case table and Business Impact (which count by customer_id).
    # Regression fix: scoping these to the active round made the Overview
    # report "0 use cases total / 0 scored" for accounts whose use cases
    # predate round linkage (assessment_id NULL) while the same card
    # showed the customer-wide average score and top use cases, and the
    # Assessments section showed the completed use cases.
    scope_total, scope_scored = base["total"], base["scored_count"]
    top_use_cases = (
        db.query(UseCase)
        .filter(cust, UseCase.overall_score.isnot(None))
        .order_by(UseCase.overall_score.desc(), UseCase.id)
        .limit(3)
        .all()
    )
    return {
        "active_assessment": active_assessment,
        "average_score": base["average_overall_score"],
        "top_use_cases": [
            {
                "id": u.id,
                "title": u.title,
                "overall_score": u.overall_score,
                "status": u.status,
            }
            for u in top_use_cases
        ],
        "unscored_count": max(0, scope_total - scope_scored),
        "total_count": scope_total,
        "scored_count": scope_scored,
    }


def _business_impact_section(db: Session, customer_id: int) -> dict:
    """Consolidated Business Impact: savings and
    revenue as sub-metrics of one total, never three equal cards."""
    cust = UseCase.customer_id == customer_id
    savings = (
        db.query(func.coalesce(func.sum(UseCase.estimated_savings), 0.0))
        .filter(cust)
        .scalar()
    )
    revenue = (
        db.query(func.coalesce(func.sum(UseCase.estimated_revenue), 0.0))
        .filter(cust)
        .scalar()
    )
    contributing = _count(
        db,
        UseCase,
        customer_id,
        (UseCase.estimated_savings.isnot(None))
        | (UseCase.estimated_revenue.isnot(None)),
    )
    s = round(float(savings or 0.0), 2)
    r = round(float(revenue or 0.0), 2)
    return {
        "total_savings": s,
        "total_revenue": r,
        "total_impact": round(s + r, 2),
        "contributing_use_cases": contributing,
    }


def _latest_evaluation(db: Session, customer_id: int) -> dict | None:
    """Reference to the most recent Sales Evaluation (its risk factors,
    growth opportunities, and discovery gaps feed the synthesis)."""
    ev = (
        db.query(SalesEvaluation)
        .filter(SalesEvaluation.customer_id == customer_id)
        .order_by(
            SalesEvaluation.created_at.desc(), SalesEvaluation.id.desc()
        )
        .first()
    )
    if ev is None:
        return None
    sections = ev.persona_sections if isinstance(ev.persona_sections, dict) else {}
    discovery = sections.get("discovery_gaps")
    return {
        "id": ev.id,
        "evaluation_name": ev.evaluation_name,
        "persona": ev.persona,
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
        "risk_factors": ev.risk_factors or [],
        "growth_opportunities": ev.growth_opportunities or [],
        "discovery_gaps": discovery if isinstance(discovery, list) else [],
    }


def _opportunities_section(
    db: Session,
    customer_id: int,
    tech: dict,
    knowledge: dict,
    sales_activity: dict,
    evaluation: dict | None,
    renewal_cards: list[dict] | None = None,
    contact_coverage_card: dict | None = None,
    eol: dict | None = None,
) -> list[dict]:
    """Deterministic, evidence-backed Opportunities & Attention synthesis.
    Lifecycle risks, observed gaps,
    growth, discovery, follow-ups, renewals, coverage and dated EOL cards each
    carrying the supporting evidence (source + source_id + source_name) so
    the UI can answer "why does this exist?". Sorted by severity (high,
    medium, low), then type, then id; capped at MAX_OPPORTUNITY_CARDS.
    Nothing is invented: every card traces to a row or a metric.
    """
    cards: list[dict] = []

    # 1) Lifecycle risk — critical/high tech with no support or EOL.
    for t in tech.get("critical_tech_at_risk", [])[:MAX_EVIDENCE_ITEMS]:
        cards.append({
            "id": f"lifecycle-risk-tech-{t['id']}",
            "type": "lifecycle_risk",
            "severity": (
                "high" if t.get("business_criticality") == "critical" else "medium"
            ),
            "title": (
                f"{t['name']} — {t.get('lifecycle_state') or 'state unknown'}/"
                f"{t.get('support_state') or 'support unknown'}"
            ),
            "detail": t.get("purpose")
            or f"Business criticality: {t.get('business_criticality') or 'unknown'}.",
            "evidence": {
                "source": "technology",
                "source_id": t["id"],
                "source_name": t["name"],
            },
        })

    # 2) Observed gaps — high-severity findings from the latest evaluation.
    if evaluation:
        for i, rf in enumerate(
            (evaluation.get("risk_factors") or [])[:MAX_EVIDENCE_ITEMS]
        ):
            cards.append({
                "id": f"observed-gap-eval-{evaluation['id']}-{i}",
                "type": "observed_gap",
                "severity": "high",
                "title": str(rf.get("category", "Assessment finding"))
                .replace("_", " ")
                .title(),
                "detail": rf.get("description"),
                "evidence": {
                    "source": "sales_evaluation",
                    "source_id": evaluation["id"],
                    "source_name": evaluation.get("evaluation_name"),
                },
            })

    # 3) Growth opportunities — use cases at/above the readiness threshold.
    for u in (
        db.query(UseCase)
        .filter(
            UseCase.customer_id == customer_id,
            UseCase.overall_score.isnot(None),
            UseCase.overall_score >= GROWTH_SCORE_THRESHOLD,
        )
        .order_by(UseCase.overall_score.desc(), UseCase.id)
        .limit(MAX_EVIDENCE_ITEMS)
        .all()
    ):
        cards.append({
            "id": f"growth-opportunity-uc-{u.id}",
            "type": "growth_opportunity",
            "severity": "medium",
            "title": u.title,
            "detail": (
                f"Readiness score {u.overall_score:.0f} — advance this initiative."
            ),
            "evidence": {
                "source": "use_case",
                "source_id": u.id,
                "source_name": u.title,
            },
        })

    # 4) Discovery needed — gaps in knowledge coverage.
    if tech["total"] == 0:
        cards.append({
            "id": "discovery-needed-technology",
            "type": "discovery_needed",
            "severity": "medium",
            "title": "No technology inventory recorded",
            "detail": (
                "Run a technology discovery session to capture the customer's "
                "estate."
            ),
            "evidence": {
                "source": "technology",
                "source_id": None,
                "source_name": "Technology Inventory",
            },
        })
    elif tech.get("unverified_pct") is not None and tech["unverified_pct"] >= 30:
        cards.append({
            "id": "discovery-needed-technology-unverified",
            "type": "discovery_needed",
            "severity": "medium",
            "title": f"{tech['unverified_pct']}% of technology inventory unverified",
            "detail": (
                "Confirm versions, lifecycle states, and ownership with the "
                "customer's IT team."
            ),
            "evidence": {
                "source": "technology",
                "source_id": None,
                "source_name": "Technology Inventory",
            },
        })
    if sales_activity["total_notes"] == 0:
        cards.append({
            "id": "discovery-needed-sales-activity",
            "type": "discovery_needed",
            "severity": "medium",
            "title": "No sales activity recorded",
            "detail": "Log a discovery note to start building the account story.",
            "evidence": {
                "source": "sales_notes",
                "source_id": None,
                "source_name": "Sales Notes",
            },
        })
    elif sales_activity["notes_stale"]:
        cards.append({
            "id": "discovery-needed-sales-stale",
            "type": "discovery_needed",
            "severity": "low",
            "title": (
                f"No meaningful interaction for "
                f"{sales_activity['days_since_last_interaction']} days"
            ),
            "detail": "Re-engage the account — recent context may have changed.",
            "evidence": {
                "source": "sales_notes",
                "source_id": None,
                "source_name": "Sales Notes",
            },
        })
    if knowledge["unprocessed_count"] > 0:
        cards.append({
            "id": "discovery-needed-knowledge",
            "type": "discovery_needed",
            "severity": "low",
            "title": (
                f"{knowledge['unprocessed_count']} knowledge source(s) "
                "awaiting processing"
            ),
            "detail": (
                "Process uploaded knowledge so it feeds assessments and "
                "evaluations."
            ),
            "evidence": {
                "source": "customer_knowledge",
                "source_id": None,
                "source_name": "Customer Knowledge",
            },
        })

    # 5) Recommended follow-ups — recent actionable sales notes.
    cutoff_date = (
        _utcnow_naive() - timedelta(days=FOLLOW_UP_WINDOW_DAYS)
    ).date()
    for n in (
        db.query(SalesNote)
        .filter(
            SalesNote.customer_id == customer_id,
            SalesNote.category.in_(FOLLOW_UP_CATEGORIES),
            SalesNote.note_date >= cutoff_date,
        )
        .order_by(SalesNote.note_date.desc(), SalesNote.id.desc())
        .limit(3)
        .all()
    ):
        cards.append({
            "id": f"follow-up-note-{n.id}",
            "type": "follow_up",
            "severity": "medium" if n.category == "risk" else "low",
            "title": n.title,
            "detail": (
                f"Recent {n.category} note "
                f"({n.note_date.isoformat() if n.note_date else 'undated'}): "
                "follow up with the customer."
            ),
            "evidence": {
                "source": "sales_note",
                "source_id": n.id,
                "source_name": n.title,
            },
        })

    for item in (eol or {}).get("items", [])[:MAX_EOL_CARDS]:
        cards.append({
            "id": f"eol-attention-{item['id']}", "type": "eol_attention",
            "severity": {"critical": "high", "high": "medium"}.get(item["business_criticality"], "low"),
            "title": f"End-of-support: {item['name']}" + (f" ({item['vendor']})" if item["vendor"] else ""),
            "detail": f"Dated end of support {item['end_of_support_date']}; source: {item['eol_source'] or 'not recorded'}.",
            "evidence": {"source": "technology", "source_id": item["id"], "source_name": item["name"]},
        })
    cards.extend(renewal_cards or [])
    if contact_coverage_card is not None:
        cards.append(contact_coverage_card)
    cards.sort(key=lambda c: (_SEVERITY_RANK.get(c["severity"], 3), c["type"], c["id"]))
    return cards[:MAX_OPPORTUNITY_CARDS]



def _renewal_opportunity_cards(renewals: dict) -> list[dict]:
    """Select the most urgent vendor-reported renewal evidence for the pool.

    This cap applies before the existing overall severity/type/id ordering.
    Import dates describe when evidence was imported, never its effective date.
    """
    snapshot = renewals["snapshot"]
    if snapshot is None:
        return []
    severity = {
        "overdue": "high", "within_30": "high", "within_60": "medium",
        "within_90": "medium", "within_180": "low", "unknown_date": "medium",
    }
    candidates = []
    for bucket in severity:
        ordered = sorted(renewals["buckets"][bucket], key=lambda card: (
            card["days"] if card["days"] is not None else 0,
            card["opportunity_number"],
        ))
        candidates.extend((bucket, card) for card in ordered)
    cards = []
    for bucket, card in candidates[:MAX_RENEWAL_CARDS]:
        number = card["opportunity_number"]
        name = (card["opportunity_name"] or "").strip()
        label = f"{name} ({number})" if name else number
        if bucket == "unknown_date":
            title = f"Reported renewal — {label}: no current contract end date recorded"
            date_detail = "Vendor-reported renewal intent; current contract end date not recorded"
        else:
            if card["days"] < 0:
                ending = f"ended {card['renewal_date']} (overdue)"
            elif card["days"] == 0:
                ending = "ends today"
            else:
                ending = f"ends in {card['days']} days"
            title = f"Renewal — {label}: current contract {ending}"
            date_detail = f"Vendor-reported current contract end {card['renewal_date']}"
        exposure = card["est_acv"]
        amount_detail = (
            f"est. ACV ${exposure['total']:,.2f} ({exposure['coverage']})"
            if exposure["total"] is not None else "est. ACV not recorded"
        )
        detail = (
            f"{date_detail} (snapshot import #{snapshot['import_id']}, "
            f"imported {snapshot['imported_at'][:10]}). "
            f"{card['lines']} lines; {amount_detail}."
        )
        if card["original_contract_end"] is not None:
            detail += f" Original end {card['original_contract_end']} (historical)."
        if card["conflicting_end_dates"]:
            detail += " lines disagree on the end date: " + ", ".join(
                card["conflicting_end_dates"],
            ) + "."
        cards.append({
            "id": f"renewal-attention-{number}", "type": "renewal_attention",
            "severity": severity[bucket], "title": title, "detail": detail,
            "evidence": {"source": "partner_pipeline", "source_id": snapshot["import_id"],
                         "source_name": number},
        })
    return cards


def get_account_workspace(db: Session, customer_id: int) -> dict:
    """Account workspace context.

    Extends the P4 overview with four actionable summaries (Technology
    Landscape, Knowledge, Sales Activity, Assessment & Use Case), a
    consolidated Business Impact figure, the latest Sales Evaluation
    reference, and the typed Opportunities & Attention synthesis. Pure
    deterministic aggregation — unknowns degrade to zero/None, never
    fabricated. Auth/isolation are enforced by the caller (route layer).
    """
    tech = _technology_landscape_section(db, customer_id)
    knowledge = _knowledge_summary_section(db, customer_id)
    sales_activity = _sales_activity_section(db, customer_id)
    assessment = _assessment_summary_section(db, customer_id)
    impact = _business_impact_section(db, customer_id)
    evaluation = _latest_evaluation(db, customer_id)
    renewal_cards = _renewal_opportunity_cards(
        renewal_attention_summaries_for(db, [customer_id])[customer_id],
    )
    opportunities = _opportunities_section(
        db, customer_id, tech, knowledge, sales_activity, evaluation,
        renewal_cards=renewal_cards,
        contact_coverage_card=contact_coverage_card(contact_coverage_for(db, customer_id), None),
        eol=dated_eol_for(db, customer_id),
    )

    customer = (
        db.query(Customer).filter(Customer.id == customer_id).first()
    )
    owner_cu = (
        db.query(CustomerUser)
        .filter(
            CustomerUser.customer_id == customer_id,
            CustomerUser.role == "owner",
        )
        .first()
    )
    account = {
        "id": customer_id,
        "name": customer.name if customer else None,
        "vertical": customer.vertical if customer else None,
        "description": customer.description if customer else None,
        "department_count": (
            db.query(func.count(Department.id))
            .filter(Department.customer_id == customer_id)
            .scalar()
            or 0
        ),
        "member_count": (
            db.query(func.count(CustomerUser.id))
            .filter(CustomerUser.customer_id == customer_id)
            .scalar()
            or 0
        ),
        "owner": (
            {
                "user_id": owner_cu.user_id,
                "display_name": owner_cu.user.display_name
                if owner_cu.user
                else None,
                "username": owner_cu.user.username if owner_cu.user else None,
                "role": owner_cu.role,
            }
            if owner_cu
            else None
        ),
    }
    return {
        "customer_id": customer_id,
        "generated_at": _utcnow_naive().isoformat(),
        "method": "deterministic_aggregation",
        "account": account,
        "technology_landscape": tech,
        "knowledge": knowledge,
        "sales_activity": sales_activity,
        "assessment": assessment,
        "business_impact": impact,
        "latest_evaluation": evaluation,
        "opportunities": opportunities,
        "headline": {
            "active_use_cases": assessment["total_count"],
            "business_impact": impact,
            "technologies_known": tech["total"],
            "open_opportunities_count": len(opportunities),
        },
    }

# ── F3 (PLAN_FEATURE_ENHANCMENTS.md) — Customer Intelligence graph ────────
# Deterministic visualization projection of the authorized customer's
# S-A-I-L records into a node/link view model. The backend OWNS:
# authorization (route layer, before this runs), domain + dependency
# relationships, provenance, and the deterministic classification
# (verified fact vs inferred observation). The frontend owns force
# layout / zoom / Canvas rendering / hover / selection.
#
# Canonical-relationship invariants (directive "canonical graph
# relationships"):
# - every edge is emitted ONCE, in a deterministic orientation; the
#   mirrored duplicate is never emitted;
# - stable relationship ids derived from the authoritative entity ids
#   (never display labels or canvas ordering);
# - a link carries a provenance + epistemic class so inferred
#   relationships are never presented as facts;
# - no edge is created merely because two records share a customer.
#
# Deterministic density control (directive "dense customers"): each
# domain contributes a bounded top-N by a legitimate value (score,
# recency, criticality) so the graph stays in the dozens-of-nodes range
# and the response reports the active limits.

_GRAPH_MAX_PER_DOMAIN = 8
# Synthesis card types per graph domain (including renewal, coverage and EOL).
_GRAPH_RISK_TYPES = ("lifecycle_risk", "observed_gap", "eol_attention", "contact_coverage")
_GRAPH_OPPORTUNITY_TYPES = ("growth_opportunity", "follow_up", "discovery_needed", "renewal_attention")


def _graph_metadata_technology(t: CustomerTechnology) -> dict:
    return {
        "vendor": t.vendor,
        "category": t.category,
        "version_edition": t.version_edition,
        "deployment_model": t.deployment_model,
        "lifecycle_state": t.lifecycle_state,
        "support_state": t.support_state,
        "business_criticality": t.business_criticality,
        "confidence": t.confidence,
    }


def _graph_metadata_use_case(u: UseCase) -> dict:
    return {
        "department": u.department,
        "status": u.status,
        "overall_score": u.overall_score,
        "description": (u.description or "")[:200] if u.description else None,
    }


def _graph_metadata_sales_note(n: SalesNote) -> dict:
    return {
        "author": n.author,
        "note_date": n.note_date.isoformat() if n.note_date else None,
        "category": n.category,
        "excerpt": (n.content or "")[:200] if n.content else None,
    }


def _graph_metadata_assessment(a: CustomerAssessment) -> dict:
    # additive round type + purpose (the FE tooltip/legend
    # data); name/status are byte-identical to before.
    return {
        "name": a.name,
        "status": a.status,
        "assessment_type": a.assessment_type or "ai",
        "purpose": a.purpose,
    }


def _graph_metadata_sales_evaluation(e: SalesEvaluation) -> dict:
    return {
        "persona": e.persona,
        "evaluation_name": e.evaluation_name,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def _graph_metadata_opportunity(op: dict) -> dict:
    return {
        "type": op.get("type"),
        "severity": op.get("severity"),
        "detail": op.get("detail"),
        "evidence": op.get("evidence"),
    }


def _node(
    kind: str,
    domain: str,
    entity_id: int,
    label: str,
    *,
    node_id: str | None = None,
    importance: float | None = None,
    status: str | None = None,
    confidence: float | None = None,
    verified: bool | None = None,
    metadata: dict | None = None,
    route: str = "",
    level: int | None = None,
    parentId: str | None = None,
    groupKey: str | None = None,
    empty: bool = False,
) -> dict:
    """One visualization node. id = '<domain>-<entity_id>' (stable) unless
    an explicit ``node_id`` is given (domain hubs use it to avoid the
    entity-id namespace entirely)."""
    return {
        "id": node_id if node_id is not None else f"{domain}-{entity_id}",
        "type": kind,
        "label": label,
        "category": domain,
        "entityId": entity_id,
        "entityType": kind,
        "importance": importance,
        "status": status,
        "confidence": confidence,
        "verified": verified,
        "metadata": metadata or {},
        "route": route,
        "level": level,
        "parentId": parentId,
        "groupKey": groupKey,
        "empty": empty,
    }


def _link(
    source: str,
    target: str,
    relationship: str,
    relationship_type: str,
    *,
    strength: float | None = None,
    verified: bool | None = None,
    confidence: float | None = None,
    provenance: str | None = None,
) -> dict:
    """One visualization link. id = deterministic over (source, target,
    relationship_type) — stable regardless of canvas ordering/labels."""
    return {
        "id": f"{source}|{target}|{relationship_type}",
        "source": source,
        "target": target,
        "relationship": relationship,
        "relationshipType": relationship_type,
        "strength": strength,
        "verified": verified,
        "confidence": confidence,
        "provenance": provenance,
    }


def _dedup_links(links: list[dict]) -> list[dict]:
    """Canonical deduplication: collapse identical (source, target,
    relationship_type) triples to the FIRST occurrence, never emitting the
    mirrored duplicate. Order is preserved (deterministic)."""
    seen = set()
    out: list[dict] = []
    for lnk in links:
        key = (lnk["source"], lnk["target"], lnk["relationshipType"])
        if key in seen:
            continue
        seen.add(key)
        out.append(lnk)
    return out


def _tech_node_priority(t: CustomerTechnology) -> tuple:
    """Deterministic rank bounding the technology domain to top-N:
    criticality first (a legitimate value), then at-risk lifecycle, then id."""
    crit_rank = {
        "critical": 0, "high": 1, "medium": 2, "low": 3,
    }.get(t.business_criticality, 4)
    at_risk = 0 if (
        t.support_state == "no_support" or t.lifecycle_state in EOL_STATES
    ) else 1
    return (crit_rank, at_risk, t.id)


def _portion_node_id(domain: str, group_key: str) -> str:
    sanitized = re.sub(r"[^a-z0-9]+", "-", group_key.lower()).strip("-")
    return f"portion-{domain}-{sanitized}"


def _portion_label(group_key: str) -> str:
    return group_key.replace("_", " ").title()


def build_customer_intelligence_graph(db: Session, customer_id: int) -> dict:
    """Deterministic Customer Intelligence graph projection (F3).

    Returns ``{"nodes": [...], "links": [...], "limits": {...},
    "method": "deterministic_graph_projection"}`` for ONE customer.
    Auth/isolation are enforced by the caller (route layer) BEFORE this
    runs — nothing here reads another customer's records.

    Node hierarchy: Customer (central) -> Domain -> Portion -> Entity. The
    original Domain -> Entity trunk links remain additive. Cross-domain links
    come from AUTHORITATIVE explicit references only:
    TechnologyDependency rows, SalesNote technology junctions, and the
    Opportunities & Attention synthesis (which carries evidence source
    refs). No edge is fabricated from shared customer membership.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    customer_label = customer.name if customer else f"Customer {customer_id}"

    nodes: list[dict] = []
    links: list[dict] = []
    domain_node_ids: dict[str, str] = {}
    # Distinct portion groups per domain across ALL records (not only the
    # kept top-N) — the honest `group_limits.total`.
    group_totals: dict[str, int] = {}

    # ── Central customer node (largest anchor, always present) ──
    customer_node = _node(
        "customer", "customer", customer_id, customer_label,
        importance=1.0, status="active", verified=True,
        metadata={
            "branch": customer.branch if customer else None,
            "department_count": (
                db.query(func.count(Department.id))
                .filter(Department.customer_id == customer_id)
                .scalar()
                or 0
            ),
            "member_count": (
                db.query(func.count(CustomerUser.id))
                .filter(CustomerUser.customer_id == customer_id)
                .scalar()
                or 0
            ),
            "vertical": customer.vertical if customer else None,
        },
        route=f"/customers/{customer_id}",
        level=0, parentId=None, groupKey=None, empty=False,
    )
    nodes.append(customer_node)

    def _domain_node(domain: str, label: str) -> str:
        """Create + register the domain hub node, link it to the customer,
        and return its id. Idempotent per domain."""
        node_id = f"{domain}-domain"
        if node_id in domain_node_ids:
            return node_id
        domain_node_ids[domain] = node_id
        nodes.append(_node(
            "domain", domain, customer_id, label,
            node_id=node_id,
            importance=0.6, verified=True,
            metadata={"domain": domain}, route="",
            level=1, parentId=customer_node["id"], groupKey=None,
            empty=False,
        ))
        links.append(_link(
            customer_node["id"], node_id,
            f"{label} domain", f"domain:{domain}",
            verified=True, provenance="domain hub (structural)",
        ))
        return node_id

    def _portion_nodes(
        domain: str,
        domain_label: str,
        domain_node_id: str,
        kept_group_keys: list[str],
        all_group_keys: list[str],
    ) -> dict[str, str]:
        """Create deterministic portion nodes and their hub edges."""
        group_totals[domain] = len(set(all_group_keys))
        group_ids: dict[str, str] = {}
        for group_key in sorted(set(kept_group_keys)):
            node_id = _portion_node_id(domain, group_key)
            label = _portion_label(group_key)
            member_count = kept_group_keys.count(group_key)
            group_ids[group_key] = node_id
            nodes.append(_node(
                "group", domain, customer_id, label,
                node_id=node_id,
                importance=round(
                    0.3 + 0.5 * (min(member_count, 8) / 8), 3
                ),
                status=None, confidence=None, verified=True,
                metadata={
                    "member_count": member_count,
                    "group_key": group_key,
                },
                route="", level=2, parentId=domain_node_id,
                groupKey=group_key, empty=False,
            ))
            links.append(_link(
                domain_node_id, node_id,
                f"{label} portion of {domain_label}",
                f"portion:{domain}", verified=True,
                provenance="portion grouping (derived)",
            ))

        if set(all_group_keys) - set(kept_group_keys):
            humanized = {
                "technology": "technology",
                "use_case": "use case",
                "sales_note": "sales note",
                "assessment": "assessment",
                "sales_evaluation": "sales evaluation",
                "risk": "risk",
                "opportunity": "opportunity",
            }[domain]
            node_id = f"portion-empty-{domain}"
            label = f"no {humanized} shown"
            nodes.append(_node(
                "empty", domain, customer_id, label,
                node_id=node_id, importance=0.1, status=None,
                confidence=None, verified=True, metadata={"empty": True},
                route="", level=2, parentId=domain_node_id,
                groupKey=None, empty=True,
            ))
            links.append(_link(
                domain_node_id, node_id,
                f"{label} portion of {domain_label}",
                f"portion:{domain}", verified=True,
                provenance="portion grouping (derived)",
            ))
        return group_ids

    # ── Technology domain + technology-dependency edges ──
    techs = (
        db.query(CustomerTechnology)
        .filter(CustomerTechnology.customer_id == customer_id)
        .all()
    )
    techs = sorted(techs, key=_tech_node_priority)
    tech_kept = techs[:_GRAPH_MAX_PER_DOMAIN]
    tech_node_ids = {t.id: f"technology-{t.id}" for t in tech_kept}
    tech_domain = _domain_node("technology", "Technology") if tech_kept else None
    tech_group_keys = [t.category or "unclassified" for t in tech_kept]
    tech_group_ids = _portion_nodes(
        "technology", "Technology", tech_domain, tech_group_keys,
        [t.category or "unclassified" for t in techs],
    ) if tech_domain else {}
    for t in tech_kept:
        nid = tech_node_ids[t.id]
        group_key = t.category or "unclassified"
        if tech_domain:
            links.append(_link(
                tech_domain, nid, "technology member", "domain:technology",
                verified=True, provenance="domain hub (structural)",
            ))
            links.append(_link(
                nid, tech_group_ids[group_key],
                f"{t.name} · {_portion_label(group_key)}",
                "supports:technology", verified=True,
                provenance="portion grouping (derived)",
            ))
        importance = {
            "critical": 0.9, "high": 0.75, "medium": 0.5, "low": 0.35,
        }.get(t.business_criticality, 0.5)
        nodes.append(_node(
            "technology", "technology", t.id, t.name,
            importance=importance, status=t.lifecycle_state,
            confidence=t.confidence,
            verified=(t.verification_state == "verified"),
            metadata=_graph_metadata_technology(t),
            route=f"/technology/{t.id}",
            level=3, parentId=tech_group_ids[group_key],
            groupKey=group_key, empty=False,
        ))
    # Technology-to-technology dependency edges (F1 model; canonical
    # orientation + dedup inherited from the single stored row).
    deps = (
        db.query(TechnologyDependency)
        .filter(TechnologyDependency.customer_id == customer_id)
        .order_by(TechnologyDependency.id)
        .all()
    )
    dep_emitted = 0
    for d in deps:
        # Endpoints resolve by technology ID (never by display name: two
        # technologies may share a name, and a dependency on a technology
        # outside the kept top-N must not attach to a same-named kept one).
        src_nid = tech_node_ids.get(d.source_id)
        tgt_nid = tech_node_ids.get(d.target_id)
        if src_nid is None or tgt_nid is None or src_nid == tgt_nid:
            continue  # endpoint outside kept top-N — omit, never fabricate
        links.append(_link(
            src_nid, tgt_nid,
            f"{d.source.name} {d.relationship_type} {d.target.name}",
            f"tech_dependency:{d.relationship_type}",
            strength=d.confidence,
            verified=(d.verification_state == "verified"),
            confidence=d.confidence,
            provenance=d.source_provenance or "technology dependency record",
        ))
        dep_emitted += 1

    # ── Use Cases / Initiatives domain (top-N by score) ──
    ucs = (
        db.query(UseCase)
        .filter(UseCase.customer_id == customer_id)
        .order_by(UseCase.overall_score.desc(), UseCase.id)
        .all()
    )
    uc_kept = ucs[:_GRAPH_MAX_PER_DOMAIN]
    uc_node_ids = {u.id: f"use_case-{u.id}" for u in uc_kept}
    uc_domain = _domain_node("use_case", "Use Cases / Initiatives") if uc_kept else None
    uc_group_keys = [u.status or "unknown" for u in uc_kept]
    uc_group_ids = _portion_nodes(
        "use_case", "Use Cases / Initiatives", uc_domain, uc_group_keys,
        [u.status or "unknown" for u in ucs],
    ) if uc_domain else {}
    for u in uc_kept:
        nid = uc_node_ids[u.id]
        group_key = u.status or "unknown"
        if uc_domain:
            links.append(_link(
                uc_domain, nid, "use case member", "domain:use_case",
                verified=True, provenance="domain hub (structural)",
            ))
            links.append(_link(
                nid, uc_group_ids[group_key],
                f"{u.title} · {_portion_label(group_key)}",
                "supports:use_case", verified=True,
                provenance="portion grouping (derived)",
            ))
        nodes.append(_node(
            "use_case", "use_case", u.id, u.title,
            importance=(u.overall_score / 100.0)
            if u.overall_score is not None else 0.5,
            status=u.status, verified=True,
            metadata=_graph_metadata_use_case(u),
            route=f"/use-case/{u.id}",
            level=3, parentId=uc_group_ids[group_key],
            groupKey=group_key, empty=False,
        ))

    # ── Sales Notes domain (+ note -> technology cross-domain links) ──
    notes = (
        db.query(SalesNote)
        .filter(SalesNote.customer_id == customer_id)
        .order_by(SalesNote.note_date.desc(), SalesNote.id)
        .all()
    )
    note_kept = notes[:_GRAPH_MAX_PER_DOMAIN]
    note_node_ids = {n.id: f"sales_note-{n.id}" for n in note_kept}
    note_domain = _domain_node("sales_note", "Sales Notes") if note_kept else None
    note_group_keys = [n.category for n in note_kept]
    note_group_ids = _portion_nodes(
        "sales_note", "Sales Notes", note_domain, note_group_keys,
        [n.category for n in notes],
    ) if note_domain else {}
    for n in note_kept:
        nid = f"sales_note-{n.id}"
        group_key = n.category
        if note_domain:
            links.append(_link(
                note_domain, nid, "sales note member", "domain:sales_note",
                verified=True, provenance="domain hub (structural)",
            ))
            links.append(_link(
                nid, note_group_ids[group_key],
                f"{n.title} · {_portion_label(group_key)}",
                "supports:sales_note", verified=True,
                provenance="portion grouping (derived)",
            ))
        nodes.append(_node(
            "sales_note", "sales_note", n.id, n.title,
            importance=0.5, status=n.category,
            verified=(n.verification_state == "verified"),
            metadata=_graph_metadata_sales_note(n),
            route=f"/sales-note/{n.id}",
            level=3, parentId=note_group_ids[group_key],
            groupKey=group_key, empty=False,
        ))
        # Cross-domain: note -> each linked technology (only where both are
        # kept; an authoritative explicit junction reference).
        for tech_id in n.related_technology_ids:
            if tech_id in tech_node_ids:
                links.append(_link(
                    nid, f"technology-{tech_id}",
                    f"{n.title} references a technology",
                    "note_references_technology",
                    verified=(n.verification_state == "verified"),
                    provenance=f"sales note #{n.id} technology junction",
                ))

    # ── Assessments domain (active round) ──
    active = (
        db.query(CustomerAssessment)
        .filter(
            CustomerAssessment.customer_id == customer_id,
            CustomerAssessment.status == "active",
        )
        .first()
    )
    if active is not None:
        # a generic round renders under its own visual
        # domain ('assessment_generic' / "Generic Assessments") so the graph
        # never presents a non-AI round as AI. The node id keeps the stable
        # 'assessment-<id>' pattern for both types (AI-round ids unchanged).
        a_type = active.assessment_type or "ai"
        a_domain = "assessment_generic" if a_type == "generic" else "assessment"
        a_domain_label = "Generic Assessments" if a_type == "generic" else "AI Assessments"
        a_nid = f"assessment-{active.id}"
        asmt_domain = _domain_node(a_domain, a_domain_label)
        asmt_group_ids = _portion_nodes(
            a_domain, a_domain_label, asmt_domain, ["active"],
            ["active"],
        )
        links.append(_link(
            asmt_domain, a_nid, "assessment round", f"domain:{a_domain}",
            verified=True, provenance="domain hub (structural)",
        ))
        links.append(_link(
            a_nid, asmt_group_ids["active"],
            f"{active.name} · {_portion_label('active')}",
            f"supports:{a_domain}", verified=True,
            provenance="portion grouping (derived)",
        ))
        nodes.append(_node(
            a_domain, a_domain, active.id, active.name,
            node_id=a_nid,
            importance=0.7, status=active.status, verified=True,
            metadata=_graph_metadata_assessment(active),
            route=f"/assessment/{active.id}",
            level=3, parentId=asmt_group_ids["active"],
            groupKey="active", empty=False,
        ))

    # ── Sales Evaluations domain (latest) ──
    # Same "latest" rule as _latest_evaluation (created_at desc, then the
    # NEWEST id) so the evaluation node is the evaluation whose findings
    # feed the observed-gap risks below.
    latest_ev = (
        db.query(SalesEvaluation)
        .filter(SalesEvaluation.customer_id == customer_id)
        .order_by(SalesEvaluation.created_at.desc(), SalesEvaluation.id.desc())
        .first()
    )
    ev_node_id = f"sales_evaluation-{latest_ev.id}" if latest_ev is not None else None
    if latest_ev is not None:
        e_nid = f"sales_evaluation-{latest_ev.id}"
        ev_domain = _domain_node("sales_evaluation", "Sales Evaluations")
        ev_group_key = latest_ev.persona or "generic"
        ev_group_ids = _portion_nodes(
            "sales_evaluation", "Sales Evaluations", ev_domain,
            [ev_group_key], [ev_group_key],
        )
        links.append(_link(
            ev_domain, e_nid, "sales evaluation", "domain:sales_evaluation",
            verified=True, provenance="domain hub (structural)",
        ))
        links.append(_link(
            e_nid, ev_group_ids[ev_group_key],
            f"{latest_ev.evaluation_name or 'Sales Evaluation'} · "
            f"{_portion_label(ev_group_key)}",
            "supports:sales_evaluation", verified=True,
            provenance="portion grouping (derived)",
        ))
        nodes.append(_node(
            "sales_evaluation", "sales_evaluation", latest_ev.id,
            latest_ev.evaluation_name or "Sales Evaluation",
            importance=0.6, status=latest_ev.persona or "generic",
            verified=True,
            metadata=_graph_metadata_sales_evaluation(latest_ev),
            route=f"/sales-evaluation/{latest_ev.id}",
            level=3, parentId=ev_group_ids[ev_group_key],
            groupKey=ev_group_key, empty=False,
        ))

    # ── Opportunities / Risks-Gaps domains (typed synthesis, top-N) ──
    # Exactly the workspace panel's Opportunities & Attention synthesis,
    # including its renewal, contact-coverage and dated-EOL inputs, so the
    # graph and the panel always agree.
    # Gaps and lifecycle attention -> risk domain; growth, discovery,
    # follow-ups and renewal attention -> opportunity domain.
    _tech = _technology_landscape_section(db, customer_id)
    _kn = _knowledge_summary_section(db, customer_id)
    _sa = _sales_activity_section(db, customer_id)
    _ev = _latest_evaluation(db, customer_id)
    opportunities = _opportunities_section(
        db, customer_id, _tech, _kn, _sa, _ev,
        renewal_cards=_renewal_opportunity_cards(
            renewal_attention_summaries_for(db, [customer_id])[customer_id],
        ),
        contact_coverage_card=contact_coverage_card(contact_coverage_for(db, customer_id), None),
        eol=dated_eol_for(db, customer_id),
    )
    has_stored_source_data = bool(
        techs or ucs or notes or active or latest_ev or _kn["total"]
    )
    all_risk_ops = [
        o for o in opportunities
        if o["type"] in _GRAPH_RISK_TYPES
    ]
    risk_ops = all_risk_ops[:_GRAPH_MAX_PER_DOMAIN]
    all_opp_ops = [
        o for o in opportunities
        if o["type"] in _GRAPH_OPPORTUNITY_TYPES
    ]
    opp_ops = all_opp_ops[:_GRAPH_MAX_PER_DOMAIN]

    if risk_ops:
        risk_domain = _domain_node("risk", "Risks / Gaps")
        risk_group_ids = {}
        if has_stored_source_data:
            risk_group_keys = [o["type"] for o in risk_ops]
            risk_group_ids = _portion_nodes(
                "risk", "Risks / Gaps", risk_domain, risk_group_keys,
                [o["type"] for o in all_risk_ops],
            )
        for i, o in enumerate(risk_ops):
            o_nid = f"risk-{i}"
            group_key = o["type"]
            links.append(_link(
                risk_domain, o_nid, "risk/gap", "domain:risk",
                verified=True,
                provenance="opportunity synthesis (deterministic)",
            ))
            if risk_group_ids:
                links.append(_link(
                    o_nid, risk_group_ids[group_key],
                    f"{o['title']} · {_portion_label(group_key)}",
                    "supports:risk", verified=True,
                    provenance="portion grouping (derived)",
                ))
            nodes.append(_node(
                "risk", "risk", i, o["title"],
                importance={"high": 0.9, "medium": 0.65, "low": 0.4}
                .get(o["severity"], 0.5),
                status=o["type"], verified=True,
                metadata=_graph_metadata_opportunity(o), route="",
                level=3, parentId=risk_group_ids.get(group_key),
                groupKey=group_key, empty=False,
            ))
            ev = o.get("evidence") or {}
            if ev.get("source") == "technology" and ev.get("source_id") in tech_node_ids:
                links.append(_link(
                    o_nid, f"technology-{ev['source_id']}",
                    f"risk on {ev.get('source_name')}",
                    "risk_affects_technology",
                    verified=True,
                    provenance="opportunity synthesis evidence ref",
                ))
            # Observed gaps come from the latest sales evaluation's findings
            # — the same evaluation the graph shows as its evaluation node.
            elif (ev.get("source") == "sales_evaluation" and ev_node_id is not None
                    and ev.get("source_id") == latest_ev.id):
                links.append(_link(
                    o_nid, ev_node_id,
                    f"gap found in {ev.get('source_name') or 'sales evaluation'}",
                    "gap_from_sales_evaluation",
                    verified=True,
                    provenance="opportunity synthesis evidence ref",
                ))
    if opp_ops:
        opp_domain = _domain_node("opportunity", "Opportunities")
        opp_group_ids = {}
        if has_stored_source_data:
            opp_group_keys = [o["type"] for o in opp_ops]
            opp_group_ids = _portion_nodes(
                "opportunity", "Opportunities", opp_domain, opp_group_keys,
                [o["type"] for o in all_opp_ops],
            )
        for i, o in enumerate(opp_ops):
            o_nid = f"opportunity-{i}"
            group_key = o["type"]
            links.append(_link(
                opp_domain, o_nid, "opportunity", "domain:opportunity",
                verified=True,
                provenance="opportunity synthesis (deterministic)",
            ))
            if opp_group_ids:
                links.append(_link(
                    o_nid, opp_group_ids[group_key],
                    f"{o['title']} · {_portion_label(group_key)}",
                    "supports:opportunity", verified=True,
                    provenance="portion grouping (derived)",
                ))
            nodes.append(_node(
                "opportunity", "opportunity", i, o["title"],
                importance={"high": 0.9, "medium": 0.65, "low": 0.4}
                .get(o["severity"], 0.5),
                status=o["type"], verified=True,
                metadata=_graph_metadata_opportunity(o), route="",
                level=3, parentId=opp_group_ids.get(group_key),
                groupKey=group_key, empty=False,
            ))
            ev = o.get("evidence") or {}
            if ev.get("source") == "use_case" and ev.get("source_id") in uc_node_ids:
                links.append(_link(
                    o_nid, f"use_case-{ev['source_id']}",
                    f"opportunity supported by {ev.get('source_name')}",
                    "opportunity_supported_by_use_case",
                    verified=True,
                    provenance="opportunity synthesis evidence ref",
                ))
            # Follow-ups come from a recent actionable sales note — link it
            # when that note is among the kept notes.
            elif ev.get("source") == "sales_note" and ev.get("source_id") in note_node_ids:
                links.append(_link(
                    o_nid, note_node_ids[ev["source_id"]],
                    f"follow up on {ev.get('source_name')}",
                    "follow_up_on_sales_note",
                    verified=True,
                    provenance="opportunity synthesis evidence ref",
                ))

    # Rep-maintained deals share the existing commercial sector; they are
    # distinct records, not derived Attention or imported vendor amounts.
    deal_rows = db.query(Deal, PipelineStage).join(PipelineStage, PipelineStage.id == Deal.stage_id).filter(
        Deal.customer_id == customer_id).order_by(Deal.updated_at.desc(), Deal.id.desc()).limit(_GRAPH_MAX_PER_DOMAIN).all()
    if deal_rows:
        deal_domain = domain_node_ids.get('opportunity') or _domain_node('opportunity', 'Opportunities')
        deal_ids = [deal.id for deal, _stage in deal_rows]
        evidence = []
        for table, key, prefix in ((deal_notes, "note_id", "sales_note"), (deal_technologies, "technology_id", "technology")):
            evidence.extend((deal_id, f"{prefix}-{related}") for deal_id, related in db.query(table.c.deal_id, table.c[key]).filter(table.c.deal_id.in_(deal_ids)))
        node_ids = {node['id'] for node in nodes}
        for deal, stage in deal_rows:
            node_id = f"deal-{deal.id}"
            nodes.append(_node("opportunity", "opportunity", deal.id, deal.name, node_id=node_id, status=stage.label,
                importance=0.65, verified=True, level=3, parentId=deal_domain,
                metadata={"source": "rep_deal", "deal_id": deal.id, "stage": stage.label,
                          "owner": deal.owner_name, "amount_minor": deal.amount_minor,
                          "currency": deal.currency, "amount_basis": deal.amount_basis}))
            links.append(_link(deal_domain, node_id, "rep-maintained deal", "domain:deal", verified=True))
            for deal_id, target in evidence:
                if deal_id == deal.id and target in node_ids:
                    links.append(_link(node_id, target, "deal evidence", "deal:evidence", verified=True))

    # ── Canonical dedup + deterministic ordering ──
    links = _dedup_links(links)
    links.sort(key=lambda lnk: (lnk["source"], lnk["target"], lnk["relationshipType"]))
    nodes.sort(key=lambda n: (n["level"], n["id"]))

    group_limits = {}
    empty_portions = {}
    for node in nodes:
        if node["type"] == "group":
            domain = node["category"]
            group_limits.setdefault(domain, {"total": group_totals.get(domain, 0), "shown": 0})
            group_limits[domain]["shown"] += 1
        elif node["type"] == "empty":
            empty_portions[node["category"]] = 1

    limits = {
        "max_per_domain": _GRAPH_MAX_PER_DOMAIN,
        "technology_total": len(techs),
        "technology_shown": len(tech_kept),
        "use_case_total": len(ucs),
        "use_case_shown": len(uc_kept),
        "sales_note_total": len(notes),
        "sales_note_shown": len(note_kept),
        "dependencies_total": len(deps),
        "dependencies_shown": dep_emitted,
        "opportunities_total": len(opportunities),
        "group_limits": group_limits,
        "empty_portions": empty_portions,
    }
    return {
        "customer_id": customer_id,
        "generated_at": _utcnow_naive().isoformat(),
        "method": "deterministic_graph_projection",
        "customer_label": customer_label,
        "nodes": nodes,
        "links": links,
        "limits": limits,
    }
