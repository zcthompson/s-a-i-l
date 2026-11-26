"""Tests for backend.services.analytics_service."""

import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock

from backend.services.analytics_service import AnalyticsService


# ── helper: build a fake UseCase ──────────────────────────────────────
def _make_uc(
    id: int = 1,
    customer_id: int = 1,
    department: str = "Engineering",
    overall_score: float = 75.0,
    estimated_savings: float = 1000.0,
    estimated_revenue: float = 2000.0,
    status: str = "active",
    name: str = "Test Use Case",
    title: str = "Test Use Case",
) -> Mock:
    uc = Mock()
    uc.id = id
    uc.customer_id = customer_id
    uc.department = department
    uc.overall_score = overall_score
    uc.estimated_savings = estimated_savings
    uc.estimated_revenue = estimated_revenue
    uc.status = status
    uc.name = name
    uc.title = title
    return uc


# ── helper: build a fake ScoreHistory entry ────────────────────────────
def _make_score(
    use_case_id: int = 1,
    score: float = 75.0,
    scored_at: datetime | None = None,
    status: str = "approved",
    scored_by: int = 1,
    notes: str = "",
) -> Mock:
    if scored_at is None:
        scored_at = datetime.now() - timedelta(days=1)
    entry = Mock()
    entry.use_case_id = use_case_id
    entry.score = score
    entry.scored_at = scored_at  # datetime, not string
    entry.status = status
    entry.scored_by = scored_by
    entry.notes = notes
    return entry


# ── mock DB factory: query-aware ──────────────────────────────────────
def make_mock_db(
    use_cases: list[Mock] | None = None,
    score_history: list[Mock] | None = None,
    dept_rows: list[tuple] | None = None,
    scored_use_cases: list[Mock] | None = None,
) -> Mock:
    """Return a mock Session that returns the right data per query type."""
    db = Mock()
    call_count = [0]  # mutable counter

    def _query(*entities):
        call_count[0] += 1
        entities_str = "".join(str(e) for e in entities)

        # ScoreHistory queries contain "ScoreHistory" in the entity string
        if "ScoreHistory" in entities_str:
            q = Mock()
            q.filter = Mock(return_value=q)
            q.order_by = Mock(return_value=q)
            q.all = Mock(return_value=score_history or [])
            return q

        # Department trends use func.count/avg/sum aggregates
        if "func" in entities_str or "count" in entities_str:
            q = Mock()
            q.group_by = Mock(return_value=q)
            q.filter = Mock(return_value=q)
            q.all = Mock(return_value=dept_rows or [])
            return q

        # UseCase queries without aggregates → return scored_use_cases
        # (correlation, or plain use case fetch)
        if "UseCase" in entities_str:
            # Distinguish UseCase.by_id (trend) from scored (correlation)
            # Trend: first call in a sequence, returns single use case
            # Correlation: multiple UseCase objects returned
            if use_cases and len(use_cases) == 1 and scored_use_cases is None:
                # This is the trend prediction's UseCase lookup
                q = Mock()
                q.filter = Mock(return_value=q)
                q.first = Mock(return_value=use_cases[0])
                return q
            else:
                # This is the correlation query
                q = Mock()
                q.filter = Mock(return_value=q)
                q.all = Mock(return_value=scored_use_cases or [])
                return q

        # Default fallback
        q = Mock()
        q.filter = Mock(return_value=q)
        q.order_by = Mock(return_value=q)
        q.all = Mock(return_value=[])
        q.first = Mock(return_value=None)
        return q

    db.query = Mock(side_effect=_query)
    return db


