"""Deterministic per-department "good example" use-case registry.

Pure data + pure functions, mirroring ``backend/verticals.py`` and
``backend/templates.py``. Every value in this module is **curated
deterministic content** — there is no LLM call, no randomness, and no
timestamp-as-logic at runtime. When the template-assessment bootstrap
leaves a vertical department with zero use cases, it fills that
department with one draft use case copied verbatim from here so a S-A-I-L
assessor always has a realistic, department-appropriate starting point.

The content is grounded in well-established real-world AI patterns, with
domain framing checked against context7 documentation (2026-08-29):

* LangChain (RAG chains; customer-support ticket structured schema of
  category / priority / summary / sentiment; document-QA retrieval) —
  grounds the Customer Success, HR, and Legal document-processing
  examples.
* scikit-learn (outlier / anomaly detection — IsolationForest,
  One-Class SVM, Local Outlier Factor, EllipticEnvelope — for fraud
  detection and rare-event / sensor monitoring) — grounds the Finance,
  Risk & Compliance, and Operations examples.
* statsmodels (time-series forecasting — SARIMAX, ExponentialSmoothing,
  STLForecast) — grounds the Supply Chain and Finance demand-forecasting
  examples.

Two registries:

* ``EXAMPLE_USE_CASES`` — one generic example per department of the
  closed 10-department set (``verticals.DEPARTMENTS``).
* ``VERTICAL_VARIANTS`` — canonical-vertical → {department → example}
  overrides, curated only where a vertical's version is meaningfully
  different from the generic one.

``example_for_department`` is the single lookup entry point.
"""

from __future__ import annotations

from backend.verticals import DEPARTMENTS, VERTICALS, canonical_vertical

