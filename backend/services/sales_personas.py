"""Sales persona registry (S-A-I-L P5).

Central, deterministic registry of buyer personas for persona-driven
Sales Evaluations (CHANGELOG 0.0.80 items 27-35).

Design constraints (charter + v2 plan):
- Centrally maintained: this module (plus the GET /api/sales-evaluations/personas/
  endpoint) is the single source of persona definitions — the frontend and the
  evaluation engine consume it; persona behavior is never hardcoded separately
  in frontend or route code (v2 item 30).
- Deterministic: pure data + rule-based selection. No LLM in this module.
- Extensible: adding a persona = appending one entry to PERSONAS.
- Persona selection must materially change emphasis, terminology, depth,
  business/risk framing, recommended questions, and next actions (v2 item 29) —
  each persona defines its own focus_dimensions, concerns, question base,
  priority and next-action angles.

The minimum persona set required by v2 item 28:
Executive/Business Leader, CIO/CTO, Infrastructure/Platform Leader,
Security Leader, Data/AI Leader, Application/Development Leader,
IT Operations Leader, Technical Architect/Engineer.
"""

from typing import Any

# The six readiness dimensions produced by the scoring engine
# (see backend/schemas/sales_evaluation.py ReadinessDimensions).
READINESS_DIMENSIONS = [
    "strategic_fit",
    "technical_feasibility",
    "financial_viability",
    "operational_readiness",
    "risk_tolerance",
    "resource_availability",
]

