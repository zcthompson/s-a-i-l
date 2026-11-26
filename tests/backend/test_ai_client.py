"""Regression tests for AIClient._parse_scoring_response scale normalization.

The scoring prompt requests dimension scores on a 1-10 scale and an overall
on 0-100. Observed gemma4-12b behavior (2026-08-26 dev run): the model
returns the OVERALL on the same 1-10 scale as the dimensions (e.g. 7.2 for a
strong use case). The parser must normalize that deterministically to 0-100,
otherwise persisted scores would be ~10x too low.

Pure-function tests — no network, no LLM.
Run: pytest tests/backend/test_ai_client.py -v
"""

import json

from backend.clients.ai_client import AIClient


def _parse(content: str) -> dict:
    client = AIClient()
    return client._parse_scoring_response(content)


def test_overall_on_1_to_10_scale_is_normalized_to_0_100():
    payload = json.dumps({
        "dimension_scores": [
            {"name": "Data Readiness", "score": 8.0, "weight": 0.2},
            {"name": "Technical Feasibility", "score": 7.5, "weight": 0.2},
        ],
        "overall_score": 7.2,
        "reasoning": "observed gemma 1-10 overall",
    })
    result = _parse(payload)
    assert result["overall_score"] == 72.0
    assert result["dimension_scores"][0]["score"] == 80.0
    assert result["dimension_scores"][1]["score"] == 75.0
    assert "scored_at" in result


def test_overall_already_0_to_100_is_unchanged():
    payload = json.dumps({
        "dimension_scores": [{"name": "Data Readiness", "score": 8.0}],
        "overall_score": 74.0,
        "reasoning": "already 0-100",
    })
    assert _parse(payload)["overall_score"] == 74.0


def test_overall_exactly_10_is_treated_as_1_to_10_scale():
    payload = json.dumps({
        "dimension_scores": [{"name": "Data Readiness", "score": 9.9}],
        "overall_score": 10,
        "reasoning": "edge: perfect 1-10 overall",
    })
    assert _parse(payload)["overall_score"] == 100.0


def test_json_extracted_from_surrounding_text():
    payload = 'Sure, here is the score:\n{"dimension_scores": [{"name": "ROI Potential", "score": 5.5}], "overall_score": 5.8, "reasoning": "x"}\nHope that helps.'
    result = _parse(payload)
    assert result["overall_score"] == 58.0
    assert result["dimension_scores"][0]["score"] == 55.0