# One curated good example per closed-set department. Keys are exactly
# ``verticals.DEPARTMENTS``.
EXAMPLE_USE_CASES: dict[str, dict] = {
    "Customer Success": {
        "title": "RAG Support Assistant with Automated Ticket Triage",
        "description": (
            "A retrieval-augmented assistant answers tier-1 questions from "
            "the knowledge base and product docs, and classifies every "
            "inbound ticket by category, priority, and sentiment so it "
            "routes to the right queue without manual triage."
        ),
        "goals": [
            "Deflect 40-60% of tier-1 tickets with grounded, cited answers",
            "Auto-classify category, priority, and sentiment on every ticket",
            "Cut median first-response time from hours to under two minutes",
        ],
        "challenges": [
            "Keeping the retrieval index fresh as docs and policies change",
            "Preventing confidently wrong answers on out-of-scope questions",
            "Integrating with the existing CRM and ticketing system",
        ],
        "pain_points": [
            "Agents spend 30%+ of their time on manual triage and routing",
            "Repetitive questions crowd out complex, high-value cases",
            "Inconsistent answers to the same question across agents",
        ],
        "impact_category": "Efficiency",
        "impact_description": (
            "Grounded self-service and automated triage reduce tier-1 "
            "handling cost, shorten first-response time, and lift CSAT "
            "through consistent answers."
        ),
        "estimated_savings": 180000.0,
        "estimated_revenue": 0.0,
        "timeline_estimate": "Short-term (3-6 months)",
    },
    "Operations": {
        "title": "Predictive Maintenance & Bottleneck Detection",
        "description": (
            "Models trained on equipment telemetry and process-flow data "
            "flag anomalous readings before failure and surface the "
            "workstations that constrain throughput, so maintenance and "
            "capacity decisions become proactive."
        ),
        "goals": [
            "Predict equipment failures far enough ahead to schedule repairs",
            "Identify the top throughput bottlenecks each week automatically",
            "Reduce unplanned downtime by 25%+ across the primary line",
        ],
        "challenges": [
            "Sparse and noisy sensor coverage on older equipment",
            "Labelling historical failures for supervised baselines",
            "Earning operator trust in model-driven maintenance calls",
        ],
        "pain_points": [
            "Unplanned outages cascade into missed delivery commitments",
            "Maintenance is calendar-based rather than condition-based",
            "Bottlenecks are only diagnosed after they have cost output",
        ],
        "impact_category": "Efficiency",
        "impact_description": (
            "Condition-based maintenance and bottleneck visibility cut "
            "unplanned downtime, extend asset life, and raise effective "
            "capacity without new equipment."
        ),
        "estimated_savings": 320000.0,
        "estimated_revenue": 0.0,
        "timeline_estimate": "Medium-term (6-12 months)",
    },
    "Finance": {
        "title": "Fraud & Anomaly Monitoring for Financial Transactions",
        "description": (
            "Outlier-detection models score transactions and ledger "
            "entries in near real time, flagging suspicious patterns and "
            "control exceptions for review with an explainable reason code "
            "for each alert."
        ),
        "goals": [
            "Flag suspicious transactions within seconds of posting",
            "Hold the false-positive rate below 5% to limit review load",
            "Give every alert an explainable, audit-ready reason code",
        ],
        "challenges": [
            "Fraud patterns shift, so models need continuous retraining",
            "Highly imbalanced data with very few confirmed fraud cases",
            "Explaining anomaly scores to auditors and dispute teams",
        ],
        "pain_points": [
            "Manual review backlogs delay closing and payment runs",
            "Losses and penalties land only after fraud is discovered late",
            "High false positives create customer friction and rework",
        ],
        "impact_category": "Risk Mitigation",
        "impact_description": (
            "Real-time anomaly monitoring reduces fraud losses, shrinks "
            "the manual review queue, and produces a continuous audit "
            "trail for controls."
        ),
        "estimated_savings": 400000.0,
        "estimated_revenue": 0.0,
        "timeline_estimate": "Medium-term (6-12 months)",
    },
    "IT": {
        "title": "AIOps Incident Triage & Root-Cause Assistance",
        "description": (
            "Machine learning over logs, metrics, and traces correlates "
            "and deduplicates alerts, ranks probable root causes, and "
            "drafts incident summaries so on-call engineers spend less "
            "time triaging and more time fixing."
        ),
        "goals": [
            "Reduce mean time to detect and resolve incidents by 50%+",
            "Cut alert noise by auto-correlating related signals",
            "Move from reactive firefighting to predictive capacity planning",
        ],
        "challenges": [
            "Normalising telemetry from heterogeneous monitoring tools",
            "Tuning anomaly thresholds to avoid a new kind of alert fatigue",
            "Governing any automated remediation in production",
        ],
        "pain_points": [
            "High-frequency, low-value pages drive on-call burnout",
            "Root-cause analysis is slow across distributed systems",
            "Capacity and configuration drift cause surprise outages",
        ],
        "impact_category": "Efficiency",
        "impact_description": (
            "Alert correlation and root-cause ranking lower MTTR, reduce "
            "pager volume, and prevent revenue-impacting outages through "
            "earlier anomaly detection."
        ),
        "estimated_savings": 260000.0,
        "estimated_revenue": 0.0,
        "timeline_estimate": "Medium-term (6-12 months)",
    },
    "Marketing": {
        "title": "Personalization & Churn Prediction Engine",
        "description": (
            "A model builds a unified customer profile from behavioural "
            "and transaction data, predicts churn risk and lifetime value, "
            "and selects the next-best message per segment across email, "
            "web, and app channels."
        ),
        "goals": [
            "Lift campaign conversion 15-35% with real-time personalization",
            "Predict churn early enough for a retention offer to work",
            "Shift budget toward high-lifetime-value segments",
        ],
        "challenges": [
            "Unifying CDP, CRM, and web analytics into one profile",
            "Measuring incremental lift with multi-touch attribution",
            "Avoiding personalization fatigue and privacy concerns",
        ],
        "pain_points": [
            "One-size-fits-all campaigns underperform across segments",
            "Churn is noticed only after the customer has already left",
            "Rising cost per acquisition as channel efficiency declines",
        ],
        "impact_category": "Revenue Growth",
        "impact_description": (
            "Personalized messaging and early churn signals raise "
            "conversion, reduce acquisition cost, and improve retention "
            "and customer lifetime value."
        ),
        "estimated_savings": 0.0,
        "estimated_revenue": 600000.0,
        "timeline_estimate": "Medium-term (6-12 months)",
    },
    "Sales": {
        "title": "Lead Scoring & Pipeline Forecasting",
        "description": (
            "Predictive lead scoring ranks prospects by conversion "
            "likelihood, and a pipeline model forecasts quarter-end "
            "revenue with confidence bands and flags at-risk deals for "
            "manager attention."
        ),
        "goals": [
            "Prioritize high-intent leads to lift close rates by 20%+",
            "Forecast quarter-end revenue to within 5% of actuals",
            "Surface at-risk deals early with clear reason codes",
        ],
        "challenges": [
            "CRM hygiene and activity capture from sales reps",
            "Model drift as product mix and market shift",
            "Making score explanations trustworthy enough for rep adoption",
        ],
        "pain_points": [
            "Reps spend time on low-intent leads while hot deals go stale",
            "Gut-feel forecasting misses or over-books the number",
            "No visibility into which attributes actually predict closure",
        ],
        "impact_category": "Revenue Growth",
        "impact_description": (
            "Focusing reps on the deals most likely to close lifts "
            "conversion, improves forecast accuracy, and shortens the "
            "sales cycle."
        ),
        "estimated_savings": 0.0,
        "estimated_revenue": 750000.0,
        "timeline_estimate": "Medium-term (6-12 months)",
    },
    "HR": {
        "title": "Employee Onboarding Assistant & Retention Signals",
        "description": (
            "A retrieval assistant answers new-hire policy and process "
            "questions from HR documentation, while a retention model "
            "surfaces early attrition risk and the training gaps behind "
            "it so managers can intervene."
        ),
        "goals": [
            "Cut time-to-productivity for new hires with self-service answers",
            "Detect attrition risk early enough for a manager to act",
            "Target training spend at measured skills gaps",
        ],
        "challenges": [
            "Employee data quality and fragmented HR systems",
            "Avoiding bias in any attrition or performance signal",
            "Keeping onboarding content current across regions",
        ],
        "pain_points": [
            "New hires wait on HR for answers already in the handbook",
            "High turnover drives recurring recruitment and training cost",
            "Skills gaps are identified only during performance reviews",
        ],
        "impact_category": "Efficiency",
        "impact_description": (
            "Self-service onboarding and early retention signals reduce "
            "ramp time, lower turnover cost, and focus training investment "
            "where it changes outcomes."
        ),
        "estimated_savings": 150000.0,
        "estimated_revenue": 0.0,
        "timeline_estimate": "Medium-term (6-12 months)",
    },
    "Risk & Compliance": {
        "title": "Regulatory Monitoring & AML/KYC Screening",
        "description": (
            "AI-assisted document analysis tracks regulatory change, and "
            "anomaly detection over customer and transaction data supports "
            "AML and KYC screening with prioritised, explainable alerts "
            "and an automated evidence trail."
        ),
        "goals": [
            "Reduce regulatory reporting cycle effort by 60%+",
            "Detect control exceptions and suspicious activity in near real time",
            "Maintain an audit-ready evidence trail automatically",
        ],
        "challenges": [
            "Keeping pace with evolving rules across jurisdictions",
            "Handling unstructured filings, contracts, and policies reliably",
            "Ensuring outputs are explainable and defensible to regulators",
        ],
        "pain_points": [
            "Month-long reporting cycles consumed by manual data gathering",
            "Missed exceptions expose the firm to regulatory penalties",
            "Recurring audit findings from manual control testing",
        ],
        "impact_category": "Risk Mitigation",
        "impact_description": (
            "Continuous monitoring and screening cut preparation time, "
            "reduce penalties and audit findings, and free compliance "
            "staff for judgment-based risk work."
        ),
        "estimated_savings": 350000.0,
        "estimated_revenue": 0.0,
        "timeline_estimate": "Long-term (12+ months)",
    },
    "Supply Chain": {
        "title": "Demand Forecasting & Inventory Optimization",
        "description": (
            "Time-series models forecast demand at SKU and location level "
            "using history, seasonality, and promotions, and translate the "
            "forecast into automated replenishment and safety-stock "
            "recommendations."
        ),
        "goals": [
            "Achieve sub-10% forecast error for the top-200 SKUs",
            "Minimize stockouts on high-demand products",
            "Reduce excess and obsolete inventory by 25%+",
        ],
        "challenges": [
            "Data quality across POS, ERP, weather, and promotion sources",
            "Modelling seasonality, promotions, and holiday effects",
            "Supply volatility from suppliers, logistics, and geopolitics",
        ],
        "pain_points": [
            "Overstock ties up working capital and drives markdowns",
            "Stockouts cause lost sales and customer dissatisfaction",
            "Spreadsheet forecasting is slow and error-prone",
        ],
        "impact_category": "Cost Reduction",
        "impact_description": (
            "Accurate demand forecasts lower inventory holding cost, cut "
            "stockout-related revenue loss, and improve cash flow through "
            "better working-capital allocation."
        ),
        "estimated_savings": 500000.0,
        "estimated_revenue": 0.0,
        "timeline_estimate": "Medium-term (6-12 months)",
    },
    "Legal": {
        "title": "Contract & Document Review Assistant",
        "description": (
            "A retrieval-augmented assistant extracts key clauses, "
            "obligations, and deviations from the playbook across "
            "contracts and filings, and answers questions about a "
            "document set with citations back to the source text."
        ),
        "goals": [
            "Cut first-pass contract review time by 50%+",
            "Flag non-standard clauses and missing protections automatically",
            "Answer document questions with citations to the source clause",
        ],
        "challenges": [
            "Extraction accuracy on scanned and poorly formatted documents",
            "Keeping the clause playbook current as standards evolve",
            "Ensuring outputs are reviewed before they are relied upon",
        ],
        "pain_points": [
            "Manual review is a bottleneck for deal and procurement cycles",
            "Non-standard clauses slip through under time pressure",
            "Prior contract knowledge is locked in inaccessible PDFs",
        ],
        "impact_category": "Efficiency",
        "impact_description": (
            "Assisted review shortens contract turnaround, improves "
            "consistency against the playbook, and makes historical "
            "contract terms searchable."
        ),
        "estimated_savings": 220000.0,
        "estimated_revenue": 0.0,
        "timeline_estimate": "Medium-term (6-12 months)",
    },
}