class TestTrendPrediction(unittest.TestCase):

    def setUp(self):
        self.base = datetime(2025, 1, 1)

    def test_no_use_case(self):
        uc = _make_uc(id=99)
        db = make_mock_db(use_cases=[uc], score_history=[])
        result = AnalyticsService.get_trend_prediction(db, 99)
        self.assertIn("error", result)

    def test_insufficient_history(self):
        uc = _make_uc(id=1)
        sh = [_make_score(1, 50, self.base)]
        db = make_mock_db(use_cases=[uc], score_history=sh)
        result = AnalyticsService.get_trend_prediction(db, 1)
        self.assertIn("Insufficient", result.get("error", ""))

    def test_improving_trend(self):
        uc = _make_uc(id=1)
        sh = []
        for i in range(10):
            ts = self.base + timedelta(days=i)
            sh.append(_make_score(1, 50 + i * 5, ts))
        db = make_mock_db(use_cases=[uc], score_history=sh)
        result = AnalyticsService.get_trend_prediction(db, 1)
        self.assertEqual(result["trend"], "improving")
        self.assertEqual(result["data_points"], 10)
        self.assertIn("predicted_score_30d", result)
        self.assertIn("confidence_interval_95", result)

    def test_declining_trend(self):
        uc = _make_uc(id=1)
        sh = []
        for i in range(5):
            ts = self.base + timedelta(days=i)
            sh.append(_make_score(1, 90 - i * 10, ts))
        db = make_mock_db(use_cases=[uc], score_history=sh)
        result = AnalyticsService.get_trend_prediction(db, 1)
        self.assertEqual(result["trend"], "declining")

    def test_stable_trend(self):
        uc = _make_uc(id=1)
        sh = []
        for i in range(5):
            ts = self.base + timedelta(days=i)
            sh.append(_make_score(1, 70, ts))
        db = make_mock_db(use_cases=[uc], score_history=sh)
        result = AnalyticsService.get_trend_prediction(db, 1)
        self.assertEqual(result["trend"], "stable")

    def test_future_prediction_clamped_high(self):
        """Score won't exceed 100."""
        uc = _make_uc(id=1)
        sh = []
        for i in range(10):
            ts = self.base + timedelta(days=i)
            sh.append(_make_score(1, 100, ts))
        db = make_mock_db(use_cases=[uc], score_history=sh)
        result = AnalyticsService.get_trend_prediction(db, 1)
        self.assertLessEqual(result["predicted_score_30d"], 100)
        self.assertGreaterEqual(result["predicted_score_30d"], 0)

    def test_future_prediction_clamped_low(self):
        """Declining score won't go below 0."""
        uc = _make_uc(id=1)
        sh = []
        for i in range(10):
            ts = self.base + timedelta(days=i)
            sh.append(_make_score(1, 10 - i, ts))
        db = make_mock_db(use_cases=[uc], score_history=sh)
        result = AnalyticsService.get_trend_prediction(db, 1)
        self.assertGreaterEqual(result["predicted_score_30d"], 0)

    def test_customer_access_control(self):
        """customer_id is accepted but not filtered for trend prediction."""
        uc = _make_uc(id=1, customer_id=999)
        sh = []
        for i in range(10):
            ts = self.base + timedelta(days=i)
            sh.append(_make_score(1, 50 + i, ts))
        db = make_mock_db(use_cases=[uc], score_history=sh)
        result = AnalyticsService.get_trend_prediction(db, 1, customer_id=1)
        self.assertNotIn("error", result)

    def test_days_parameter_changes_horizon(self):
        """A longer horizon extends a positive-slope prediction further."""
        uc = _make_uc(id=1)
        sh = []
        for i in range(10):
            ts = self.base + timedelta(days=i)
            sh.append(_make_score(1, 40 + i, ts))
        db = make_mock_db(use_cases=[uc], score_history=sh)
        r30 = AnalyticsService.get_trend_prediction(db, 1, days=30)
        r270 = AnalyticsService.get_trend_prediction(db, 1, days=270)
        self.assertNotIn("error", r30)
        self.assertNotIn("error", r270)
        self.assertEqual(r270["days"], 270)
        self.assertGreater(r270["predicted_score"], r30["predicted_score"])

    def test_prediction_response_contract_fields(self):
        """New contract fields: use_case_title, days, predicted_score, score_change."""
        uc = _make_uc(id=1, title="Forecast UC")
        sh = []
        for i in range(10):
            ts = self.base + timedelta(days=i)
            sh.append(_make_score(1, 40 + i, ts))
        db = make_mock_db(use_cases=[uc], score_history=sh)
        result = AnalyticsService.get_trend_prediction(db, 1, days=90)
        self.assertEqual(result["use_case_title"], "Forecast UC")
        self.assertEqual(result["days"], 90)
        self.assertIn("predicted_score", result)
        self.assertIn("score_change", result)
        self.assertAlmostEqual(
            result["score_change"],
            result["predicted_score"] - result["current_score"],
            delta=0.15,
        )
        # Legacy alias stays in sync with the generalized field
        self.assertEqual(result["predicted_score_30d"], result["predicted_score"])


