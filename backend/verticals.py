"""Deterministic, rule-based customer-vertical registry (WP19).

Pure data + pure functions. No LLM, no inference. Given a customer's
vertical (industry), this module answers two questions deterministically:

* which four departments are most likely to request an AI assessment
  (``resolve_departments``), and
* which of those departments a given template goal belongs under
  (``map_goal_to_department``).

The vertical list and the per-vertical department picks are curated and
user-approved (2026-08-28). "Other"/unset always falls back to
``DEFAULT_DEPARTMENTS``.
"""

from __future__ import annotations

# The 13 curated verticals (canonical case). "Other" is the escape hatch —
# the customer's description then carries the industry specifics.
VERTICALS: list[str] = [
    "Retail & E-Commerce",
    "Healthcare & Life Sciences",
    "Financial Services",
    "Insurance",
    "Manufacturing",
    "Energy & Utilities",
    "Logistics & Supply Chain",
    "Technology & SaaS",
    "Education",
    "Government & Public Sector",
    "Hospitality & Travel",
    "Media & Entertainment",
    "Other",
]

# Closed 10-department set — every value in VERTICAL_DEPARTMENTS and every
# GOAL_DEPARTMENT_RULES target is one of these.
DEPARTMENTS: list[str] = [
    "Customer Success",
    "Operations",
    "Finance",
    "IT",
    "Marketing",
    "Sales",
    "HR",
    "Risk & Compliance",
    "Supply Chain",
    "Legal",
]

DEFAULT_DEPARTMENTS = ("Customer Success", "Operations", "Finance", "IT")

# The 4 most-likely-to-request-an-AI-assessment departments per vertical,
# in seed order.
VERTICAL_DEPARTMENTS: dict[str, tuple[str, str, str, str]] = {
    "Retail & E-Commerce": ("Customer Success", "Operations", "Marketing", "Sales"),
    "Healthcare & Life Sciences": ("Customer Success", "Operations", "Finance", "IT"),
    "Financial Services": ("Finance", "Risk & Compliance", "Customer Success", "IT"),
    "Insurance": ("Finance", "Risk & Compliance", "Customer Success", "Operations"),
    "Manufacturing": ("Operations", "Finance", "HR", "IT"),
    "Energy & Utilities": ("Operations", "IT", "Finance", "Risk & Compliance"),
    "Logistics & Supply Chain": ("Supply Chain", "Operations", "Finance", "IT"),
    "Technology & SaaS": ("IT", "Customer Success", "Sales", "Marketing"),
    "Education": ("HR", "Customer Success", "Operations", "Finance"),
    "Government & Public Sector": ("Operations", "Finance", "Risk & Compliance", "IT"),
    "Hospitality & Travel": ("Customer Success", "Operations", "Marketing", "Finance"),
    "Media & Entertainment": ("Marketing", "Customer Success", "Operations", "Finance"),
    "Other": DEFAULT_DEPARTMENTS,
}

# Ordered goal-text → department keyword rules. FIRST match wins;
# case-insensitive substring match against the goal text.
GOAL_DEPARTMENT_RULES: list[tuple[tuple[str, ...], str]] = [
    (("customer", "support", "ticket", "csat", "agent", "satisfaction"), "Customer Success"),
    (("fraud", "compliance", "risk", "audit", "regulatory", "aml", "kyc", "penalt"), "Risk & Compliance"),
    (("lead", "close rate", "pipeline", "sales cycle", "prospect"), "Sales"),
    (("campaign", "conversion", "segment", "acquisition", "brand", "personalization"), "Marketing"),
    (("financial", "reconciliation", "month-end", "ledger", "accrual"), "Finance"),
    (("incident", "mttr", "mttd", "on-call", "infrastructure", "telemetry", "capacity", "outage", "alert"), "IT"),
    (("employee", "hire", "turnover", "recruit", "talent", "training", "skills gap"), "HR"),
    (("forecast", "inventory", "stock", "supply chain", "logistics", "replenish", "demand"), "Supply Chain"),
    (("quality", "process", "operational", "efficiency", "production", "bottleneck", "waste"), "Operations"),
]


def canonical_vertical(vertical: str | None) -> str | None:
    """Return the canonical-case vertical name, or None.

    Empty/whitespace/None → None. Case-insensitive match against
    ``VERTICALS`` → the canonical-case name. No match → None.
    """
    if not vertical or not vertical.strip():
        return None
    needle = vertical.strip().casefold()
    for name in VERTICALS:
        if name.casefold() == needle:
            return name
    return None


def resolve_departments(vertical: str | None) -> list[str]:
    """The 4 seed departments for this vertical.

    Canonical-case vertical present in the mapping → its 4 departments.
    "Other", unset, or an unknown value → ``DEFAULT_DEPARTMENTS``.
    """
    canon = canonical_vertical(vertical)
    if canon and canon in VERTICAL_DEPARTMENTS:
        return list(VERTICAL_DEPARTMENTS[canon])
    return list(DEFAULT_DEPARTMENTS)


def _keyword_department(goal: str) -> str | None:
    text = (goal or "").casefold()
    for keywords, department in GOAL_DEPARTMENT_RULES:
        if any(kw in text for kw in keywords):
            return department
    return None


# Bidirectional alias: Supply Chain work is Operations work when the
# customer's 4-set has only one of the two.
_ALIASES = {
    "Supply Chain": "Operations",
    "Operations": "Supply Chain",
}


def map_goal_to_department(
    goal: str,
    department_set: list[str],
    template_department: str | None,
    goal_index: int,
) -> str:
    """Pick the department (within ``department_set``) for a template goal.

    1. keyword match → candidate;
    2. candidate in the set → return it;
    3. alias (Supply Chain ↔ Operations) in the set → return the alias;
    4. the template's own default department, if in the set → return it;
    5. otherwise round-robin: ``department_set[goal_index % len]``.
    """
    candidate = _keyword_department(goal)
    if candidate and candidate in department_set:
        return candidate
    if candidate and candidate in _ALIASES and _ALIASES[candidate] in department_set:
        return _ALIASES[candidate]
    if template_department and template_department in department_set:
        return template_department
    if not department_set:
        return template_department or "Operations"
    return department_set[goal_index % len(department_set)]
