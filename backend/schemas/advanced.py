"""Pydantic schemas for advanced visualization endpoints."""


from pydantic import BaseModel

# ── Impact Matrix ──────────────────────────────────────────────────────────


class ImpactMatrixPoint(BaseModel):
    """Single data point for the business impact scatter plot."""
    id: int
    title: str
    department: str | None = None
    overall_score: float
    total_impact: float          # estimated_savings + estimated_revenue
    effort_level: int            # 1=short, 2=medium, 3=long
    effort_label: str            # "Short", "Medium", "Long"
    impact_category: str | None = None
    status: str


class ImpactMatrixResponse(BaseModel):
    """All use cases plotted on the impact vs effort matrix."""
    points: list[ImpactMatrixPoint]
    quadrants: dict[str, list[str]]  # quadrant_label → list of titles


# ── Department Comparison ──────────────────────────────────────────────────


class DeptDimensionAvg(BaseModel):
    """Average score for one dimension across all use cases in a department."""
    dimension: str
    avg_score: float
    count: int
    min_score: float
    max_score: float


class DeptComparisonEntry(BaseModel):
    """One department with its averaged dimension scores."""
    department: str
    use_case_count: int
    avg_overall: float
    dimension_avgs: list[DeptDimensionAvg]


class DeptComparisonResponse(BaseModel):
    """Dimension-level comparison across all departments."""
    departments: list[DeptComparisonEntry]
    dimensions: list[str]  # canonical dimension name order


# ── Score Drill-Down ───────────────────────────────────────────────────────


class ScoreHistoryPoint(BaseModel):
    """One entry in a use case's score history."""
    timestamp: str
    overall_score: float


class DimensionDetail(BaseModel):
    """One scoring dimension with context."""
    name: str
    score: float
    weight: float
    weighted_score: float
    description: str


class DrillDownResponse(BaseModel):
    """Detailed score breakdown for a single use case."""
    id: int
    title: str
    department: str | None = None
    status: str
    overall_score: float
    dimension_details: list[DimensionDetail]
    score_history: list[ScoreHistoryPoint]
    reasoning: str | None = None
    recommendations: list[str] | None = None
    business_impact: dict[str, float | None]  # savings, revenue, total
    timeline_estimate: str | None = None
    scored_at: str | None = None