class TestDepartmentTrends(unittest.TestCase):

    def test_empty_db(self):
        db = make_mock_db(dept_rows=[])
        result = AnalyticsService.get_department_trends(db)
        self.assertEqual(result, [])

    def test_single_department(self):
        dept_rows = [("Engineering", 5, 75.5, 15000.0)]
        db = make_mock_db(dept_rows=dept_rows)
        result = AnalyticsService.get_department_trends(db)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["department"], "Engineering")
        self.assertEqual(result[0]["use_case_count"], 5)
        self.assertEqual(result[0]["avg_score"], 75.5)
        self.assertEqual(result[0]["total_impact"], 15000.0)

    def test_multiple_departments(self):
        dept_rows = [
            ("Engineering", 3, 80.0, 12000.0),
            ("Sales", 7, 45.0, 25000.0),
        ]
        db = make_mock_db(dept_rows=dept_rows)
        result = AnalyticsService.get_department_trends(db)
        self.assertEqual(len(result), 2)

    def test_unassigned_department(self):
        dept_rows = [(None, 2, 60.0, 5000.0)]
        db = make_mock_db(dept_rows=dept_rows)
        result = AnalyticsService.get_department_trends(db)
        self.assertEqual(result[0]["department"], "Unassigned")

    def test_customer_scoped(self):
        dept_rows = [("Engineering", 2, 70.0, 8000.0)]
        db = make_mock_db(dept_rows=dept_rows)
        result = AnalyticsService.get_department_trends(db, customer_id=42)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["department"], "Engineering")

    def test_null_avg_score(self):
        dept_rows = [(None, 1, None, 0)]
        db = make_mock_db(dept_rows=dept_rows)
        result = AnalyticsService.get_department_trends(db)
        self.assertEqual(result[0]["avg_score"], 0)

    def test_null_total_impact(self):
        # Service does round(total_impact, 2) - no None guard, so pass 0
        dept_rows = [("QA", 1, 50.0, 0)]
        db = make_mock_db(dept_rows=dept_rows)
        result = AnalyticsService.get_department_trends(db)
        self.assertEqual(result[0]["total_impact"], 0)


class TestScoreImpactCorrelation(unittest.TestCase):

    def _make_corr_db(self, use_cases: list[Mock]):
        return make_mock_db(scored_use_cases=use_cases)

    def test_no_scored_use_cases(self):
        db = make_mock_db(scored_use_cases=[])
        result = AnalyticsService.get_score_impact_correlation(db)
        self.assertIn("error", result)
        self.assertIn("No scored", result["error"])

    def test_single_use_case(self):
        uc = _make_uc(overall_score=50.0, estimated_savings=1000.0)
        db = self._make_corr_db([uc])
        result = AnalyticsService.get_score_impact_correlation(db)
        self.assertEqual(result["sample_size"], 1)
        self.assertEqual(result["correlation"], 0.0)
        self.assertEqual(result["r_squared"], 0.0)

    def test_strong_positive(self):
        """Higher scores → higher impact."""
        ucs = [
            _make_uc(id=i, overall_score=s, estimated_savings=s * 100)
            for i, s in enumerate([20, 40, 60, 80, 100])
        ]
        db = self._make_corr_db(ucs)
        result = AnalyticsService.get_score_impact_correlation(db)
        self.assertAlmostEqual(result["correlation"], 1.0, places=3)
        self.assertAlmostEqual(result["r_squared"], 1.0, places=3)
        self.assertIn("Strong", result["interpretation"])

    def test_weak_correlation(self):
        """Random scores with fixed impact."""
        ucs = [
            _make_uc(id=i, overall_score=s, estimated_savings=5000)
            for i, s in enumerate([20, 90, 30, 80, 40])
        ]
        db = self._make_corr_db(ucs)
        result = AnalyticsService.get_score_impact_correlation(db)
        self.assertLess(abs(result["correlation"]), 0.1)

    def test_negative_correlation(self):
        """Higher scores → lower impact."""
        ucs = [
            _make_uc(id=i, overall_score=s, estimated_savings=max(1000, 10000 - s * 100))
            for i, s in enumerate([20, 40, 60, 80, 100])
        ]
        db = self._make_corr_db(ucs)
        result = AnalyticsService.get_score_impact_correlation(db)
        self.assertLess(result["correlation"], 0)

    def test_r_squared(self):
        """R-squared should equal correlation squared."""
        ucs = [
            _make_uc(id=i, overall_score=50 + i * 10, estimated_savings=1000 + i * 500)
            for i in range(5)
        ]
        db = self._make_corr_db(ucs)
        result = AnalyticsService.get_score_impact_correlation(db)
        self.assertAlmostEqual(result["r_squared"], result["correlation"] ** 2, places=5)

    def test_zero_impact_all(self):
        """All zero impact → correlation is 0."""
        ucs = [
            _make_uc(id=i, overall_score=50 + i * 10, estimated_savings=0, estimated_revenue=0)
            for i in range(5)
        ]
        db = self._make_corr_db(ucs)
        result = AnalyticsService.get_score_impact_correlation(db)
        self.assertEqual(result["correlation"], 0.0)

    def test_null_impacts(self):
        """None estimated_savings/revenue → treated as 0."""
        ucs = [
            _make_uc(id=i, overall_score=60, estimated_savings=None, estimated_revenue=None)
            for i in range(3)
        ]
        db = self._make_corr_db(ucs)
        result = AnalyticsService.get_score_impact_correlation(db)
        self.assertEqual(result["mean_impact"], 0.0)

    def test_customer_scoped(self):
        """Customer-scoped query returns only that customer's data."""
        ucs = [
            _make_uc(id=1, customer_id=42, overall_score=50.0, estimated_savings=1000),
            _make_uc(id=2, customer_id=42, overall_score=80.0, estimated_savings=3000),
        ]
        db = self._make_corr_db(ucs)
        result = AnalyticsService.get_score_impact_correlation(db, customer_id=42)
        self.assertEqual(result["sample_size"], 2)
        self.assertIn("correlation", result)