PERSONAS: dict[str, dict[str, Any]] = {
    "executive": {
        "id": "executive",
        "label": "Executive / Business Leader",
        "description": (
            "C-suite / business executive. Cares about outcomes, ROI, risk "
            "exposure, and strategic alignment; technical detail is secondary "
            "to business impact."
        ),
        "technical_depth": "low",
        "business_framing": "business outcomes, cost exposure, and strategic advantage",
        "risk_framing": "business exposure — financial, reputational, and strategic risk",
        "focus_dimensions": ["strategic_fit", "financial_viability"],
        "concerns": [
            "Is the current investment protected, and what is the exposure if the environment is not modernized?",
            "What does this mean for the strategic roadmap and the upcoming budget cycle?",
            "What is the cost of inaction versus the cost of action?",
        ],
        "question_base": [
            "Which business outcomes would leadership prioritize if modernization were funded this year?",
            "How is infrastructure risk currently reported to the executive team?",
            "What would a 'success' look like for this initiative at the end of next fiscal year?",
        ],
        "priority_angles": [
            "ROI and business-case framing",
            "Executive sponsor alignment",
            "Budget-cycle timing",
        ],
        "next_action_angles": [
            "Request an executive business-case session",
            "Align on investment timeline and funding source",
            "Identify and confirm the executive sponsor",
        ],
    },
    "cio_cto": {
        "id": "cio_cto",
        "label": "CIO / CTO",
        "description": (
            "Strategic technology leader. Owns the technology portfolio, vendor "
            "strategy, and the balance between innovation and operational stability."
        ),
        "technical_depth": "high",
        "business_framing": "technology portfolio strategy and capital allocation",
        "risk_framing": "portfolio risk — aging platforms, vendor lock-in, and support coverage",
        "focus_dimensions": ["strategic_fit", "technical_feasibility", "resource_availability"],
        "concerns": [
            "Which parts of the technology portfolio are end-of-life and what is the replacement strategy?",
            "How much of the technology budget is consumed by legacy support?",
            "Is the vendor base aligned with the three-year technology roadmap?",
        ],
        "question_base": [
            "Which platforms on the roadmap depend on the current virtualization/infrastructure stack?",
            "How are refresh decisions currently prioritized across the portfolio?",
            "What is the target state for infrastructure in 24 months?",
        ],
        "priority_angles": [
            "Portfolio modernization roadmap",
            "Vendor strategy and lock-in reduction",
            "Budget reallocation from support to innovation",
        ],
        "next_action_angles": [
            "Schedule a portfolio review with the platform teams",
            "Map EOL items to the 3-year roadmap",
            "Agree on a reference architecture for the target state",
        ],
    },
    "infrastructure": {
        "id": "infrastructure",
        "label": "Infrastructure / Platform Leader",
        "description": (
            "Owns the infrastructure and platform estate: virtualization, "
            "compute, storage, networking. Cares about stability, capacity, "
            "lifecycle, and operational burden."
        ),
        "technical_depth": "high",
        "business_framing": "platform stability, capacity, and lifecycle management",
        "risk_framing": "operational risk — EOL components, capacity limits, and support gaps",
        "focus_dimensions": ["technical_feasibility", "operational_readiness", "resource_availability"],
        "concerns": [
            "Which infrastructure components are at or past end-of-life?",
            "Is capacity headroom sufficient for growth without a refresh?",
            "What is the operational burden of maintaining legacy components?",
        ],
        "question_base": [
            "What is the current refresh cycle for compute and storage hardware?",
            "How are capacity limits currently monitored and reported?",
            "What would an infrastructure refresh look like operationally (downtime windows, migrations)?",
        ],
        "priority_angles": [
            "EOL remediation and lifecycle management",
            "Capacity and performance headroom",
            "Operational simplification and automation",
        ],
        "next_action_angles": [
            "Walk through the infrastructure estate with the platform team",
            "Prioritize EOL components by business criticality",
            "Define a migration/refresh plan with downtime constraints",
        ],
    },
    "security": {
        "id": "security",
        "label": "Security Leader",
        "description": (
            "CISO / security architect. Cares about security posture, compliance "
            "obligations, and the security implications of the technology estate."
        ),
        "technical_depth": "high",
        "business_framing": "security posture and compliance obligation",
        "risk_framing": "security and compliance risk — unpatched/EOL components and audit exposure",
        "focus_dimensions": ["risk_tolerance", "technical_feasibility"],
        "concerns": [
            "Which EOL components no longer receive security patches?",
            "Are there compliance obligations (SOX, HIPAA, PCI, ISO 27001) affected by the current estate?",
            "How is the security posture of legacy systems documented for audits?",
        ],
        "question_base": [
            "How are security exceptions for legacy systems tracked and approved?",
            "What compliance frameworks apply to the infrastructure being discussed?",
            "How would a refresh change the security architecture (network segmentation, identity)?",
        ],
        "priority_angles": [
            "Eliminating unpatched/EOL components",
            "Compliance documentation and audit readiness",
            "Security architecture in the target state",
        ],
        "next_action_angles": [
            "Review the security exception list for legacy components",
            "Map EOL items to compliance obligations",
            "Engage the security team on the target-state architecture",
        ],
    },
    "data_ai": {
        "id": "data_ai",
        "label": "Data / AI Leader",
        "description": (
            "Owns data platforms and AI/ML initiatives. Cares about data access, "
            "platform readiness for analytics/AI, and innovation enablement."
        ),
        "technical_depth": "high",
        "business_framing": "data platform readiness and AI/innovation enablement",
        "risk_framing": "innovation risk — aging platforms that block data/AI initiatives",
        "focus_dimensions": ["technical_feasibility", "strategic_fit", "resource_availability"],
        "concerns": [
            "Does the current platform support the data volumes and latency needs of analytics/AI?",
            "Which data initiatives are blocked or slowed by the current infrastructure?",
            "Is there a reference architecture for data/AI workloads?",
        ],
        "question_base": [
            "Which data/AI initiatives are planned for the next 12-24 months?",
            "Where do data pipelines currently experience platform constraints?",
            "How is GPU/compute capacity for AI workloads being planned?",
        ],
        "priority_angles": [
            "Platform readiness for data/AI workloads",
            "Unblocking innovation initiatives",
            "Reference architecture for modern data stacks",
        ],
        "next_action_angles": [
            "Map planned data/AI initiatives to platform requirements",
            "Identify the platform constraints blocking the top initiatives",
            "Agree on a target architecture for data/AI workloads",
        ],
    },
    "application": {
        "id": "application",
        "label": "Application / Development Leader",
        "description": (
            "Owns application portfolios and development teams. Cares about "
            "application modernization, developer experience, and delivery velocity."
        ),
        "technical_depth": "high",
        "business_framing": "application portfolio modernization and delivery velocity",
        "risk_framing": "delivery risk — legacy platforms slowing application delivery",
        "focus_dimensions": ["technical_feasibility", "operational_readiness", "resource_availability"],
        "concerns": [
            "Which applications are constrained by the current infrastructure?",
            "How does the platform affect development velocity and deployment frequency?",
            "Is there a modern application platform (containers, IaC) in place or planned?",
        ],
        "question_base": [
            "Which applications are candidates for modernization first, and why?",
            "How are CI/CD pipelines currently supported by the infrastructure?",
            "What developer-experience pain points does the current platform cause?",
        ],
        "priority_angles": [
            "Application modernization sequencing",
            "Developer experience and delivery velocity",
            "Platform enablement (containers, IaC, observability)",
        ],
        "next_action_angles": [
            "Prioritize the application modernization backlog",
            "Review the CI/CD and deployment tooling estate",
            "Agree on platform enablement requirements for the top applications",
        ],
    },
    "it_operations": {
        "id": "it_operations",
        "label": "IT Operations Leader",
        "description": (
            "Runs day-to-day IT operations. Cares about stability, on-call "
            "burden, tooling, incident reduction, and run-cost."
        ),
        "technical_depth": "medium",
        "business_framing": "operational stability and run-cost reduction",
        "risk_framing": "operational risk — incidents, toil, and coverage gaps",
        "focus_dimensions": ["operational_readiness", "resource_availability", "risk_tolerance"],
        "concerns": [
            "Which components drive the most incidents and on-call pages?",
            "How much manual toil is consumed maintaining legacy systems?",
            "What tooling is missing for observability and automation?",
        ],
        "question_base": [
            "What does the incident profile look like for the current estate (top recurring issues)?",
            "How is capacity and performance monitored day-to-day?",
            "What operational automation would have the highest impact if funded first?",
        ],
        "priority_angles": [
            "Incident reduction and on-call burden",
            "Operational automation and tooling",
            "Run-cost optimization",
        ],
        "next_action_angles": [
            "Review the top recurring incidents with the ops team",
            "Quantify the toil consumed by legacy components",
            "Prioritize automation by operational impact",
        ],
    },
    "architect": {
        "id": "architect",
        "label": "Technical Architect / Engineer",
        "description": (
            "Deep technical counterpart. Cares about architecture patterns, "
            "integration, performance, and the technical detail of a migration."
        ),
        "technical_depth": "high",
        "business_framing": "technical fit, integration, and migration feasibility",
        "risk_framing": "technical risk — integration complexity, performance regressions, migration cutover",
        "focus_dimensions": ["technical_feasibility", "operational_readiness", "resource_availability"],
        "concerns": [
            "What are the integration and dependency constraints of the current stack?",
            "What are the performance and latency requirements for the target state?",
            "What is the migration cutover strategy and rollback plan?",
        ],
        "question_base": [
            "Which dependencies (network, storage, identity) constrain the migration approach?",
            "What are the non-functional requirements (latency, availability, RPO/RTO) for critical workloads?",
            "What has been evaluated for the target architecture and what was rejected, and why?",
        ],
        "priority_angles": [
            "Architecture fit and integration strategy",
            "Non-functional requirements and cutover risk",
            "Migration patterns and rollback strategy",
        ],
        "next_action_angles": [
            "Run a technical deep-dive on the critical workloads",
            "Map dependencies and constraints of the current stack",
            "Draft the migration/rollback strategy for the top workload",
        ],
    },
}

# Ordered list for stable presentation (registry endpoint, UI selects).
PERSONA_ORDER = [
    "executive",
    "cio_cto",
    "infrastructure",
    "security",
    "data_ai",
    "application",
    "it_operations",
    "architect",
]


def get_persona(persona_id: str | None) -> dict[str, Any] | None:
    """Return the persona definition, or None when unknown/absent."""
    if not persona_id:
        return None
    return PERSONAS.get(persona_id)


def list_personas() -> list[dict[str, Any]]:
    """Return all personas in stable registry order."""
    return [PERSONAS[pid] for pid in PERSONA_ORDER if pid in PERSONAS]


def validate_persona(persona_id: str | None) -> str | None:
    """Return an error message when persona_id is set but unknown, else None."""
    if persona_id is None:
        return None
    if get_persona(persona_id) is None:
        valid = ", ".join(PERSONA_ORDER)
        return f"Unknown persona '{persona_id}'. Valid personas: {valid}"
    return None