# Canonical-vertical → department → example overrides. Curated only where
# the vertical's version reads meaningfully differently from the generic.
VERTICAL_VARIANTS: dict[str, dict[str, dict]] = {
    "Financial Services": {
        "Finance": {
            "title": "Real-Time Payment Fraud & Anomaly Monitoring",
            "description": (
                "Outlier-detection models score card and account "
                "transactions as they authorize, blocking high-risk "
                "activity and routing borderline cases to review with an "
                "explainable reason code."
            ),
            "goals": [
                "Score every transaction for fraud risk before authorization",
                "Keep the false-positive rate below 3% to limit declines",
                "Adapt models continuously as fraud tactics evolve",
            ],
            "challenges": [
                "Sub-second scoring latency at full transaction volume",
                "Extreme class imbalance with rare confirmed fraud",
                "Model explainability for chargeback and regulatory disputes",
            ],
            "pain_points": [
                "Fraud losses and scheme penalties from late detection",
                "Legitimate transactions declined, driving customer churn",
                "Analysts overwhelmed by low-quality alert queues",
            ],
            "impact_category": "Risk Mitigation",
            "impact_description": (
                "Real-time transaction scoring cuts fraud losses and "
                "false declines while producing an auditable decision "
                "trail for every authorization."
            ),
            "estimated_savings": 900000.0,
            "estimated_revenue": 0.0,
            "timeline_estimate": "Medium-term (6-12 months)",
        },
        "Risk & Compliance": {
            "title": "AML/KYC Transaction Monitoring & Regulatory Change Tracking",
            "description": (
                "Anomaly detection over customer and transaction data "
                "prioritises AML alerts, while document analysis tracks "
                "regulatory change and maps it to affected controls and "
                "filings."
            ),
            "goals": [
                "Prioritise AML alerts so investigators work true positives first",
                "Map every regulatory change to affected controls within days",
                "Produce audit-ready suspicious-activity evidence automatically",
            ],
            "challenges": [
                "Tuning models to keep suspicious-activity recall high",
                "Explaining alert scores to regulators and auditors",
                "Integrating GRC platforms with core banking systems",
            ],
            "pain_points": [
                "Investigators spend most of their time clearing false alerts",
                "Regulatory changes are tracked manually across jurisdictions",
                "Audit findings recur from inconsistent manual control testing",
            ],
            "impact_category": "Risk Mitigation",
            "impact_description": (
                "Alert prioritisation and automated change tracking reduce "
                "investigation cost, lower penalty exposure, and keep the "
                "control library current."
            ),
            "estimated_savings": 650000.0,
            "estimated_revenue": 0.0,
            "timeline_estimate": "Long-term (12+ months)",
        },
        "Legal": {
            "title": "Loan & Vendor Contract Review Against the Compliance Playbook",
            "description": (
                "A retrieval-augmented assistant reviews loan, ISDA, and "
                "vendor agreements against the compliance playbook, "
                "flagging deviations, missing regulatory language, and "
                "renewal obligations."
            ),
            "goals": [
                "Cut first-pass review time for standard agreements by 60%+",
                "Flag missing regulatory clauses before signature",
                "Track renewal and covenant obligations automatically",
            ],
            "challenges": [
                "Extraction accuracy on negotiated, redlined documents",
                "Keeping the playbook aligned with regulatory guidance",
                "Ensuring attorney review of every automated finding",
            ],
            "pain_points": [
                "Contract review is a bottleneck for lending and procurement",
                "Regulatory language is inconsistently applied under deadline",
                "Obligations buried in executed contracts are missed",
            ],
            "impact_category": "Efficiency",
            "impact_description": (
                "Playbook-aligned review speeds contract turnaround, "
                "reduces regulatory gaps, and makes obligations trackable."
            ),
            "estimated_savings": 300000.0,
            "estimated_revenue": 0.0,
            "timeline_estimate": "Medium-term (6-12 months)",
        },
    },
    "Insurance": {
        "Finance": {
            "title": "Claims Fraud & Leakage Detection",
            "description": (
                "Outlier-detection models score claims for fraud and "
                "leakage indicators, routing suspicious claims to the "
                "special investigations unit with explainable evidence."
            ),
            "goals": [
                "Identify likely fraudulent claims before payout",
                "Reduce claims leakage from overpayment and error",
                "Give investigators explainable, prioritised referrals",
            ],
            "challenges": [
                "Limited labelled fraud history for supervised models",
                "Balancing investigation load against customer experience",
                "Explaining referrals for regulatory and legal review",
            ],
            "pain_points": [
                "Fraud is confirmed only after the claim has been paid",
                "Manual referral rules miss novel fraud patterns",
                "Legitimate claimants are delayed by broad manual review",
            ],
            "impact_category": "Risk Mitigation",
            "impact_description": (
                "Early claims scoring reduces fraud payout and leakage "
                "while keeping honest claims moving quickly."
            ),
            "estimated_savings": 700000.0,
            "estimated_revenue": 0.0,
            "timeline_estimate": "Medium-term (6-12 months)",
        },
        "Risk & Compliance": {
            "title": "Regulatory Monitoring & Solvency Reporting Automation",
            "description": (
                "Document analysis tracks insurance regulatory change and "
                "anomaly detection checks reporting data for exceptions "
                "ahead of solvency and conduct filings."
            ),
            "goals": [
                "Reduce regulatory reporting cycle effort by 60%+",
                "Catch data exceptions before filings are submitted",
                "Maintain an audit-ready evidence trail automatically",
            ],
            "challenges": [
                "Multi-jurisdiction rules with frequent revisions",
                "Reconciling actuarial, finance, and claims data sources",
                "Explaining exception flags to regulators",
            ],
            "pain_points": [
                "Reporting cycles are consumed by manual reconciliation",
                "Late data errors force refiling and draw scrutiny",
                "Control testing is manual and inconsistently evidenced",
            ],
            "impact_category": "Risk Mitigation",
            "impact_description": (
                "Continuous monitoring shortens the reporting cycle and "
                "reduces refiling and penalty exposure."
            ),
            "estimated_savings": 400000.0,
            "estimated_revenue": 0.0,
            "timeline_estimate": "Long-term (12+ months)",
        },
    },
    "Manufacturing": {
        "Operations": {
            "title": "Sensor-Driven Predictive Maintenance for Production Lines",
            "description": (
                "Anomaly-detection models on vibration, temperature, and "
                "current sensor streams predict equipment degradation and "
                "schedule maintenance before failure stops the line."
            ),
            "goals": [
                "Predict failures with enough lead time to plan the repair",
                "Reduce unplanned line downtime by 30%+",
                "Extend mean time between failures on critical assets",
            ],
            "challenges": [
                "Retrofitting sensors and historians on legacy machines",
                "Distinguishing true degradation from process variation",
                "Integrating alerts into the CMMS work-order flow",
            ],
            "pain_points": [
                "A single machine stoppage idles the whole line",
                "Maintenance is scheduled by calendar, not condition",
                "Spare-parts inventory is oversized to hedge surprise failures",
            ],
            "impact_category": "Efficiency",
            "impact_description": (
                "Condition-based maintenance cuts unplanned downtime, "
                "lowers spare-parts carrying cost, and raises overall "
                "equipment effectiveness."
            ),
            "estimated_savings": 450000.0,
            "estimated_revenue": 0.0,
            "timeline_estimate": "Medium-term (6-12 months)",
        },
        "Supply Chain": {
            "title": "Production Demand Forecasting & Inventory Optimization",
            "description": (
                "Time-series models forecast finished-goods and component "
                "demand and drive materials-requirement planning, safety "
                "stock, and supplier order timing."
            ),
            "goals": [
                "Cut forecast error on high-volume SKUs below 10%",
                "Reduce raw-material and finished-goods inventory by 20%+",
                "Improve on-time-in-full delivery to customers",
            ],
            "challenges": [
                "Long and variable supplier lead times",
                "Bill-of-materials complexity and shared components",
                "Aligning the forecast with plant capacity constraints",
            ],
            "pain_points": [
                "Excess inventory ties up capital on the plant floor",
                "Component shortages halt production runs",
                "Planning is spreadsheet-driven and slow to react",
            ],
            "impact_category": "Cost Reduction",
            "impact_description": (
                "Better demand forecasts reduce inventory across the bill "
                "of materials while protecting production continuity and "
                "delivery performance."
            ),
            "estimated_savings": 550000.0,
            "estimated_revenue": 0.0,
            "timeline_estimate": "Medium-term (6-12 months)",
        },
    },
    "Logistics & Supply Chain": {
        "Supply Chain": {
            "title": "Network Demand Forecasting & Inventory Positioning",
            "description": (
                "Time-series demand models forecast volume by lane and "
                "distribution centre and recommend where to position "
                "inventory to hit service levels at the lowest total cost."
            ),
            "goals": [
                "Forecast lane and DC demand to within 10% error",
                "Position inventory to meet service levels at least cost",
                "Reduce expedited freight caused by misplaced stock",
            ],
            "challenges": [
                "Volatile demand and carrier capacity",
                "Multi-echelon inventory optimisation complexity",
                "Data integration across TMS, WMS, and ERP",
            ],
            "pain_points": [
                "Stock sits in the wrong node while another stocks out",
                "Expedited freight erodes margin to recover service",
                "Planners react to shortages instead of preventing them",
            ],
            "impact_category": "Cost Reduction",
            "impact_description": (
                "Forecast-driven inventory positioning lowers total "
                "landed cost, cuts expedited freight, and stabilises "
                "service levels."
            ),
            "estimated_savings": 600000.0,
            "estimated_revenue": 0.0,
            "timeline_estimate": "Medium-term (6-12 months)",
        },
    },
    "Technology & SaaS": {
        "IT": {
            "title": "AIOps for Platform Reliability & Incident Response",
            "description": (
                "Machine learning over service telemetry correlates "
                "alerts across microservices, ranks probable root causes, "
                "and predicts capacity pressure before it breaches SLOs."
            ),
            "goals": [
                "Reduce MTTR for customer-facing incidents by 50%+",
                "Correlate multi-service alert storms into single incidents",
                "Predict capacity and quota exhaustion ahead of SLO breach",
            ],
            "challenges": [
                "High-cardinality telemetry across many services",
                "Frequent deploys shifting the baseline continuously",
                "Governance for automated rollback and remediation",
            ],
            "pain_points": [
                "Alert storms bury the signal during incidents",
                "On-call engineers burn out on noisy pages",
                "SLO breaches trigger contractual credits",
            ],
            "impact_category": "Efficiency",
            "impact_description": (
                "Alert correlation and predictive capacity planning lower "
                "MTTR, reduce SLO-breach credits, and ease on-call load."
            ),
            "estimated_savings": 300000.0,
            "estimated_revenue": 0.0,
            "timeline_estimate": "Medium-term (6-12 months)",
        },
        "Sales": {
            "title": "Pipeline & Win-Rate Forecasting for SaaS Revenue",
            "description": (
                "Predictive models score opportunities on win likelihood "
                "using product-usage, engagement, and firmographic "
                "signals, and forecast bookings and net revenue retention "
                "with confidence bands."
            ),
            "goals": [
                "Forecast quarterly bookings to within 5% of actuals",
                "Rank opportunities by win likelihood with reason codes",
                "Flag expansion and churn risk in the installed base early",
            ],
            "challenges": [
                "Joining CRM data with product-usage telemetry",
                "Model drift across pricing and packaging changes",
                "Rep adoption of score-driven prioritisation",
            ],
            "pain_points": [
                "Forecast calls swing on rep optimism, not signal",
                "Expansion opportunities are noticed too late to act",
                "Reps chase stalled deals while winnable ones age out",
            ],
            "impact_category": "Revenue Growth",
            "impact_description": (
                "Usage-informed scoring and forecasting improve forecast "
                "accuracy, lift win rates, and surface expansion revenue "
                "earlier."
            ),
            "estimated_savings": 0.0,
            "estimated_revenue": 900000.0,
            "timeline_estimate": "Medium-term (6-12 months)",
        },
    },
    "Retail & E-Commerce": {
        "Marketing": {
            "title": "Shopper Personalization & Churn Prediction",
            "description": (
                "A model unifies browse, purchase, and loyalty data to "
                "personalize product recommendations and offers, and "
                "predicts lapsing shoppers in time for a win-back "
                "campaign."
            ),
            "goals": [
                "Lift on-site conversion and average order value with personalization",
                "Predict lapsing shoppers before their next expected purchase",
                "Shift spend toward high-lifetime-value segments",
            ],
            "challenges": [
                "Identity resolution across guest and logged-in sessions",
                "Cold-start recommendations for new products and shoppers",
                "Attribution across paid, owned, and store channels",
            ],
            "pain_points": [
                "Generic merchandising underperforms across shopper segments",
                "Loyalty lapse is spotted only in quarterly reporting",
                "Rising acquisition cost squeezes category margin",
            ],
            "impact_category": "Revenue Growth",
            "impact_description": (
                "Personalized merchandising and timely win-back offers "
                "raise conversion and repeat-purchase rate while lowering "
                "acquisition cost."
            ),
            "estimated_savings": 0.0,
            "estimated_revenue": 800000.0,
            "timeline_estimate": "Medium-term (6-12 months)",
        },
        "Supply Chain": {
            "title": "SKU-Store Demand Forecasting & Replenishment",
            "description": (
                "Time-series models forecast demand at SKU and store "
                "level with seasonality and promotion effects, and "
                "generate automated replenishment and allocation "
                "recommendations."
            ),
            "goals": [
                "Achieve sub-10% forecast error for top-selling SKUs",
                "Cut stockouts on promoted and seasonal items",
                "Reduce markdown losses from overstock by 25%+",
            ],
            "challenges": [
                "Promotion cannibalisation and halo effects",
                "New-store and new-product forecasting with no history",
                "POS and ERP data quality across the fleet",
            ],
            "pain_points": [
                "Overstock forces end-of-season markdowns",
                "Stockouts on hero products lose the sale and the trip",
                "Store-level ordering relies on manager intuition",
            ],
            "impact_category": "Cost Reduction",
            "impact_description": (
                "Store-level forecasting lowers markdown and carrying "
                "cost while improving on-shelf availability."
            ),
            "estimated_savings": 550000.0,
            "estimated_revenue": 0.0,
            "timeline_estimate": "Medium-term (6-12 months)",
        },
        "Sales": {
            "title": "Wholesale & B2B Account Pipeline Forecasting",
            "description": (
                "Predictive scoring ranks wholesale and marketplace "
                "accounts by expansion potential, and a pipeline model "
                "forecasts B2B revenue with at-risk-account alerts."
            ),
            "goals": [
                "Forecast wholesale revenue to within 5% of actuals",
                "Prioritise accounts by expansion potential",
                "Flag at-risk accounts before they reduce orders",
            ],
            "challenges": [
                "Sparse activity data on smaller accounts",
                "Seasonality in wholesale ordering patterns",
                "Aligning trade terms with predicted account value",
            ],
            "pain_points": [
                "Account managers spread attention evenly, not by value",
                "Order declines surface only after the quarter",
                "Forecasts are built bottom-up by hand each month",
            ],
            "impact_category": "Revenue Growth",
            "impact_description": (
                "Account scoring and pipeline forecasting focus account "
                "management on expansion and protect at-risk revenue."
            ),
            "estimated_savings": 0.0,
            "estimated_revenue": 650000.0,
            "timeline_estimate": "Medium-term (6-12 months)",
        },
        "Customer Success": {
            "title": "Shopper Support Assistant with Order-Aware Triage",
            "description": (
                "A retrieval-augmented assistant answers order, returns, "
                "and product questions grounded in policy and catalogue "
                "data, and triages contacts by intent, urgency, and "
                "sentiment."
            ),
            "goals": [
                "Deflect order-status and returns questions with self-service",
                "Triage contacts by intent and urgency automatically",
                "Cut peak-season response times without seasonal hiring",
            ],
            "challenges": [
                "Real-time order and inventory data in the retrieval context",
                "Policy variation by region and channel",
                "Handoff to a human with full context for complex cases",
            ],
            "pain_points": [
                "Seasonal contact spikes overwhelm the support team",
                "Repetitive 'where is my order' contacts crowd the queue",
                "Return-policy answers are inconsistent across agents",
            ],
            "impact_category": "Efficiency",
            "impact_description": (
                "Order-aware self-service and triage cut contact cost and "
                "response time through seasonal peaks."
            ),
            "estimated_savings": 200000.0,
            "estimated_revenue": 0.0,
            "timeline_estimate": "Short-term (3-6 months)",
        },
    },
    "Healthcare & Life Sciences": {
        "Risk & Compliance": {
            "title": "HIPAA & Regulatory Monitoring with Access Anomaly Detection",
            "description": (
                "Document analysis tracks health-privacy and payer "
                "regulatory change, and anomaly detection over EHR access "
                "logs flags unusual record access for privacy review."
            ),
            "goals": [
                "Detect anomalous patient-record access in near real time",
                "Map regulatory change to affected policies within days",
                "Maintain an audit-ready privacy evidence trail",
            ],
            "challenges": [
                "Defining normal access across clinical roles",
                "Minimising false flags on legitimate care-team access",
                "Integrating EHR, IAM, and GRC systems",
            ],
            "pain_points": [
                "Privacy breaches are found during audits, not as they happen",
                "Regulatory updates are tracked manually across payers",
                "Access reviews are periodic and sampling-based",
            ],
            "impact_category": "Risk Mitigation",
            "impact_description": (
                "Continuous access monitoring and change tracking reduce "
                "breach exposure and audit findings."
            ),
            "estimated_savings": 400000.0,
            "estimated_revenue": 0.0,
            "timeline_estimate": "Long-term (12+ months)",
        },
        "HR": {
            "title": "Clinical Staff Onboarding & Retention Signals",
            "description": (
                "A retrieval assistant answers credentialing and policy "
                "questions for new clinical hires, and a retention model "
                "surfaces burnout and attrition risk with the training "
                "and staffing gaps behind it."
            ),
            "goals": [
                "Shorten credentialing and onboarding time for clinical staff",
                "Detect burnout and attrition risk early enough to act",
                "Target continuing-education spend at measured gaps",
            ],
            "challenges": [
                "Fragmented HR, scheduling, and credentialing systems",
                "Avoiding bias in any attrition or performance signal",
                "Keeping policy content current across facilities",
            ],
            "pain_points": [
                "Nurse and clinician turnover drives costly agency staffing",
                "Onboarding delays keep new hires off the floor",
                "Skills and compliance gaps surface during audits",
            ],
            "impact_category": "Efficiency",
            "impact_description": (
                "Faster onboarding and early retention signals cut agency "
                "staffing cost and stabilise clinical coverage."
            ),
            "estimated_savings": 300000.0,
            "estimated_revenue": 0.0,
            "timeline_estimate": "Medium-term (6-12 months)",
        },
    },
    "Government & Public Sector": {
        "Legal": {
            "title": "Procurement Contract & Grant Agreement Review",
            "description": (
                "A retrieval-augmented assistant reviews procurement "
                "contracts and grant agreements against policy and "
                "statute, flagging non-compliant terms, missing clauses, "
                "and reporting obligations."
            ),
            "goals": [
                "Cut first-pass review time for standard agreements by 50%+",
                "Flag non-compliant or missing clauses before award",
                "Track grant reporting and compliance obligations automatically",
            ],
            "challenges": [
                "Extraction accuracy on scanned and legacy documents",
                "Keeping the policy library aligned with statute changes",
                "Ensuring staff review of every automated finding",
            ],
            "pain_points": [
                "Contract review delays award and disbursement timelines",
                "Compliance clauses are applied inconsistently",
                "Reporting obligations buried in agreements are missed",
            ],
            "impact_category": "Efficiency",
            "impact_description": (
                "Policy-aligned review speeds award cycles and reduces "
                "compliance gaps in contracts and grants."
            ),
            "estimated_savings": 250000.0,
            "estimated_revenue": 0.0,
            "timeline_estimate": "Medium-term (6-12 months)",
        },
    },
    "Hospitality & Travel": {
        "Marketing": {
            "title": "Guest Personalization & Churn Prediction",
            "description": (
                "A model unifies booking, stay, and loyalty data to "
                "personalize offers and itineraries, and predicts guests "
                "at risk of not rebooking in time for a targeted offer."
            ),
            "goals": [
                "Lift direct-booking conversion and ancillary revenue",
                "Predict lapsing loyalty members before their next trip window",
                "Shift spend toward high-lifetime-value guest segments",
            ],
            "challenges": [
                "Identity resolution across OTA and direct channels",
                "Seasonality and trip-purpose variation",
                "Attribution across a long trip-planning journey",
            ],
            "pain_points": [
                "Generic promotions leak margin to discount-seekers",
                "Loyalty lapse is seen only in quarterly reporting",
                "OTA dependence raises distribution cost",
            ],
            "impact_category": "Revenue Growth",
            "impact_description": (
                "Personalized offers and timely win-back campaigns raise "
                "direct bookings and repeat-stay rate."
            ),
            "estimated_savings": 0.0,
            "estimated_revenue": 700000.0,
            "timeline_estimate": "Medium-term (6-12 months)",
        },
        "Customer Success": {
            "title": "Guest Service Assistant with Reservation-Aware Triage",
            "description": (
                "A retrieval-augmented assistant answers reservation, "
                "amenity, and policy questions grounded in property data, "
                "and triages guest messages by intent, urgency, and "
                "sentiment across channels."
            ),
            "goals": [
                "Deflect routine reservation and amenity questions",
                "Triage guest messages by urgency automatically",
                "Maintain response times through demand peaks",
            ],
            "challenges": [
                "Live reservation and availability data in the assistant",
                "Policy variation by property and rate plan",
                "Warm handoff to on-property staff for service recovery",
            ],
            "pain_points": [
                "Front-desk teams are pulled off guests to answer messages",
                "Repetitive pre-arrival questions flood the inbox",
                "Inconsistent answers across properties hurt the brand",
            ],
            "impact_category": "Efficiency",
            "impact_description": (
                "Reservation-aware self-service and triage cut response "
                "time and free staff for in-person service."
            ),
            "estimated_savings": 160000.0,
            "estimated_revenue": 0.0,
            "timeline_estimate": "Short-term (3-6 months)",
        },
    },
    "Education": {
        "Customer Success": {
            "title": "Student & Learner Support Assistant with Triage",
            "description": (
                "A retrieval-augmented assistant answers enrollment, "
                "financial-aid, and course questions grounded in policy "
                "and catalogue data, and triages requests by topic and "
                "urgency."
            ),
            "goals": [
                "Deflect routine enrollment and aid questions with self-service",
                "Triage student requests by topic and urgency automatically",
                "Hold response times steady through term-start peaks",
            ],
            "challenges": [
                "Policy variation by program and campus",
                "Sensitive financial-aid and record data in context",
                "Handoff to an advisor with full history for complex cases",
            ],
            "pain_points": [
                "Advising teams are overwhelmed at the start of every term",
                "Repetitive policy questions crowd out real advising",
                "Answers vary by advisor and channel",
            ],
            "impact_category": "Efficiency",
            "impact_description": (
                "Grounded self-service and triage cut advising load and "
                "response time during peak enrollment periods."
            ),
            "estimated_savings": 140000.0,
            "estimated_revenue": 0.0,
            "timeline_estimate": "Short-term (3-6 months)",
        },
        "HR": {
            "title": "Faculty & Staff Onboarding with Training-Gap Detection",
            "description": (
                "A retrieval assistant answers HR and policy questions "
                "for new faculty and staff, and analytics surface "
                "attrition risk and the professional-development gaps "
                "behind it."
            ),
            "goals": [
                "Shorten onboarding time for faculty and staff",
                "Detect attrition risk early enough for intervention",
                "Target professional-development spend at measured gaps",
            ],
            "challenges": [
                "Fragmented HR and academic systems",
                "Avoiding bias in attrition and performance signals",
                "Keeping policy content current across departments",
            ],
            "pain_points": [
                "New hires wait on HR for answers already documented",
                "Turnover drives recurring recruitment and training cost",
                "Development needs surface only at review time",
            ],
            "impact_category": "Efficiency",
            "impact_description": (
                "Self-service onboarding and early retention signals "
                "reduce ramp time and turnover cost."
            ),
            "estimated_savings": 130000.0,
            "estimated_revenue": 0.0,
            "timeline_estimate": "Medium-term (6-12 months)",
        },
    },
    "Media & Entertainment": {
        "Marketing": {
            "title": "Audience Personalization & Subscriber Churn Prediction",
            "description": (
                "A model unifies viewing, engagement, and billing data to "
                "personalize content recommendations and predicts "
                "subscribers at risk of cancelling in time for a "
                "retention offer."
            ),
            "goals": [
                "Lift content engagement and watch time with personalization",
                "Predict subscriber churn before the renewal date",
                "Shift spend toward high-lifetime-value audience segments",
            ],
            "challenges": [
                "Cold-start recommendations for new titles",
                "Balancing personalization with content discovery breadth",
                "Attribution across trailers, social, and owned channels",
            ],
            "pain_points": [
                "Generic recommendations depress engagement and retention",
                "Churn is identified only after cancellation",
                "Rising acquisition cost per subscriber",
            ],
            "impact_category": "Revenue Growth",
            "impact_description": (
                "Personalized discovery and timely retention offers raise "
                "engagement and reduce subscriber churn."
            ),
            "estimated_savings": 0.0,
            "estimated_revenue": 850000.0,
            "timeline_estimate": "Medium-term (6-12 months)",
        },
    },
}


