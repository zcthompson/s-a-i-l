"""Tests for AI readiness scoring logic."""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

import pytest
from backend.services.scoring import ScoringService


class TestExtractDimensionScores:
    """Tests for ScoringService.extract_dimension_scores() payload normalization."""

    def test_flat_seed_payload(self):
        out = ScoringService.extract_dimension_scores({
            "data_readiness": 72, "technical_feasibility": 78,
            "organizational_readiness": 68, "roi_potential": 65,
            "risk_compliance": 72, "implementation_complexity": 70,
        })
        assert out == {
            "Data Readiness": 72.0, "Technical Feasibility": 78.0,
            "Organizational Readiness": 68.0, "ROI Potential": 65.0,
            "Risk & Compliance": 72.0, "Implementation Complexity": 70.0,
        }

    def test_list_payload(self):
        out = ScoringService.extract_dimension_scores({
            "dimension_scores": [
                {"name": "Data Readiness", "score": 88.0, "weight": 0.2, "description": "ok"},
                {"name": "ROI Potential", "score": 50.0, "weight": 0.2},
            ],
            "overall_score": 70,
        })
        assert out == {"Data Readiness": 88.0, "ROI Potential": 50.0}

    def test_list_wins_flat_fills_gaps(self):
        out = ScoringService.extract_dimension_scores({
            "dimension_scores": [{"name": "Data Readiness", "score": 90}],
            "roi_potential": 40,
        })
        assert out == {"Data Readiness": 90.0, "ROI Potential": 40.0}

    def test_model_paraphrase_and_variant(self):
        out = ScoringService.extract_dimension_scores({
            "dimension_scores": [
                {"name": "Risk and Compliance", "score": 55.0},
                {"name": "roi and potential", "score": 61.0},
            ],
        })
        assert out == {"Risk & Compliance": 55.0, "ROI Potential": 61.0}

    def test_junk_and_empty(self):
        assert ScoringService.extract_dimension_scores(None) == {}
        assert ScoringService.extract_dimension_scores({}) == {}
        assert ScoringService.extract_dimension_scores(
            {"dimension_scores": [{"name": "NotADimension", "score": 5}]}
        ) == {}


class TestWeightedAverage:
    """Tests for the weighted average calculation."""

    def test_perfect_scores(self):
        """All dimensions at 100 should return 100."""
        dimensions = [
            {"name": "Data", "score": 100, "weight": 0.20},
            {"name": "Tech", "score": 100, "weight": 0.20},
            {"name": "Org", "score": 100, "weight": 0.15},
            {"name": "ROI", "score": 100, "weight": 0.20},
            {"name": "Risk", "score": 100, "weight": 0.15},
            {"name": "Complexity", "score": 100, "weight": 0.10},
        ]
        assert ScoringService.calculate_weighted_average(dimensions) == 100.0

    def test_zero_scores(self):
        """All dimensions at 0 should return 0."""
        dimensions = [
            {"name": "Data", "score": 0, "weight": 0.20},
            {"name": "Tech", "score": 0, "weight": 0.20},
            {"name": "Org", "score": 0, "weight": 0.15},
            {"name": "ROI", "score": 0, "weight": 0.20},
            {"name": "Risk", "score": 0, "weight": 0.15},
            {"name": "Complexity", "score": 0, "weight": 0.10},
        ]
        assert ScoringService.calculate_weighted_average(dimensions) == 0.0

    def test_mixed_scores(self):
        """Mixed scores should calculate correctly."""
        dimensions = [
            {"name": "Data", "score": 80, "weight": 0.20},
            {"name": "Tech", "score": 60, "weight": 0.20},
            {"name": "Org", "score": 90, "weight": 0.15},
            {"name": "ROI", "score": 70, "weight": 0.20},
            {"name": "Risk", "score": 50, "weight": 0.15},
            {"name": "Complexity", "score": 40, "weight": 0.10},
        ]
        # Manual calculation: 80*0.20 + 60*0.20 + 90*0.15 + 70*0.20 + 50*0.15 + 40*0.10
        # = 16 + 12 + 13.5 + 14 + 7.5 + 4 = 67.0
        result = ScoringService.calculate_weighted_average(dimensions)
        assert result == pytest.approx(67.0, abs=0.1)

    def test_empty_list(self):
        """Empty dimension list should return 0."""
        assert ScoringService.calculate_weighted_average([]) == 0.0

    def test_dimensions_included(self):
        """All predefined dimensions should be present."""
        dim_names = [d["name"] for d in ScoringService.DIMENSIONS]
        assert "Data Readiness" in dim_names
        assert "Technical Feasibility" in dim_names
        assert "Organizational Readiness" in dim_names
        assert "ROI Potential" in dim_names
        assert "Risk & Compliance" in dim_names
        assert "Implementation Complexity" in dim_names

    def test_weights_sum_to_one(self):
        """Total weight should equal 1.0."""
        total = sum(d["weight"] for d in ScoringService.DIMENSIONS)
        assert total == pytest.approx(1.0, abs=0.001)

    def test_all_weights_positive(self):
        """All weights should be positive."""
        for dim in ScoringService.DIMENSIONS:
            assert dim["weight"] > 0

    def test_weighted_average_ignores_zero_weight(self):
        """A dimension with zero weight should not affect the result."""
        dimensions = [
            {"name": "Data", "score": 100, "weight": 0.20},
            {"name": "Tech", "score": 0, "weight": 0.0},  # Zero weight
            {"name": "Org", "score": 50, "weight": 0.80},
        ]
        # Only Data and Org contribute: (100*0.20 + 50*0.80) / (0.20 + 0.80)
        # = (20 + 40) / 1.0 = 60.0
        result = ScoringService.calculate_weighted_average(dimensions)
        assert result == pytest.approx(60.0, abs=0.1)
