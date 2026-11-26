"""Cross-domain sales evaluation engine.

Combines organizational readiness (scoring dimensions) with customer environment
knowledge (software inventory, hardware, processes) to produce actionable gap/risk/
growth analyses for sales approach efficiency.

Weighting (configurable):
    40% software completeness
    30% hardware currency
    20% process documentation
    10% vendor diversity
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.models.customer_knowledge import CustomerKnowledge
from backend.models.sales_evaluation import SalesEvaluation
from backend.models.sales_note import SalesNote
from backend.models.use_case import Customer, UseCase
from backend.services.customer_intelligence import get_customer_overview
from backend.services.sales_personas import get_persona

# ── Configurable weights ──────────────────────────────────────────────────────
SOFTWARE_WEIGHT = 0.40
HARDWARE_WEIGHT = 0.30
PROCESS_WEIGHT = 0.20
VENDOR_WEIGHT = 0.10

# Score thresholds
SCORE_STRONG = 75
SCORE_MODERATE = 50
SCORE_WEAK = 50  # < 50


def compute_environment_score(db: Session, customer_id: int) -> tuple[float, dict[str, Any]]:
    """Compute 0-100 environment score from customer knowledge base.

    Returns (score, factors_dict) with per-category breakdown.
    """
    entries = db.query(CustomerKnowledge).filter(
        CustomerKnowledge.customer_id == customer_id
    ).all()

    # Classify entries by type
    software_entries = [e for e in entries if e.knowledge_type in ("software_inventory",)]
    hardware_entries = [e for e in entries if e.knowledge_type in ("hardware_inventory",)]
    process_entries = [e for e in entries if e.knowledge_type in ("process_document", "policy_document")]
    all_entries = entries

    # Software completeness: based on number of unique software items and coverage
    software_score = _compute_software_completeness(software_entries)
    # Hardware currency: based on hardware entries and freshness
    hardware_score = _compute_hardware_currency(hardware_entries)
    # Process documentation: based on document coverage
    process_score = _compute_process_coverage(process_entries)
    # Vendor diversity: based on variety of vendors in knowledge base
    vendor_score = _compute_vendor_diversity(all_entries)

    # Weighted composite
    composite = (
        software_score * SOFTWARE_WEIGHT
        + hardware_score * HARDWARE_WEIGHT
        + process_score * PROCESS_WEIGHT
        + vendor_score * VENDOR_WEIGHT
    )

    factors: dict[str, Any] = {
        "software_completeness": round(software_score, 2),
        "hardware_currency": round(hardware_score, 2),
        "process_documentation": round(process_score, 2),
        "vendor_diversity": round(vendor_score, 2),
        "details": {
            "software_entries": len(software_entries),
            "hardware_entries": len(hardware_entries),
            "process_entries": len(process_entries),
            "total_entries": len(all_entries),
        },
    }

    return round(composite, 2), factors


def _compute_software_completeness(entries: list[CustomerKnowledge]) -> float:
    """Score software inventory completeness (0-100)."""
    if not entries:
        return 0.0
    # Score based on number of entries (diminishing returns after 20)
    count = len(entries)
    score = min(100.0, count * 5.0)  # 20 entries = 100
    # Bonus for processed entries
    processed = sum(1 for e in entries if e.processed)
    if count > 0:
        score *= (0.5 + 0.5 * (processed / count))  # 50-100% based on processing
    return min(100.0, score)


def _compute_hardware_currency(entries: list[CustomerKnowledge]) -> float:
    """Score hardware inventory currency (0-100)."""
    if not entries:
        return 0.0
    count = len(entries)
    score = min(100.0, count * 5.0)
    processed = sum(1 for e in entries if e.processed)
    if count > 0:
        score *= (0.5 + 0.5 * (processed / count))
    return min(100.0, score)


def _compute_process_coverage(entries: list[CustomerKnowledge]) -> float:
    """Score process documentation coverage (0-100)."""
    if not entries:
        return 0.0
    count = len(entries)
    score = min(100.0, count * 5.0)
    processed = sum(1 for e in entries if e.processed)
    if count > 0:
        score *= (0.5 + 0.5 * (processed / count))
    return min(100.0, score)


def _compute_vendor_diversity(entries: list[CustomerKnowledge]) -> float:
    """Score vendor diversity (0-100)."""
    if not entries:
        return 0.0
    # Extract unique vendors from extracted text
    vendors: set[str] = set()
    for entry in entries:
        # Canonical content: normalized Markdown first, legacy extracted
        # text fallback (PLAN.md part 43 item 16).
        text = entry.knowledge_text
        if text:
            # Simple vendor extraction: look for capitalized multi-word terms
            text = text.lower()
            # Common vendor indicators
            for vendor_keyword in [
                "microsoft", "cisco", "vmware", "amazon", "google",
                "oracle", "ibm", "sap", "salesforce", "dell",
                "hp", "red hat", "palantir", "snowflake",
            ]:
                if vendor_keyword in text:
                    vendors.add(vendor_keyword)
    # Score based on diversity (more vendors = higher score)
    diversity = len(vendors)
    score = min(100.0, diversity * 10.0)  # 10 unique vendors = 100
    return score


def identify_gaps(
    readiness_data: dict[str, Any],
    environment_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compare readiness vs. environment and identify gaps.

    readiness_data: dict with 'average_score', 'dimensions' (dim -> score)
    environment_data: dict with environment factors
    """
    gaps: list[dict[str, Any]] = []
    avg_score = readiness_data.get("average_score", 0)
    dimensions = readiness_data.get("dimensions", {})
    env_factors = environment_data.get("environment_factors", {})

    # Software gaps: high readiness but low software documentation
    sw_score = dimensions.get("technical_feasibility", 0)
    sw_completeness = env_factors.get("software_completeness", 0)
    if sw_score >= SCORE_STRONG and sw_completeness < SCORE_MODERATE:
        gaps.append({
            "category": "software",
            "severity": "high",
            "description": f"Strong technical readiness ({sw_score:.0f}) but software inventory documentation is incomplete ({sw_completeness:.0f}%)",
            "readiness_dimension": "technical_feasibility",
            "environment_factor": "software_completeness",
        })
    elif sw_score >= SCORE_MODERATE and sw_completeness < SCORE_WEAK:
        gaps.append({
            "category": "software",
            "severity": "medium",
            "description": f"Moderate technical readiness ({sw_score:.0f}) with insufficient software documentation ({sw_completeness:.0f}%)",
            "readiness_dimension": "technical_feasibility",
            "environment_factor": "software_completeness",
        })

    # Hardware risks: low hardware currency score
    hw_currency = env_factors.get("hardware_currency", 0)
    if hw_currency < SCORE_WEAK:
        gaps.append({
            "category": "hardware",
            "severity": "high",
            "description": f"Hardware inventory currency is low ({hw_currency:.0f}%) — potential outdated/unsupported systems",
            "environment_factor": "hardware_currency",
        })
    elif hw_currency < SCORE_MODERATE:
        gaps.append({
            "category": "hardware",
            "severity": "medium",
            "description": f"Hardware inventory currency is moderate ({hw_currency:.0f}%) — review for refresh needs",
            "environment_factor": "hardware_currency",
        })

    # Process compliance: low documentation
    proc_doc = env_factors.get("process_documentation", 0)
    if proc_doc < SCORE_WEAK:
        gaps.append({
            "category": "process",
            "severity": "high",
            "description": f"Process documentation is significantly underdeveloped ({proc_doc:.0f}%)",
            "environment_factor": "process_documentation",
        })
    elif proc_doc < SCORE_MODERATE:
        gaps.append({
            "category": "process",
            "severity": "medium",
            "description": f"Process documentation coverage is moderate ({proc_doc:.0f}%) — gaps in procedures",
            "environment_factor": "process_documentation",
        })

    # General readiness gap: low overall readiness
    if avg_score < SCORE_WEAK:
        gaps.append({
            "category": "readiness",
            "severity": "high",
            "description": f"Organizational readiness is below target ({avg_score:.0f}/100) — foundational improvements needed",
        })
    elif avg_score < SCORE_MODERATE:
        gaps.append({
            "category": "readiness",
            "severity": "medium",
            "description": f"Organizational readiness is moderate ({avg_score:.0f}/100) — targeted improvements can accelerate readiness",
        })

    return gaps