def example_for_department(dept_name: str, vertical: str | None) -> dict:
    """Return the good-example use case for ``dept_name`` under ``vertical``.

    ``vertical`` is canonicalised via ``verticals.canonical_vertical``.
    When a ``VERTICAL_VARIANTS`` override exists for the canonical
    vertical and department, it is returned; otherwise the department's
    generic ``EXAMPLE_USE_CASES`` entry is returned. "Other", ``None``,
    and unknown verticals all fall through to the generic entry
    (consistent with ``resolve_departments``).

    An unknown ``dept_name`` (not in the closed 10-department set) raises
    ``ValueError`` — the registry is closed and the bootstrap only ever
    passes 4-set department names.
    """
    if dept_name not in EXAMPLE_USE_CASES:
        raise ValueError(f"Unknown department '{dept_name}'")
    canon = canonical_vertical(vertical)
    if canon and canon in VERTICAL_VARIANTS:
        variant = VERTICAL_VARIANTS[canon].get(dept_name)
        if variant is not None:
            return variant
    return EXAMPLE_USE_CASES[dept_name]


# Import-time integrity checks — the registry is curated data; a typo in a
# key should fail loudly at startup, not silently skip a pre-seed.
assert set(EXAMPLE_USE_CASES) == set(DEPARTMENTS), (
    "EXAMPLE_USE_CASES must cover exactly verticals.DEPARTMENTS"
)
for _v, _depts in VERTICAL_VARIANTS.items():
    assert _v in VERTICALS, f"VERTICAL_VARIANTS key '{_v}' is not a canonical vertical"
    for _d in _depts:
        assert _d in DEPARTMENTS, f"VERTICAL_VARIANTS['{_v}'] department '{_d}' is not closed-set"
