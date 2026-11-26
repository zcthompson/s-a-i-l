"""Unit tests for CustomerStatsService (aggregation service).

Note: These tests focus on what's easy to verify via mocks —
the full query chains are covered by integration tests in
test_api.py and test_integration.py.
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

from unittest.mock import Mock

import pytest
from backend.models.use_case import Customer, UseCase
from backend.services.customer_stats_service import CustomerStatsService


class TestCustomerStatsService:
    """Test customer stats aggregation."""

    @pytest.fixture
    def mock_customer(self):
        """Create a mock customer."""
        customer = Mock()
        customer.id = 1
        customer.name = "Test Customer"
        return customer

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return Mock()

    def test_get_user_stats_no_customers(self, mock_db):
        """Test user stats with no accessible customers."""
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.scalar.return_value = 0

        result = CustomerStatsService.get_user_stats(mock_db, 1)

        assert result["total_use_cases"] == 0
        assert result["total_scored"] == 0
        assert result["average_score"] == 0
        assert "customers" in result

    def test_get_global_stats_includes_customer_scores_and_score_bands(
        self, db_session
    ):
        customer_a = Customer(name="Customer A")
        customer_b = Customer(name="Customer B")
        db_session.add_all([customer_a, customer_b])
        db_session.flush()
        db_session.add_all(
            [
                UseCase(
                    title="High",
                    customer_id=customer_a.id,
                    overall_score=80,
                    estimated_savings=100,
                    estimated_revenue=20,
                ),
                UseCase(
                    title="Unscored",
                    customer_id=customer_a.id,
                    estimated_savings=30,
                    estimated_revenue=0,
                ),
                UseCase(
                    title="Mid",
                    customer_id=customer_b.id,
                    overall_score=60,
                    estimated_savings=50,
                    estimated_revenue=10,
                ),
                UseCase(
                    title="Low",
                    customer_id=customer_b.id,
                    overall_score=40,
                    estimated_savings=0,
                    estimated_revenue=40,
                ),
            ]
        )
        db_session.flush()

        result = CustomerStatsService.get_global_stats(db_session)
        customers = {row["customer_name"]: row for row in result["customers"]}

        assert customers["Customer A"]["average_score"] == 80.0
        assert customers["Customer A"]["total_scored"] == 1
        assert customers["Customer B"]["average_score"] == 50.0
        assert customers["Customer B"]["total_scored"] == 2
        assert result["score_bands"] == {
            "high": 1,
            "mid": 2,
            "low": 0,
            "unscored": 1,
        }
        assert result["total_customers"] == 2
        assert result["total_use_cases"] == 4
        assert result["average_score"] == 60.0
        assert result["total_impact"] == 250.0

    def test_get_user_stats_with_customers(self, mock_db):
        """Test user stats with accessible customers."""
        # Mock junction returns customer IDs
        mock_record = Mock()
        mock_record.customer_id = 1
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_record]

        # Mock UseCase aggregation
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.scalar.return_value = 0

        result = CustomerStatsService.get_user_stats(mock_db, 1)

        assert "total_use_cases" in result
        assert "total_scored" in result
        assert "average_score" in result
        assert "total_savings" in result
        assert "total_revenue" in result
        assert "customers" in result
