"""Tests for AdvancedVisualizationsService (impact matrix, dept comparison, drill-down)."""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

from datetime import UTC, datetime

import pytest
from backend.models.use_case import Customer, UseCase
from backend.services.advanced_visualizations import AdvancedVisualizationsService
from backend.services.scoring import ScoringService


@pytest.fixture(autouse=True)
def _visualization_customers(db_session):
    """The scored fixtures below reference these real account identities."""
    db_session.add_all([Customer(id=1, name="CustA"), Customer(id=2, name="CustB"),
                        Customer(id=3, name="CustC"), Customer(id=5, name="CustE")])
    db_session.commit()


def _make_uc(
    id_: int = 1,
    title: str = "Test UC",
    department: str = "Operations",
    status: str = "active",
    overall_score: float | None = 75.0,
    scores: dict | None = None,
    estimated_savings: float | None = 50000.0,
    estimated_revenue: float | None = 30000.0,
    timeline_estimate: str | None = "short",
    impact_category: str | None = "cost_reduction",
    score_history: list | None = None,
    scored_at: datetime | None = None,
    reason: str = "Good fit",
    recommendations: list | None = None,
    customer_id: int | None = 1,
    description: str = "",
    goals: list | None = None,
    challenges: list | None = None,
    pain_points: list | None = None,
    impact_description: str | None = None,
) -> UseCase:
    """Build a UseCase with realistic scoring data."""
    if scores is None:
        scores = {
            "reasoning": reason,
            "recommendations": recommendations or ["Deploy incrementally"],
            "dimension_scores": [
                {"name": "Data Readiness", "score": 80.0, "weight": 0.20},
                {"name": "Technical Feasibility", "score": 70.0, "weight": 0.20},
                {"name": "Organizational Readiness", "score": 75.0, "weight": 0.15},
                {"name": "ROI Potential", "score": 85.0, "weight": 0.20},
                {"name": "Risk & Compliance", "score": 60.0, "weight": 0.15},
                {"name": "Implementation Complexity", "score": 65.0, "weight": 0.10},
            ],
        }
    return UseCase(
        id=id_,
        title=title,
        description=description,
        customer_id=customer_id,
        department=department,
        status=status,
        overall_score=overall_score,
        scores=scores,
        estimated_savings=estimated_savings,
        estimated_revenue=estimated_revenue,
        timeline_estimate=timeline_estimate,
        impact_category=impact_category,
        impact_description=impact_description,
        score_history=score_history or [
            {"timestamp": "2026-08-01T00:00:00Z", "score": 70.0},
            {"timestamp": "2026-08-10T00:00:00Z", "score": 75.0},
        ],
        scored_at=scored_at or datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC),
        goals=goals or ["Increase efficiency"],
        challenges=challenges or ["Legacy systems"],
        pain_points=pain_points or ["Slow processes"],
    )


# ── Impact Matrix ──────────────────────────────────────────────────────────