def generate_sales_approach(
    gaps: list[dict[str, Any]],
    risk_factors: list[dict[str, Any]],
    growth_opportunities: list[dict[str, Any]],
    customer_vertical: str | None = None,
) -> dict[str, Any]:
    """Generate sales approach recommendations from gap/risk/growth analysis.

    Returns structured recommendations with messaging, timing, and priorities.
    """
    # Determine priority based on gap severity
    high_gaps = [g for g in gaps if g.get("severity") == "high"]
    medium_gaps = [g for g in gaps if g.get("severity") == "medium"]

    # Determine approach based on gap profile
    if high_gaps:
        urgency = "immediate"
        approach = "remediation-first"
        focus = f"Address {len(high_gaps)} critical gap(s) before pursuing advanced initiatives"
    elif medium_gaps:
        urgency = "near-term"
        approach = "balanced"
        focus = f"Progress on {len(medium_gaps)} moderate gaps while advancing {len(growth_opportunities)} growth opportunity/ies"
    else:
        urgency = "standard"
        approach = "growth-oriented"
        focus = "Customer is well-positioned — focus on advanced capabilities and expansion"

    # Build talking points
    talking_points: list[str] = []
    if high_gaps:
        talking_points.append(f"Priority: {high_gaps[0]['description']}")
    if growth_opportunities:
        talking_points.append(f"Growth: {growth_opportunities[0].get('description', 'Identified expansion opportunities')}")
    if risk_factors:
        talking_points.append(f"Risk mitigation: {risk_factors[0].get('description', 'Risk factors identified and can be addressed')}")

    # Recommended timing
    if urgency == "immediate":
        timing = "Schedule discovery call within 1 week to address critical gaps"
    elif urgency == "near-term":
        timing = "Schedule strategy session within 2-3 weeks to align on roadmap"
    else:
        timing = "Schedule quarterly business review to discuss growth path"

    return {
        "approach": approach,
        "urgency": urgency,
        "focus": focus,
        "talking_points": talking_points,
        "timing": timing,
        "next_steps": [
            f"Review {len(gaps)} identified gap(s) with stakeholder",
            f"Validate {len(risk_factors)} risk factor(s) with technical team",
            f"Prioritize {len(growth_opportunities)} growth opportunity/ies",
            "Schedule follow-up to align on action items",
        ],
    }


