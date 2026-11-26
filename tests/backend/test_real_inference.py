"""Real-inference liveness tests — the suite's model-endpoint probe.

These tests run a real model call through the app's own scoring route
(dev: nemotron-lightning vLLM on the LAN, per the .env / stored inference
settings). Every full dev-suite run thus confirms the configured inference
endpoint is up and produces a parseable score.

In environments without that endpoint (e.g. GitHub CI runners) every test
marked ``real_inference`` is skipped when SAIL_SKIP_REAL_INFERENCE=1
(see ``pytest_collection_modifyitems`` in tests/backend/conftest.py); the CI
workflow sets that flag at the workflow level. The junction-enforcement
scoring tests in test_multi_tenant_isolation.py stub the AI seam, so they
run deterministically everywhere.

Run: venv/bin/python -m pytest tests/backend/test_real_inference.py -v
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

import pytest
from backend.auth import create_access_token


@pytest.mark.real_inference
def test_scoring_reaches_live_model_endpoint(client, db_session):
    """Liveness: a real model call via POST /api/scoring/ succeeds (200).

    Requires the configured AI endpoint to be reachable (dev: nemotron-lightning
    vLLM). Without it the route 403s (endpoint/API key unconfigured) or
    502s (unreachable), so a green run is a genuine model-liveness signal.
    """
    admin_headers = {
        "Authorization": f"Bearer {create_access_token({'sub': 'admin', 'is_admin': True})}"
    }

    r = client.post(
        "/api/customers/",
        json={"name": "LivenessCust", "description": "real-inference liveness seed"},
        headers=admin_headers,
    )
    assert r.status_code == 201

    r = client.post(
        "/api/use-cases/",
        json={
            "title": "Liveness UC",
            "description": "real-inference liveness seed",
            "customer_id": 1,
            "status": "active",
        },
        headers=admin_headers,
    )
    assert r.status_code == 201
    uc_id = r.json()["id"]

    r = client.post(
        "/api/scoring/",
        json={"use_case_id": uc_id, "reasoning": "Liveness probe"},
        headers=admin_headers,
    )
    assert r.status_code == 200, f"live model call failed: {r.status_code} {r.text[:300]}"

    data = r.json()
    assert "use_case" in data and "scores" in data
    assert 0.0 <= data["scores"]["overall_score"] <= 100.0