class TestImpactMatrix:
    """Tests for AdvancedVisualizationsService.get_impact_matrix()."""

    def test_basic_matrix(self, db_session):
        """A single scored use case produces one point."""
        uc = _make_uc(id_=1, title="Alpha")
        db_session.add(uc)
        db_session.commit()

        result = AdvancedVisualizationsService.get_impact_matrix(db_session)

        assert len(result["points"]) == 1
        p = result["points"][0]
        assert p["id"] == 1
        assert p["title"] == "Alpha"
        assert p["department"] == "Operations"
        assert p["total_impact"] == 80000.0  # 50k + 30k
        assert p["effort_level"] == 1  # short
        assert p["effort_label"] == "Short"
        assert p["overall_score"] == 75.0
        assert p["status"] == "active"
        assert p["impact_category"] == "cost_reduction"

    def test_empty_when_no_scored_use_cases(self, db_session):
        """No scored use cases → empty points list and empty quadrants."""
        db_session.add(UseCase(id=1, title="Unscored", status="draft"))
        db_session.commit()

        result = AdvancedVisualizationsService.get_impact_matrix(db_session)
        assert result["points"] == []
        assert result["quadrants"]["quick_win"] == []
        assert result["quadrants"]["major_project"] == []
        assert result["quadrants"]["fill_in"] == []
        assert result["quadrants"]["thankless_task"] == []

    def test_quadrant_classification(self, db_session):
        """Multiple use cases are distributed across quadrants by median."""
        # High impact, low effort (short) → quick_win
        db_session.add(_make_uc(id_=1, title="HW1", timeline_estimate="short"))
        uc2 = _make_uc(id_=2, title="HW2", estimated_savings=100000.0, estimated_revenue=50000.0, timeline_estimate="short")
        # High effort (long)
        uc3 = _make_uc(id_=3, title="HL1", estimated_savings=100000.0, estimated_revenue=50000.0, timeline_estimate="long")
        # Low effort
        uc4 = _make_uc(id_=4, title="LL1", estimated_savings=1000.0, estimated_revenue=1000.0, timeline_estimate="short")
        db_session.add(uc2)
        db_session.add(uc3)
        db_session.add(uc4)
        db_session.commit()

        result = AdvancedVisualizationsService.get_impact_matrix(db_session)
        assert len(result["points"]) == 4

        titles = [p["title"] for p in result["points"]]
        quick = result["quadrants"]["quick_win"]
        assert "HW1" in quick or "HW2" in quick  # at least one high-impact low-effort

    def test_customer_scoped(self, db_session):
        """A customer_id filter limits results to that customer."""
        db_session.add(UseCase(id=1, title="A1", customer_id=1, department="Ops", overall_score=70.0,
                               scores={"dimension_scores": ScoringService.DIMENSIONS}, estimated_savings=10000.0, estimated_revenue=5000.0,
                               timeline_estimate="short", score_history=[{"timestamp": "2026-08-01T00:00:00Z", "score": 70.0}]))
        db_session.add(UseCase(id=2, title="B1", customer_id=2, department="Ops", overall_score=70.0,
                               scores={"dimension_scores": ScoringService.DIMENSIONS}, estimated_savings=10000.0, estimated_revenue=5000.0,
                               timeline_estimate="short", score_history=[{"timestamp": "2026-08-01T00:00:00Z", "score": 70.0}]))
        db_session.commit()

        result = AdvancedVisualizationsService.get_impact_matrix(db_session, customer_id=1)
        assert len(result["points"]) == 1
        assert result["points"][0]["title"] == "A1"

    def test_default_effort_when_no_timeline(self, db_session):
        """Missing timeline_estimate defaults to medium effort (2)."""
        uc = _make_uc(id_=1, title="NoTimeline", timeline_estimate=None)
        db_session.add(uc)
        db_session.commit()

        result = AdvancedVisualizationsService.get_impact_matrix(db_session)
        assert len(result["points"]) == 1
        assert result["points"][0]["effort_level"] == 2  # medium
        assert result["points"][0]["effort_label"] == "Medium"

    def test_impact_calculation_zero_values(self, db_session):
        """When savings is 0 and revenue is None, total_impact is 0."""
        uc = _make_uc(id_=1, title="ZeroImpact", estimated_savings=0.0, estimated_revenue=None)
        db_session.add(uc)
        db_session.commit()

        result = AdvancedVisualizationsService.get_impact_matrix(db_session)
        assert len(result["points"]) == 1
        assert result["points"][0]["total_impact"] == 0.0

    def test_unscored_excluded(self, db_session):
        """Use cases with overall_score=None are excluded."""
        db_session.add(UseCase(id=1, title="Scored", overall_score=70.0,
                               scores={"dimension_scores": ScoringService.DIMENSIONS}, estimated_savings=10000.0, estimated_revenue=5000.0,
                               timeline_estimate="short", score_history=[{"timestamp": "2026-08-01T00:00:00Z", "score": 70.0}]))
        db_session.add(UseCase(id=2, title="Unscored", overall_score=None, status="draft"))
        db_session.commit()

        result = AdvancedVisualizationsService.get_impact_matrix(db_session)
        assert len(result["points"]) == 1
        assert result["points"][0]["title"] == "Scored"

    def test_no_impact_data_excluded(self, db_session):
        """Use cases with no estimated_savings AND no estimated_revenue are excluded."""
        db_session.add(UseCase(id=1, title="HasImpact", overall_score=70.0,
                               scores={"dimension_scores": ScoringService.DIMENSIONS}, estimated_savings=10000.0, estimated_revenue=5000.0,
                               timeline_estimate="short", score_history=[{"timestamp": "2026-08-01T00:00:00Z", "score": 70.0}]))
        db_session.add(UseCase(id=2, title="NoImpact", overall_score=70.0,
                               scores={"dimension_scores": ScoringService.DIMENSIONS}, estimated_savings=None, estimated_revenue=None,
                               timeline_estimate="short", score_history=[{"timestamp": "2026-08-01T00:00:00Z", "score": 70.0}]))
        db_session.commit()

        result = AdvancedVisualizationsService.get_impact_matrix(db_session)
        assert len(result["points"]) == 1
        assert result["points"][0]["title"] == "HasImpact"