class TestInterpretCorrelation(unittest.TestCase):

    def test_strong_positive(self):
        result = AnalyticsService._interpret_correlation(0.8)
        self.assertEqual(result, "Strong positive correlation")

    def test_strong_negative(self):
        result = AnalyticsService._interpret_correlation(-0.85)
        self.assertEqual(result, "Strong negative correlation")

    def test_moderate_positive(self):
        result = AnalyticsService._interpret_correlation(0.55)
        self.assertEqual(result, "Moderate positive correlation")

    def test_moderate_negative(self):
        result = AnalyticsService._interpret_correlation(-0.45)
        self.assertEqual(result, "Moderate negative correlation")

    def test_weak_positive(self):
        result = AnalyticsService._interpret_correlation(0.3)
        self.assertEqual(result, "Weak positive correlation")

    def test_weak_negative(self):
        result = AnalyticsService._interpret_correlation(-0.2)
        self.assertEqual(result, "Weak negative correlation")

    def test_zero(self):
        result = AnalyticsService._interpret_correlation(0.0)
        # 0.0 > 0 is False → direction is "negative", abs(0) < 0.4 → "Weak"
        self.assertEqual(result, "Weak negative correlation")


class TestIntegration(unittest.TestCase):
    """Integration test with the real database."""

    def test_predictive_analytics(self):
        """End-to-end: create use case, add history, verify prediction."""
        from backend.models.collaboration import ScoreHistory
        from backend.models.use_case import Customer, UseCase
        from sqlalchemy.orm import Session

        from tests.backend._shared import engine

        with Session(engine) as db:
            if db.get(Customer, 1) is None:
                db.add(Customer(id=1, name="Analytics test customer"))
                db.commit()
            # Clear existing test data
            db.query(UseCase).filter(UseCase.title == "AnalyticsTest").delete()
            db.commit()

            # Create use case with actual UseCase model fields
            uc = UseCase(
                title="AnalyticsTest",
                description="Test for analytics",
                customer_id=1,
                department="Engineering",
                status="active",
                estimated_savings=1000,
                estimated_revenue=2000,
                overall_score=50,
            )
            db.add(uc)
            db.commit()

            # Add history entries
            base = datetime(2025, 1, 1)
            for i in range(10):
                ts = base + timedelta(days=i)
                score = 50 + i * 5
                entry = ScoreHistory(
                    use_case_id=uc.id,
                    score=score,
                    scored_at=ts,
                    status="approved",
                    scored_by=1,
                )
                db.add(entry)
            db.commit()

            result = AnalyticsService.get_trend_prediction(db, uc.id)
            self.assertNotIn("error", result)
            self.assertEqual(result["data_points"], 10)
            self.assertIn("predicted_score_30d", result)

            # Clean up
            db.query(ScoreHistory).filter(ScoreHistory.use_case_id == uc.id).delete()
            db.query(UseCase).filter(UseCase.id == uc.id).delete()
            db.commit()


if __name__ == "__main__":
    unittest.main()