def _compute_evaluation_parts(db: Session, customer_id: int) -> dict[str, Any]:
    """Steps 1-7 of the evaluation pipeline (deterministic).

    Shared by create_sales_evaluation (persisted) and
    preview_sales_evaluation (pre-generation view) so the preview and the
    persisted evaluation always agree.
    """
    # ── 1. Organizational readiness (from scoring engine) ──────────────────
    use_cases = db.query(UseCase).filter(
        UseCase.customer_id == customer_id
    ).all()

    scored_ucs = [uc for uc in use_cases if uc.overall_score is not None]
    avg_score = (
        round(sum(uc.overall_score for uc in scored_ucs) / len(scored_ucs), 2)
        if scored_ucs else 0.0
    )

    # Extract dimension averages
    dimensions: dict[str, float] = {}
    for uc in scored_ucs:
        if uc.scores and isinstance(uc.scores, dict):
            for dim_name, dim_score in uc.scores.items():
                if isinstance(dim_score, (int, float)):
                    dimensions[dim_name] = dimensions.get(dim_name, 0.0) + dim_score
    if scored_ucs:
        dimensions = {k: round(v / len(scored_ucs), 2) for k, v in dimensions.items()}

    readiness_data = {
        "average_score": avg_score,
        "dimensions": dimensions,
        "scored_use_cases": len(scored_ucs),
        "total_use_cases": len(use_cases),
    }

    # ── 2. Environment analysis (from knowledge base) ─────────────────────
    env_score, env_factors = compute_environment_score(db, customer_id)

    environment_data = {
        "environment_score": env_score,
        "environment_factors": env_factors,
    }

    # ── 3. Gap analysis ───────────────────────────────────────────────────
    gaps = identify_gaps(readiness_data, environment_data)

    # ── 4. Risk factors ───────────────────────────────────────────────────
    risk_factors: list[dict[str, Any]] = []
    for gap in gaps:
        if gap.get("severity") == "high":
            risk_factors.append({
                "category": gap.get("category", "unknown"),
                "description": f"Risk: {gap['description']}",
                "mitigation": f"Address {gap.get('environment_factor', gap.get('readiness_dimension', 'area'))} through targeted assessment",
            })

    # ── 5. Growth opportunities ───────────────────────────────────────────
    growth_opportunities: list[dict[str, Any]] = []
    if avg_score >= SCORE_MODERATE and env_score >= SCORE_MODERATE:
        growth_opportunities.append({
            "category": "expansion",
            "description": "Both readiness and environment are above threshold — candidate for advanced capabilities and cross-sell",
        })
    if avg_score >= SCORE_STRONG:
        growth_opportunities.append({
            "category": "innovation",
            "description": f"Strong organizational readiness ({avg_score:.0f}) — position for AI/automation innovation",
        })
    if env_score >= SCORE_STRONG:
        growth_opportunities.append({
            "category": "modernization",
            "description": f"Comprehensive environment knowledge ({env_score:.0f}%) — foundation for infrastructure modernization",
        })
    if not growth_opportunities:
        growth_opportunities.append({
            "category": "foundation",
            "description": "Focus on foundational improvements first; growth opportunities will emerge as gaps are addressed",
        })

    # ── 6. Get customer vertical for context ──────────────────────────────
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    vertical = customer.vertical if customer else None

    # ── 7. Generate sales approach ────────────────────────────────────────
    sales_approach = generate_sales_approach(
        gaps=gaps,
        risk_factors=risk_factors,
        growth_opportunities=growth_opportunities,
        customer_vertical=vertical,
    )

    return {
        "use_cases": use_cases,
        "scored_ucs": scored_ucs,
        "avg_score": avg_score,
        "dimensions": dimensions,
        "readiness_data": readiness_data,
        "env_score": env_score,
        "env_factors": env_factors,
        "gaps": gaps,
        "risk_factors": risk_factors,
        "growth_opportunities": growth_opportunities,
        "customer": customer,
        "vertical": vertical,
        "sales_approach": sales_approach,
    }