# ── Department Comparison ─────────────────────────────────────────────────

class TestDeptComparison:
    """Tests for AdvancedVisualizationsService.get_dept_comparison()."""

    def test_single_department(self, db_session):
        """One department yields one entry with correct averages."""
        db_session.add(_make_uc(id_=1, title="A", department="Ops"))
        db_session.add(_make_uc(id_=2, title="B", department="Ops", overall_score=90.0))
        db_session.commit()

        result = AdvancedVisualizationsService.get_dept_comparison(db_session)
        assert len(result["departments"]) == 1
        dept = result["departments"][0]
        assert dept["department"] == "Ops"
        assert dept["use_case_count"] == 2
        # Avg of 75 and 90
        assert dept["avg_overall"] == pytest.approx(82.5, abs=0.1)

    def test_multiple_departments(self, db_session):
        """Multiple departments are sorted by name."""
        db_session.add(_make_uc(id_=1, title="A", department="Finance"))
        db_session.add(_make_uc(id_=2, title="B", department="HR", overall_score=90.0))
        db_session.add(_make_uc(id_=3, title="C", department="HR", overall_score=80.0))
        db_session.commit()

        result = AdvancedVisualizationsService.get_dept_comparison(db_session)
        assert len(result["departments"]) == 2
        depts = result["departments"]
        assert depts[0]["department"] == "Finance"
        assert depts[1]["department"] == "HR"
        assert depts[0]["use_case_count"] == 1
        assert depts[1]["use_case_count"] == 2

    def test_unassigned_department(self, db_session):
        """Use cases with department=None are grouped under 'Unassigned'."""
        db_session.add(UseCase(id=1, title="Unassigned1", department=None, customer_id=1, overall_score=60.0,
                               scores={"dimension_scores": ScoringService.DIMENSIONS}, estimated_savings=10000.0, estimated_revenue=5000.0,
                               timeline_estimate="short", score_history=[{"timestamp": "2026-08-01T00:00:00Z", "score": 60.0}]))
        db_session.commit()

        result = AdvancedVisualizationsService.get_dept_comparison(db_session)
        assert any(d["department"] == "Unassigned" for d in result["departments"])

    def test_customer_scoped(self, db_session):
        """A customer_id filter limits comparison to that customer."""
        db_session.add(UseCase(id=1, title="Cust1_A", customer_id=1, department="Ops", overall_score=70.0,
                               scores={"dimension_scores": ScoringService.DIMENSIONS}, estimated_savings=10000.0, estimated_revenue=5000.0,
                               timeline_estimate="short", score_history=[{"timestamp": "2026-08-01T00:00:00Z", "score": 70.0}]))
        db_session.add(UseCase(id=2, title="Cust1_B", customer_id=1, department="Ops", overall_score=80.0,
                               scores={"dimension_scores": ScoringService.DIMENSIONS}, estimated_savings=10000.0, estimated_revenue=5000.0,
                               timeline_estimate="short", score_history=[{"timestamp": "2026-08-01T00:00:00Z", "score": 80.0}]))
        db_session.add(UseCase(id=3, title="Cust2_A", customer_id=2, department="Ops", overall_score=90.0,
                               scores={"dimension_scores": ScoringService.DIMENSIONS}, estimated_savings=10000.0, estimated_revenue=5000.0,
                               timeline_estimate="short", score_history=[{"timestamp": "2026-08-01T00:00:00Z", "score": 90.0}]))
        db_session.commit()

        result = AdvancedVisualizationsService.get_dept_comparison(db_session, customer_id=1)
        assert len(result["departments"]) == 1
        assert result["departments"][0]["use_case_count"] == 2

    def test_no_scored_cases_returns_dimensions(self, db_session):
        """Empty result still includes dimension names."""
        result = AdvancedVisualizationsService.get_dept_comparison(db_session)
        assert result["departments"] == []
        dims = result["dimensions"]
        assert len(dims) == 6  # ScoringService.DIMENSIONS has 6

    def test_dimension_avgs_computed(self, db_session):
        """Per-dimension averages are calculated correctly."""
        # Both have Data Readiness at 80 and 90 respectively
        db_session.add(_make_uc(id_=1, title="A", department="Dept1"))
        uc2 = _make_uc(id_=2, title="B", department="Dept1", overall_score=90.0)
        # Override dimension scores for uc2
        uc2.scores["dimension_scores"][0]["score"] = 90.0  # Data Readiness
        db_session.add(uc2)
        db_session.commit()

        result = AdvancedVisualizationsService.get_dept_comparison(db_session)
        dept = result["departments"][0]
        dim_avgs = dept["dimension_avgs"]
        # Find Data Readiness
        dr = [d for d in dim_avgs if d["dimension"] == "Data Readiness"][0]
        assert dr["avg_score"] == pytest.approx(85.0, abs=0.1)
        assert dr["count"] == 2
        assert dr["min_score"] == pytest.approx(80.0, abs=0.1)
        assert dr["max_score"] == pytest.approx(90.0, abs=0.1)

    def test_dimensions_order_preserved(self, db_session):
        """Dimensions appear in ScoringService.DIMENSIONS_NAME_ORDER order."""
        db_session.add(_make_uc(id_=1, title="A", department="Ops"))
        db_session.commit()

        result = AdvancedVisualizationsService.get_dept_comparison(db_session)
        dims = result["dimensions"]
        assert dims == ScoringService.DIMENSIONS_NAME_ORDER

    def test_flat_seed_payload_scores_dimensions(self, db_session):
        """Seeded flat-dict scores (no dimension_scores list) still score dimensions.

        Regression: TechCorp-style seeded use cases store
        {"data_readiness": 72, ...} and rendered all-zero dimension averages.
        """
        db_session.add(UseCase(id=1, title="SeedA", customer_id=3, department="Customer Success",
                               overall_score=72.0,
                               scores={"data_readiness": 72, "technical_feasibility": 78,
                                       "organizational_readiness": 68, "roi_potential": 65,
                                       "risk_compliance": 72, "implementation_complexity": 70}))
        db_session.add(UseCase(id=2, title="SeedB", customer_id=3, department="Customer Success",
                               overall_score=36.0,
                               scores={"data_readiness": 36, "technical_feasibility": 42,
                                       "organizational_readiness": 38, "roi_potential": 50,
                                       "risk_compliance": 45, "implementation_complexity": 32}))
        db_session.commit()

        result = AdvancedVisualizationsService.get_dept_comparison(db_session, customer_id=3)
        dept = result["departments"][0]
        dr = [d for d in dept["dimension_avgs"] if d["dimension"] == "Data Readiness"][0]
        assert dr["count"] == 2
        assert dr["avg_score"] == pytest.approx(54.0, abs=0.1)
        assert dr["min_score"] == pytest.approx(36.0, abs=0.1)
        assert dr["max_score"] == pytest.approx(72.0, abs=0.1)
        roi = [d for d in dept["dimension_avgs"] if d["dimension"] == "ROI Potential"][0]
        assert roi["avg_score"] == pytest.approx(57.5, abs=0.1)
        rc = [d for d in dept["dimension_avgs"] if d["dimension"] == "Risk & Compliance"][0]
        assert rc["avg_score"] == pytest.approx(58.5, abs=0.1)

    def test_mixed_payload_shapes_per_department(self, db_session):
        """Flat-dict and dimension_scores-list shapes aggregate together per dimension."""
        db_session.add(UseCase(id=1, title="ListShape", customer_id=3, department="Ops",
                               overall_score=80.0,
                               scores={"dimension_scores": [
                                   {"name": "Data Readiness", "score": 90.0, "weight": 0.20},
                                   {"name": "ROI Potential", "score": 80.0, "weight": 0.20}]},
                               ))
        db_session.add(UseCase(id=2, title="FlatShape", customer_id=3, department="Ops",
                               overall_score=60.0,
                               scores={"data_readiness": 70, "roi_potential": 60}))
        db_session.commit()

        result = AdvancedVisualizationsService.get_dept_comparison(db_session, customer_id=3)
        dept = result["departments"][0]
        dr = [d for d in dept["dimension_avgs"] if d["dimension"] == "Data Readiness"][0]
        assert dr["count"] == 2
        assert dr["avg_score"] == pytest.approx(80.0, abs=0.1)
        roi = [d for d in dept["dimension_avgs"] if d["dimension"] == "ROI Potential"][0]
        assert roi["count"] == 2
        assert roi["avg_score"] == pytest.approx(70.0, abs=0.1)


