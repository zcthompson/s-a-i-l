"""Typed schemas for the customer-stats HTTP endpoints (BE-04).

These model the *wire* shapes returned by ``/api/customers/{name}/stats/``
(and the per-customer aggregate used by the sales readiness surface). Attaching
``response_model`` to the routes means a malformed/error-dict payload can no
longer masquerade as statistics — a ``{"error": ...}`` body fails validation
instead of silently rendering as zeros.
"""


from pydantic import BaseModel


class CustomerStatsDepartment(BaseModel):
    count: int
    avg_score: float
    total_savings: float
    total_revenue: float


class CustomerStatsRecentActivity(BaseModel):
    id: int
    title: str
    created_at: str | None = None
    status: str
    score: float | None = None


class CustomerStatsResponse(BaseModel):
    """GET /api/customers/{name}/stats/ — per-customer aggregate stats."""

    customer_name: str
    customer_description: str | None = None
    total_use_cases: int
    scored_use_cases: int
    unscored_use_cases: int
    average_score: float
    total_savings: float
    total_revenue: float
    total_impact: float
    departments: int
    by_department: dict[str, CustomerStatsDepartment]
    status_breakdown: dict[str, int]
    recent_activity: list[CustomerStatsRecentActivity]