def create_sales_evaluation(
    db: Session,
    customer_id: int,
    evaluation_name: str,
    persona_id: str | None = None,
) -> SalesEvaluation:
    """Orchestrate a full cross-domain sales evaluation.

    Pulls organizational readiness from scoring engine,
    environment knowledge from knowledge base,
    runs gap/risk/growth analysis,
    persists the result.

    S-A-I-L P5: an optional ``persona_id`` (see backend/services/
    sales_personas.py) tailors the generated sections and is persisted with
    the evaluation so historical evaluations retain their audience context.
    Every evaluation carries source-context provenance (deterministic
    engine; no LLM).
    """
    parts = _compute_evaluation_parts(db, customer_id)
    customer = parts["customer"]
    customer_name = customer.name if customer else f"Customer {customer_id}"

    # ── 8. S-A-I-L P5 — persona + provenance ─────────────────────────────────
    persona = get_persona(persona_id)
    overview = get_customer_overview(db, customer_id)
    competitive_notes = (
        db.query(SalesNote)
        .filter(
            SalesNote.customer_id == customer_id,
            SalesNote.category == "competitive",
        )
        .order_by(SalesNote.id)
        .all()
    )
    source_context = build_source_context(
        overview=overview,
        persona_id=persona_id,
        competitive_notes=competitive_notes,
        parts=parts,
    )
    persona_sections = (
        build_persona_sections(
            customer_name=customer_name,
            vertical=parts["vertical"],
            persona=persona,
            overview=overview,
            parts=parts,
            competitive_notes=competitive_notes,
        )
        if persona is not None
        else None
    )

    # ── 9. Persist evaluation ────────────────────────────────────────────
    now = datetime.now(UTC)
    evaluation = SalesEvaluation(
        customer_id=customer_id,
        evaluation_name=evaluation_name,
        readiness_overall=parts["avg_score"],
        readiness_dimensions=parts["dimensions"],
        environment_score=parts["env_score"],
        environment_factors=parts["env_factors"],
        growth_opportunities=parts["growth_opportunities"],
        risk_factors=parts["risk_factors"],
        sales_approach=parts["sales_approach"],
        persona=persona_id,
        source_context=source_context,
        persona_sections=persona_sections,
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)
    return evaluation


