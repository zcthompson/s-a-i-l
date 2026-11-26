"""Canonical AI use-case template registry (WP19).

Single source of truth for all assessment templates. Consolidates the
four generic department templates that used to live in
``backend/routes/bulk.py`` with the seven rich templates that used to
live in ``frontend/src/data/templates.ts`` (moved here verbatim).

Every entry has the same shape::

    id, name, icon, default_department, description, default_title,
    default_goals, default_challenges, default_pain_points,
    impact_category, impact_description, timeline

The wire contract served by ``/api/bulk/templates/`` keeps every key the
old four-template registry exposed (``name``, ``default_department``,
``default_goals``, ``default_challenges``, ``default_pain_points``) and
only ADDS keys — existing consumers are unaffected.
"""

from __future__ import annotations

TEMPLATES: dict[str, dict] = {
    # ── Generic department templates (enriched, deterministic prose) ──────
    "operations": {
        "id": "operations",
        "name": "Operations Template",
        "icon": "⚙️",
        "default_department": "Operations",
        "description": (
            "Assess where AI can streamline core operational workflows — "
            "automating manual hand-offs, standardizing quality checks, and "
            "surfacing bottlenecks before they cascade."
        ),
        "default_title": "Operational Efficiency Assessment",
        "default_goals": [
            "Improve operational efficiency",
            "Reduce costs",
            "Enhance quality and consistency",
        ],
        "default_challenges": [
            "Legacy systems and processes",
            "Data silos and integration issues",
            "Change management and adoption",
        ],
        "default_pain_points": [
            "Manual processes causing bottlenecks",
            "High operational costs",
            "Quality inconsistencies",
        ],
        "impact_category": "Efficiency",
        "impact_description": (
            "Operational AI reduces manual processing time, lowers unit "
            "costs, and improves output consistency across the value chain."
        ),
        "timeline": "Short-term (3-6 months)",
    },
    "finance": {
        "id": "finance",
        "name": "Finance Template",
        "icon": "💰",
        "default_department": "Finance",
        "description": (
            "Assess AI opportunities across financial close, forecasting, "
            "and controls — cutting reconciliation effort and tightening "
            "compliance without adding headcount."
        ),
        "default_title": "Finance Automation Assessment",
        "default_goals": [
            "Improve financial accuracy and forecasting",
            "Reduce processing time",
            "Enhance compliance and risk management",
        ],
        "default_challenges": [
            "Complex regulatory requirements",
            "Legacy financial systems",
            "Data accuracy and reconciliation",
        ],
        "default_pain_points": [
            "Slow month-end closing processes",
            "High manual reconciliation effort",
            "Compliance audit risks",
        ],
        "impact_category": "Efficiency",
        "impact_description": (
            "Finance AI shortens the close cycle, improves forecast "
            "accuracy, and reduces audit findings through continuous "
            "control monitoring."
        ),
        "timeline": "Medium-term (6-12 months)",
    },
    "hr": {
        "id": "hr",
        "name": "HR Template",
        "icon": "👥",
        "default_department": "HR",
        "description": (
            "Assess where AI can improve the employee lifecycle — faster, "
            "fairer hiring, better retention signals, and targeted "
            "skills-gap analysis."
        ),
        "default_title": "HR & Talent Assessment",
        "default_goals": [
            "Improve employee experience",
            "Reduce time-to-hire",
            "Enhance retention and engagement",
        ],
        "default_challenges": [
            "Diverse candidate evaluation",
            "Training effectiveness measurement",
            "Employee data quality",
        ],
        "default_pain_points": [
            "High turnover rates",
            "Inefficient recruitment processes",
            "Skills gap identification",
        ],
        "impact_category": "Efficiency",
        "impact_description": (
            "HR AI reduces time-to-hire, improves retention through early "
            "attrition signals, and targets training spend at real skills "
            "gaps."
        ),
        "timeline": "Medium-term (6-12 months)",
    },
    "customer_success": {
        "id": "customer_success",
        "name": "Customer Success Template",
        "icon": "🤝",
        "default_department": "Customer Success",
        "description": (
            "Assess AI opportunities in support and retention — deflecting "
            "repetitive tickets, personalizing outreach at scale, and "
            "turning feedback into action."
        ),
        "default_title": "Customer Success Assessment",
        "default_goals": [
            "Improve customer satisfaction",
            "Reduce support costs",
            "Increase customer lifetime value",
        ],
        "default_challenges": [
            "Scaling support operations",
            "Personalization at scale",
            "Customer feedback analysis",
        ],
        "default_pain_points": [
            "Long response times",
            "High volume of repetitive tickets",
            "Inconsistent customer experience",
        ],
        "impact_category": "Efficiency",
        "impact_description": (
            "Customer Success AI cuts response times, deflects repetitive "
            "tickets, and lifts retention through consistent, personalized "
            "engagement."
        ),
        "timeline": "Short-term (3-6 months)",
    },
    # ── Rich templates (verbatim from frontend/src/data/templates.ts) ────
    "customer-support": {
        "id": "customer-support",
        "name": "AI-Powered Customer Support",
        "icon": "🤖",
        "default_department": "Customer Success",
        "description": (
            "Deploy AI assistants and chatbots to handle tier-1 support, "
            "automate ticket routing, search knowledge bases, and provide "
            "24/7 multilingual support coverage."
        ),
        "default_title": "AI-Powered Customer Support Automation",
        "default_goals": [
            "Reduce average ticket resolution time from hours to minutes for tier-1 issues",
            "Achieve 24/7 multilingual support coverage without staffing increases",
            "Improve customer satisfaction (CSAT) scores by providing instant, accurate responses",
            "Free human agents to focus on complex, high-value interactions",
        ],
        "default_challenges": [
            "Handling edge-case and highly complex customer queries that require human judgment",
            "Maintaining consistent brand voice and quality across AI-generated responses",
            "Integrating with existing CRM, ticketing, and knowledge base systems",
            "Managing customer expectations about AI capabilities and limitations",
        ],
        "default_pain_points": [
            "Long wait times and response delays during peak support hours",
            "High agent turnover leading to training overhead and inconsistent service quality",
            "Inconsistent answers from different agents on the same issue",
            "Manual triage and routing consuming 30%+ of agent time",
        ],
        "impact_category": "Efficiency",
        "impact_description": (
            "AI-driven customer support reduces first-response time by 80%+, "
            "cuts tier-1 ticket volume handled by humans by 40-60%, and "
            "improves CSAT through consistent, instant responses."
        ),
        "timeline": "Short-term (3-6 months)",
    },
    "demand-forecasting": {
        "id": "demand-forecasting",
        "name": "Demand Forecasting & Inventory Optimization",
        "icon": "📦",
        "default_department": "Operations",
        "description": (
            "Build predictive models that forecast product demand at "
            "SKU/store level, optimize stock replenishment, reduce waste "
            "and stockouts, and enable proactive supply chain decisions."
        ),
        "default_title": "Demand Forecasting & Inventory Optimization",
        "default_goals": [
            "Achieve sub-10% forecasting error for top-200 SKUs to reduce safety stock needs",
            "Minimize stockouts for high-demand products to prevent lost sales",
            "Reduce excess and obsolete inventory by 25%+ to free working capital",
            "Enable proactive replenishment with automated reorder recommendations",
        ],
        "default_challenges": [
            "Ensuring data quality and completeness from multiple sources (POS, ERP, weather, promotions)",
            "Accounting for seasonality, promotions, and external factors (holidays, trends)",
            "Managing supply chain volatility from suppliers, logistics, and geopolitics",
            "Balancing service level targets with inventory cost constraints",
        ],
        "default_pain_points": [
            "Overstock situations tying up capital and increasing carrying costs and waste",
            "Understock/stockout situations leading to lost sales and customer dissatisfaction",
            "Manual, spreadsheet-based forecasting that is slow, error-prone, and lacks accuracy",
            "Reactive rather than proactive inventory planning",
        ],
        "impact_category": "Cost Reduction",
        "impact_description": (
            "AI demand forecasting reduces inventory holding costs by "
            "15-30%, cuts stockout-related revenue loss by 20-40%, and "
            "improves cash flow by optimizing working capital allocation."
        ),
        "timeline": "Medium-term (6-12 months)",
    },
    "fraud-detection": {
        "id": "fraud-detection",
        "name": "Fraud Detection & Anomaly Monitoring",
        "icon": "🛡️",
        "default_department": "Finance",
        "description": (
            "Implement real-time transaction monitoring and anomaly "
            "detection to identify fraudulent activity, suspicious "
            "patterns, and compliance violations with automated alerting "
            "and escalation."
        ),
        "default_title": "Real-Time Fraud Detection & Anomaly Monitoring",
        "default_goals": [
            "Detect and flag fraudulent transactions within seconds of occurrence",
            "Reduce false positive rate below 5% to minimize unnecessary customer friction",
            "Ensure compliance with AML, KYC, and regulatory reporting requirements",
            "Continuously adapt detection models as fraud patterns evolve",
        ],
        "default_challenges": [
            "Evolving and increasingly sophisticated fraud patterns that require continuous model retraining",
            "Meeting data privacy and security requirements for sensitive financial data",
            "Balancing detection sensitivity with false positive rates (avoiding customer friction)",
            "Ensuring model explainability for regulatory audits and dispute resolution",
        ],
        "default_pain_points": [
            "Manual review bottleneck creating delays in transaction processing",
            "Missed fraud cases leading to financial losses and regulatory penalties",
            "High false positive rates causing customer dissatisfaction and support overhead",
            "Late detection of fraud patterns after significant losses have occurred",
        ],
        "impact_category": "Risk Mitigation",
        "impact_description": (
            "AI-driven fraud detection reduces fraud losses by 40-60%, cuts "
            "manual review workload by 70%+, and ensures regulatory "
            "compliance through automated audit trails and real-time "
            "monitoring."
        ),
        "timeline": "Medium-term (6-12 months)",
    },
    "marketing-personalization": {
        "id": "marketing-personalization",
        "name": "AI Marketing Personalization & Campaign Optimization",
        "icon": "🎯",
        "default_department": "Marketing",
        "description": (
            "Deploy machine-learning personalization engines to segment "
            "audiences in real time, optimize campaign targeting and "
            "creative selection, predict customer lifetime value, and "
            "automate multi-channel messaging at scale."
        ),
        "default_title": "AI Marketing Personalization & Campaign Optimization",
        "default_goals": [
            "Lift campaign click-through and conversion rates 15-35% via real-time personalization",
            "Improve marketing ROI by shifting budget toward high-LTV segments",
            "Cut manual campaign setup time with AI-assisted creative and copy generation",
            "Deliver consistent cross-channel messaging through automated content adaptation",
        ],
        "default_challenges": [
            "Integrating CDP, CRM, and web analytics data into a unified real-time profile",
            "Avoiding customer fatigue and privacy concerns with hyper-personalization",
            "Measuring incremental lift with multi-touch attribution across channels",
            "Balancing creative control between marketing teams and automated systems",
        ],
        "default_pain_points": [
            "One-size-fits-all campaigns underperforming across distinct segments",
            "Manual A/B testing that is slow and limited to a handful of variables",
            "Marketing data scattered across platforms with no unified view",
            "Rising cost per acquisition as channel efficiency declines",
        ],
        "impact_category": "Revenue Growth",
        "impact_description": (
            "AI-driven personalization lifts campaign conversion by 15-35%, "
            "reduces cost per acquisition by 20-40%, and improves customer "
            "lifetime value through lifecycle-optimized messaging."
        ),
        "timeline": "Medium-term (6-12 months)",
    },
    "sales-lead-scoring": {
        "id": "sales-lead-scoring",
        "name": "AI Sales Lead Scoring & Pipeline Forecasting",
        "icon": "📈",
        "default_department": "Sales",
        "description": (
            "Implement predictive lead scoring and pipeline forecasting to "
            "prioritize high-intent prospects, automate sales activity "
            "routing, forecast quarter-end numbers with statistical "
            "confidence, and coach reps with AI-generated insights."
        ),
        "default_title": "AI Sales Lead Scoring & Pipeline Forecasting",
        "default_goals": [
            "Identify and prioritize high-intent leads to lift close rates by 20%+",
            "Improve forecast accuracy to within 5% of actual quarter-end revenue",
            "Reduce time spent on low-value prospects and unproductive activities",
            "Give sales leadership real-time pipeline health and at-risk deal alerts",
        ],
        "default_challenges": [
            "Capturing quality CRM hygiene and activity data from sales reps",
            "Preventing model drift as market and product mix shifts",
            "Integrating CRM, ERP, and engagement tooling without breaking workflows",
            "Ensuring model explanations are trustworthy enough to earn rep adoption",
        ],
        "default_pain_points": [
            "Rep time spent on low-intent leads while hot opportunities go stale",
            "Gut-feel forecasting that systematically misses or over-books the number",
            "No visibility into which deal attributes actually predict closure",
            "Manual pipeline review consuming hours in sales calls",
        ],
        "impact_category": "Revenue Growth",
        "impact_description": (
            "AI lead scoring lifts conversion rates by 20-35%, improves "
            "forecast accuracy by 5-10 points, and shortens sales cycles by "
            "focusing reps on the deals most likely to close."
        ),
        "timeline": "Medium-term (6-12 months)",
    },
    "aiops-incident": {
        "id": "aiops-incident",
        "name": "AIOps: IT Operations, Monitoring & Incident Response",
        "icon": "🖥️",
        "default_department": "IT",
        "description": (
            "Apply machine learning to operational telemetry (logs, "
            "metrics, traces) for anomaly detection, root cause analysis, "
            "automated incident response, and predictive capacity planning "
            "to reduce MTTR and prevent outages."
        ),
        "default_title": "AIOps: IT Operations, Monitoring & Incident Response",
        "default_goals": [
            "Reduce mean time to detect and resolve incidents (MTTD/MTTR) by 50%+",
            "Cut alert noise by auto-correlating and deduplicating related signals",
            "Shift from reactive firefighting to predictive maintenance of infrastructure",
            "Improve capacity planning accuracy to avoid outages and over-provisioning",
        ],
        "default_challenges": [
            "Ingesting and normalizing telemetry from heterogeneous tooling and estates",
            "Avoiding alert fatigue from over-sensitive anomaly thresholds",
            "Maintaining runbook and automation coverage as the estate evolves",
            "Governance for automated remediation actions in production",
        ],
        "default_pain_points": [
            "24/7 on-call burden with high-frequency, low-value pages",
            "Slow root cause analysis across distributed systems",
            "Surprise outages from capacity or configuration drift",
            "Manual incident triage delaying recovery and increasing MTTD",
        ],
        "impact_category": "Efficiency",
        "impact_description": (
            "AIOps reduces MTTR by 40-60%, cuts alert volume by 70%+, and "
            "prevents revenue-impacting outages through predictive anomaly "
            "detection and automated remediation."
        ),
        "timeline": "Medium-term (6-12 months)",
    },
    "risk-compliance": {
        "id": "risk-compliance",
        "name": "Risk, Compliance & Regulatory Reporting Automation",
        "icon": "⚖️",
        "default_department": "Risk & Compliance",
        "description": (
            "Automate regulatory reporting, internal audit, and control "
            "monitoring with AI-assisted document analysis, exception "
            "detection, and continuous compliance tracking to reduce manual "
            "reporting effort and audit findings."
        ),
        "default_title": "Risk, Compliance & Regulatory Reporting Automation",
        "default_goals": [
            "Reduce regulatory reporting cycle effort by 60%+",
            "Detect control exceptions and policy violations in near real time",
            "Maintain an audit-ready evidence trail with automated document collection",
            "Accelerate internal audit cycles via AI-assisted sampling and analysis",
        ],
        "default_challenges": [
            "Keeping pace with evolving regulatory requirements across jurisdictions",
            "Handling unstructured documents (contracts, policies, filings) reliably",
            "Ensuring model outputs are explainable and defensible to regulators",
            "Integrating GRC platforms with ERP and systems of record",
        ],
        "default_pain_points": [
            "Month-long reporting cycles consumed by manual data gathering and reconciliation",
            "High risk of missed exceptions and regulatory penalties",
            "Recurring audit findings from manual control testing",
            "Compliance data siloed across departments and systems",
        ],
        "impact_category": "Risk Mitigation",
        "impact_description": (
            "Automated compliance reporting cuts preparation time by "
            "60-80%, reduces regulatory penalties and audit findings "
            "through continuous monitoring, and frees compliance teams for "
            "judgment-based risk work."
        ),
        "timeline": "Long-term (12+ months)",
    },
}


def truncate_goal_title(goal: str | None, limit: int = 100) -> str:
    """Truncate a goal to ``limit`` chars at a word boundary.

    Appends an ellipsis only when truncation actually occurred. Accepts
    ``None``/empty and returns an empty string.
    """
    goal = (goal or "").strip()
    if len(goal) <= limit:
        return goal
    cut = goal[:limit].rsplit(" ", 1)[0].rstrip()
    if not cut:  # single very long token
        cut = goal[:limit].rstrip()
    return cut + "…"