# ── Score Drill-Down ──────────────────────────────────────────────────────

class TestScoreDrillDown:
    """Tests for AdvancedVisualizationsService.get_drill_down()."""

    def test_basic_drill_down(self, db_session):
        """A valid use case returns full breakdown."""
        db_session.add(_make_uc(id_=1, title="Alpha", department="Ops", overall_score=75.0))
        db_session.commit()

        result = AdvancedVisualizationsService.get_drill_down(db_session, use_case_id=1)
        assert result is not None
        assert result["id"] == 1
        assert result["title"] == "Alpha"
        assert result["department"] == "Ops"
        assert result["overall_score"] == 75.0
        assert result["status"] == "active"
        assert len(result["dimension_details"]) == 6
        assert result["reasoning"] == "Good fit"
        assert result["recommendations"] == ["Deploy incrementally"]

    def test_missing_use_case_returns_none(self, db_session):
        """Non-existent use case returns None."""
        result = AdvancedVisualizationsService.get_drill_down(db_session, use_case_id=9999)
        assert result is None

    def test_unscored_returns_none(self, db_session):
        """Use case without scores returns None."""
        db_session.add(UseCase(id=1, title="Unscored", scores=None))
        db_session.commit()

        result = AdvancedVisualizationsService.get_drill_down(db_session, use_case_id=1)
        assert result is None

    def test_dimension_details_calculated(self, db_session):
        """Each dimension has correct weighted score."""
        uc = _make_uc(id_=1, title="Weighted")
        db_session.add(uc)
        db_session.commit()

        result = AdvancedVisualizationsService.get_drill_down(db_session, use_case_id=1)
        dr = [d for d in result["dimension_details"] if d["name"] == "Data Readiness"][0]
        assert dr["score"] == 80.0
        assert dr["weight"] == 0.20
        assert dr["weighted_score"] == pytest.approx(16.0, abs=0.1)

    def test_flat_seed_payload_drill_down(self, db_session):
        """Drill-down reconstructs dimension details from seeded flat-dict scores.

        Regression: seeded use cases ({"data_readiness": 72, ...}) rendered an
        empty dimension_details list, so the drill-down view showed no bars.
        """
        db_session.add(UseCase(id=1, title="SeedA", customer_id=3, department="Customer Success",
                               overall_score=72.0,
                               scores={"data_readiness": 72, "technical_feasibility": 78,
                                       "organizational_readiness": 68, "roi_potential": 65,
                                       "risk_compliance": 72, "implementation_complexity": 70}))
        db_session.commit()

        result = AdvancedVisualizationsService.get_drill_down(db_session, use_case_id=1)
        assert result is not None
        names = [d["name"] for d in result["dimension_details"]]
        assert names == ScoringService.DIMENSIONS_NAME_ORDER
        dr = [d for d in result["dimension_details"] if d["name"] == "Data Readiness"][0]
        assert dr["score"] == pytest.approx(72.0, abs=0.1)
        assert dr["weight"] == pytest.approx(0.20, abs=0.01)
        assert dr["weighted_score"] == pytest.approx(14.4, abs=0.1)
        rc = [d for d in result["dimension_details"] if d["name"] == "Risk & Compliance"][0]
        assert rc["score"] == pytest.approx(72.0, abs=0.1)

    def test_business_impact(self, db_session):
        """Business impact correctly sums savings + revenue."""
        uc = _make_uc(id_=1, title="ImpactTest", estimated_savings=50000.0, estimated_revenue=30000.0)
        db_session.add(uc)
        db_session.commit()

        result = AdvancedVisualizationsService.get_drill_down(db_session, use_case_id=1)
        bi = result["business_impact"]
        assert bi["savings"] == 50000.0
        assert bi["revenue"] == 30000.0
        assert bi["total"] == 80000.0

    def test_score_history_preserved(self, db_session):
        """Score history entries are returned with timestamp and score."""
        history = [
            {"timestamp": "2026-07-01T00:00:00Z", "score": 60.0},
            {"timestamp": "2026-08-01T00:00:00Z", "score": 75.0},
        ]
        uc = _make_uc(id_=1, title="History", score_history=history)
        db_session.add(uc)
        db_session.commit()

        result = AdvancedVisualizationsService.get_drill_down(db_session, use_case_id=1)
        assert len(result["score_history"]) == 2
        assert result["score_history"][0]["timestamp"] == "2026-07-01T00:00:00Z"
        assert result["score_history"][0]["overall_score"] == 60.0
        assert result["score_history"][1]["overall_score"] == 75.0

    def test_customer_audit_filter(self, db_session):
        """Wrong customer_id returns access error."""
        db_session.add(_make_uc(id_=1, title="Private", customer_id=5))
        db_session.commit()

        result = AdvancedVisualizationsService.get_drill_down(db_session, use_case_id=1, customer_id=99)
        assert result["error"] == "No access to this use case"

    def test_customer_pass_through(self, db_session):
        """Matching customer_id returns normal result."""
        db_session.add(_make_uc(id_=1, title="Public", customer_id=5))
        db_session.commit()

        result = AdvancedVisualizationsService.get_drill_down(db_session, use_case_id=1, customer_id=5)
        assert result is not None
        assert result["title"] == "Public"

    def test_scored_at_iso_format(self, db_session):
        """scored_at is returned as ISO format string."""
        uc = _make_uc(id_=1, title="Datetime", scored_at=datetime(2026, 8, 15, 14, 30, 0, tzinfo=UTC))
        db_session.add(uc)
        db_session.commit()

        result = AdvancedVisualizationsService.get_drill_down(db_session, use_case_id=1)
        assert result["scored_at"] == "2026-08-15T14:30:00"