# ── S-A-I-L P5 — persona-driven sections + provenance ────────────────────────────

GENERIC_PERSONA: dict[str, Any] = {
    "id": None,
    "label": "Generic (no persona selected)",
    "description": (
        "Audience-agnostic evaluation. Select a persona for tailored "
        "emphasis, terminology, depth, and questions."
    ),
    "technical_depth": "medium",
    "business_framing": "general business and technical framing",
    "risk_framing": "combined business and operational risk",
    "focus_dimensions": [
        "strategic_fit",
        "technical_feasibility",
        "financial_viability",
        "operational_readiness",
        "risk_tolerance",
        "resource_availability",
    ],
    "concerns": [],
    "question_base": [],
    "priority_angles": [],
    "next_action_angles": [],
}


def build_source_context(
    overview: dict[str, Any],
    persona_id: str | None,
    competitive_notes: list[SalesNote],
    parts: dict[str, Any],
) -> dict[str, Any]:
    """Provenance metadata for a generated evaluation (v2 items 34, 39):
    which sources + indicators the deterministic engine consumed. Never
    contains free text copied from source records (no data leakage into
    provenance) — only counts, ids of at-risk items, and indicator values.
    """
    tech = overview["technology_inventory"]
    notes = overview["sales_notes"]
    ind = overview["indicators"]
    return {
        "method": "deterministic_engine",
        "generated_at": datetime.now(UTC).isoformat(),
        "persona": persona_id,
        "sources": {
            "use_cases_total": len(parts["use_cases"]),
            "use_cases_scored": len(parts["scored_ucs"]),
            "knowledge_entries": overview["customer_knowledge"]["total"],
            "technology_items": tech["total"],
            "sales_notes": notes["total"],
            "competitive_notes": len(competitive_notes),
        },
        "indicators": {
            "readiness_overall": parts["avg_score"],
            "environment_score": parts["env_score"],
            "eol_tech_count": ind["eol_tech_count"],
            "critical_tech_at_risk": [t["name"] for t in tech["critical_tech_at_risk"]],
            "unverified_tech_pct": ind["unverified_tech_pct"],
            "notes_stale": ind["notes_stale"],
            "days_since_latest_note": ind["days_since_latest_note"],
            "gap_count": len(parts["gaps"]),
        },
        "provenance_note": (
            "All generated sections are rule-based inferences derived from the cited "
            "source data (deterministic engine; no LLM). Source records (technology "
            "inventory, sales notes, knowledge documents, use cases) carry their own "
            "verification states; generated content is labeled per section and must "
            "not be treated as verified customer data."
        ),
    }


def _build_evidence_grounded_questions(
    overview: dict[str, Any], customer_name: str
) -> list[str]:
    """Discovery questions grounded in the customer's actual data — including
    explicit questions about missing knowledge (v2 item 35: missing knowledge
    is surfaced as an actionable discovery gap, never fabricated).
    """
    tech = overview["technology_inventory"]
    notes = overview["sales_notes"]
    knowledge = overview["customer_knowledge"]
    ucs = overview["use_cases"]
    q: list[str] = []
    for t in tech["critical_tech_at_risk"][:2]:
        vendor = t.get("vendor") or "unknown vendor"
        lifecycle = t.get("lifecycle_state") or "lifecycle unknown"
        support = t.get("support_state") or "support state unknown"
        q.append(
            f"How is support coverage being maintained for {t['name']} ({vendor}), "
            f"currently {lifecycle} with {support}?"
        )
    if tech["eol_count"] > 0:
        q.append(
            f"Of the {tech['eol_count']} technology item(s) at or past "
            "end-of-life, which are business-critical and what is the "
            "replacement plan?"
        )
    if notes["total"] == 0:
        q.append(
            "No sales notes have been recorded for this account yet — "
            "what should we capture first?"
        )
    elif notes["notes_stale"]:
        q.append(
            f"The most recent recorded note is "
            f"{notes['days_since_latest_note']} days old — what has changed "
            "in the account since then?"
        )
    if knowledge["total"] == 0:
        q.append(
            f"No documents have been uploaded for {customer_name} — which "
            "internal documents (architecture, inventory, runbooks) could "
            "we review together?"
        )
    if ucs["total"] > 0 and ucs["scored_count"] == 0:
        q.append(
            f"{ucs['total']} use case(s) exist but none are scored yet — "
            "which should be scored first?"
        )
    return q


def build_persona_sections(
    customer_name: str,
    vertical: str | None,
    persona: dict[str, Any],
    overview: dict[str, Any],
    parts: dict[str, Any],
    competitive_notes: list[SalesNote],
) -> dict[str, Any]:
    """Build the persona-tailored section set (v2 item 33).

    Deterministic. Every section carries a label describing its epistemic
    status (evidence-based / derived / inference / discovery-needed) and
    evidence references where applicable (v2 items 34, 39). Missing
    knowledge is surfaced as an actionable discovery gap (v2 item 35).
    """
    tech = overview["technology_inventory"]
    notes = overview["sales_notes"]
    ucs = overview["use_cases"]
    knowledge = overview["customer_knowledge"]
    gaps = parts["gaps"]

    # Persona-relevance tagging on gaps (deterministic membership test)
    focus_dims = set(persona.get("focus_dimensions", []))
    gaps_tagged = [
        {**g, "persona_relevant": g.get("readiness_dimension") in focus_dims}
        for g in gaps
    ]

    # Competitive considerations — strictly evidence-based (v2 item 34)
    competitive = [
        {
            "id": n.id,
            "title": n.title,
            "note_date": n.note_date.isoformat() if n.note_date else None,
            "verification_state": n.verification_state,
            "content_excerpt": (
                n.content[:200] + "…" if len(n.content or "") > 200 else (n.content or "")
            ),
        }
        for n in competitive_notes
    ]

    # Recommended solutions — each cites evidence or is labeled hypothesis
    recommendations: list[dict[str, Any]] = []
    for g in gaps:
        recommendations.append(
            {
                "recommendation": (
                    f"Address {g.get('category', 'unclassified')} gap: {g['description']}"
                ),
                "evidence": [
                    g.get("readiness_dimension"),
                    g.get("environment_factor"),
                ],
                "hypothesis": False,
            }
        )
    for opp in parts["growth_opportunities"]:
        recommendations.append(
            {
                "recommendation": (
                    f"Pursue {opp.get('category', 'growth')} opportunity: "
                    f"{opp.get('description', '')}"
                ),
                "evidence": ["scored use cases", "environment score"],
                "hypothesis": False,
            }
        )
    for angle in persona.get("priority_angles", []):
        if not any(
            angle.lower() in r["recommendation"].lower() for r in recommendations
        ):
            recommendations.append(
                {
                    "recommendation": (
                        f"Explore with the {persona.get('label', 'audience')}: {angle}"
                    ),
                    "evidence": [],
                    "hypothesis": True,
                }
            )

    # Discovery gaps — missing knowledge surfaced as actionable (v2 35)
    discovery_gaps: list[dict[str, Any]] = []
    if tech["total"] == 0:
        discovery_gaps.append(
            {
                "area": "technology_inventory",
                "gap": "No technology inventory recorded for this customer",
                "action": (
                    "Run an inventory discovery session to capture the "
                    "current technology estate"
                ),
            }
        )
    elif (tech["unverified_pct"] or 0) >= 50:
        discovery_gaps.append(
            {
                "area": "technology_verification",
                "gap": (
                    f"{tech['unverified_pct']}% of technology inventory "
                    "items are not verified"
                ),
                "action": "Verify inventory details with the customer's technical team",
            }
        )
    if notes["total"] == 0:
        discovery_gaps.append(
            {
                "area": "sales_notes",
                "gap": "No sales notes recorded for this account",
                "action": "Record the next discovery/meeting as a structured sales note",
            }
        )
    elif notes["notes_stale"]:
        discovery_gaps.append(
            {
                "area": "sales_notes_freshness",
                "gap": (
                    f"Most recent note is {notes['days_since_latest_note']} "
                    "days old (stale)"
                ),
                "action": "Schedule a check-in to refresh account intelligence",
            }
        )
    if knowledge["total"] == 0:
        discovery_gaps.append(
            {
                "area": "customer_knowledge",
                "gap": "No knowledge documents uploaded for this customer",
                "action": (
                    "Request or collect architecture, inventory, and process "
                    "documentation"
                ),
            }
        )
    if tech["total"] > 0 and not competitive_notes:
        discovery_gaps.append(
            {
                "area": "competitive_intelligence",
                "gap": "No competitive intelligence recorded",
                "action": "Capture competitor mentions from the next customer conversation",
            }
        )

    sections: dict[str, Any] = {
        "account_snapshot": {
            "label": "derived — deterministic aggregation of customer master data + P4 overview",
            "content": {
                "customer": customer_name,
                "vertical": vertical,
                "readiness_overall": parts["avg_score"],
                "environment_score": parts["env_score"],
                "technology_items": tech["total"],
                "eol_items": tech["eol_count"],
                "sales_notes": notes["total"],
                "use_cases": ucs["total"],
            },
        },
        "relevant_environment": {
            "label": "evidence-based — environment scoring (knowledge base) + technology inventory",
            "content": {
                "environment_factors": parts["env_factors"],
                "technology_by_category": tech["by_category"],
                "eol_items": tech["eol_count"],
                "critical_tech_at_risk": tech["critical_tech_at_risk"],
                "unverified_tech_pct": tech["unverified_pct"],
            },
        },
        "business_technical_priorities": {
            "label": "inference (rule-based) — persona lens applied to gaps + readiness dimensions",
            "content": {
                "persona": persona.get("label"),
                "framing": persona.get("business_framing"),
                "concerns": persona.get("concerns", []),
                "focus_dimension_scores": {
                    d: parts["dimensions"].get(d)
                    for d in persona.get("focus_dimensions", [])
                    if d in parts["dimensions"]
                },
                "priority_angles": persona.get("priority_angles", []),
            },
        },
        "observed_gaps": {
            "label": "evidence-based — rule-based comparison of readiness vs environment",
            "content": gaps_tagged,
        },
        "growth_opportunities": {
            "label": "inference (rule-based) — scored thresholds + environment triggers",
            "content": parts["growth_opportunities"],
            "persona_framing": persona.get("business_framing"),
        },
        "risks": {
            "label": "evidence-based — high-severity gaps + persona risk framing",
            "content": parts["risk_factors"],
            "risk_framing": persona.get("risk_framing"),
        },
        "competitive_considerations": {
            "label": (
                "evidence-based — recorded competitive intelligence (sales notes, category=competitive)"
                if competitive
                else "discovery needed — no competitive intelligence recorded"
            ),
            "content": (
                {"notes": competitive}
                if competitive
                else {
                    "recorded": False,
                    "action": (
                        "Capture competitor mentions from the next customer "
                        "conversation (sales note, category=competitive)"
                    ),
                }
            ),
        },
        "recommended_solutions": {
            "label": (
                "inference — each recommendation cites evidence or is "
                "explicitly marked as a hypothesis requiring discovery"
            ),
            "content": recommendations,
        },
        "discovery_questions": {
            "label": "persona base + evidence-grounded discovery questions",
            "content": {
                "persona_questions": persona.get("question_base", []),
                "evidence_grounded_questions": _build_evidence_grounded_questions(
                    overview, customer_name
                ),
            },
        },
        "suggested_next_actions": {
            "label": "persona angles + engine-derived next steps",
            "content": {
                "persona_angles": persona.get("next_action_angles", []),
                "next_steps": parts["sales_approach"].get("next_steps", []),
            },
        },
    }

    return {
        "persona": persona.get("id"),
        "persona_label": persona.get("label"),
        "persona_description": persona.get("description"),
        "technical_depth": persona.get("technical_depth"),
        "business_framing": persona.get("business_framing"),
        "risk_framing": persona.get("risk_framing"),
        "sections": sections,
        "discovery_gaps": discovery_gaps,
    }


def preview_sales_evaluation(
    db: Session,
    customer_id: int,
    persona_id: str | None = None,
) -> dict[str, Any]:
    """Pre-generation view (v2 item 32): the selected customer, the persona,
    the related available intelligence, and the generation intent — computed
    without persisting anything. Mirrors create_sales_evaluation exactly
    (same _compute_evaluation_parts + build_persona_sections) so the preview
    and the persisted evaluation always agree.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if customer is None:
        raise ValueError("Customer not found")
    persona = get_persona(persona_id) or GENERIC_PERSONA
    parts = _compute_evaluation_parts(db, customer_id)
    overview = get_customer_overview(db, customer_id)
    competitive_notes = (
        db.query(SalesNote)
        .filter(
            SalesNote.customer_id == customer_id,
            SalesNote.category == "competitive",
        )
        .order_by(SalesNote.id)
        .all()
    )
    built = build_persona_sections(
        customer_name=customer.name,
        vertical=customer.vertical,
        persona=persona,
        overview=overview,
        parts=parts,
        competitive_notes=competitive_notes,
    )
    return {
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "vertical": customer.vertical,
        },
        "persona": persona,
        "available_intelligence": {
            "technology_items": overview["technology_inventory"]["total"],
            "sales_notes": overview["sales_notes"]["total"],
            "knowledge_entries": overview["customer_knowledge"]["total"],
            "use_cases": {
                "total": overview["use_cases"]["total"],
                "scored": overview["use_cases"]["scored_count"],
            },
            "eol_tech_count": overview["indicators"]["eol_tech_count"],
            "critical_tech_at_risk_count": overview["indicators"]["critical_tech_at_risk_count"],
            "notes_stale": overview["indicators"]["notes_stale"],
        },
        "generation_intent": (
            f"Deterministic, rule-based sales evaluation for {customer.name}, "
            f"framed for {persona['label']}; no LLM inference — sections are "
            "labeled by epistemic status and recommendations cite evidence "
            "or are marked as hypotheses."
        ),
        "sections": built["sections"],
        "discovery_gaps": built["discovery_gaps"],
        "source_context": build_source_context(
            overview=overview,
            persona_id=persona_id,
            competitive_notes=competitive_notes,
            parts=parts,
        ),
    }
