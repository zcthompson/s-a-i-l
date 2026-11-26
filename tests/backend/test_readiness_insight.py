"""WP33 readiness-insight service, routes, caching, and trigger tests."""

import json
import threading
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from backend.models.use_case import (
    Customer,
    CustomerUser,
    ReadinessInsight,
    UseCase,
    User,
)
from backend.services.insight_service import InsightService


@contextmanager
def insight_threads():
    """Record the real insight worker threads so the test can join them.

    The test engine is a single shared SQLite connection; polling it while the
    worker thread uses it is a cross-thread race (intermittent
    OperationalError). Joining keeps the real thread but leaves the test idle
    until the worker finishes.
    """
    started = []
    real_start = threading.Thread.start

    def start(self):
        target = getattr(self, "_target", None)
        if target is not None and "trigger_async" in getattr(target, "__qualname__", ""):
            started.append(self)
        real_start(self)

    with patch.object(threading.Thread, "start", start):
        yield started
    for thread in started:
        thread.join(timeout=10)
        assert not thread.is_alive(), "insight worker did not finish"


def insight_row(db_session, customer_id):
    db_session.expire_all()
    return db_session.query(ReadinessInsight).filter_by(customer_id=customer_id).first()

VALID = json.dumps({
    "summary": "The organization has a useful foundation.",
    "strengths": ["Strong data readiness"],
    "weaknesses": ["ROI remains below the 70 target"],
    "priorities": ["Improve ROI evidence", "Sequence delivery", "Measure outcomes"],
})
HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"


@pytest.fixture(autouse=True)
def _auth_lookup(db_session):
    from backend import auth

    def lookup(username):
        user = db_session.query(User).filter(User.username == username).first()
        if not user:
            return None
        return {
            "username": user.username, "email": user.email, "user_id": user.id,
            "is_admin": user.is_admin, "role": user.role,
        }

    with patch.object(auth, "_get_user_by_username", lookup):
        yield


def token(username="admin"):
    from backend.auth import create_access_token
    return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}


def seed(db, complete=True, score=80, title="UC", department="IT", **kwargs):
    customer = Customer(name=kwargs.pop("customer_name", "Acme"))
    db.add(customer)
    db.flush()
    uc = UseCase(
        title=title, customer_id=customer.id,
        status="completed" if complete else "draft", overall_score=score,
        department=department, **kwargs,
    )
    db.add(uc)
    db.commit()
    return customer, uc


def test_fingerprint_tracks_fields_and_is_query_order_independent(db_session):
    customer, first = seed(db_session)
    second = UseCase(title="Second", customer_id=customer.id, status="completed", overall_score=70)
    db_session.add(second)
    db_session.commit()
    original = InsightService.data_fingerprint(db_session, customer.id)
    assert original == InsightService.data_fingerprint(db_session, customer.id)
    for field, value in (("overall_score", 71), ("status", "draft"), ("department", "Ops")):
        setattr(second, field, value)
        db_session.commit()
        changed = InsightService.data_fingerprint(db_session, customer.id)
        assert changed != original
        setattr(second, field, {"overall_score": 70, "status": "completed", "department": None}[field])
        db_session.commit()
    with patch.object(InsightService, "_use_cases", return_value=[second, first]):
        assert InsightService.data_fingerprint(db_session, customer.id) == original


def test_scope_state_mixed_portfolio(db_session):
    customer, _ = seed(db_session)
    db_session.add_all([
        UseCase(title="scored draft", customer_id=customer.id, status="draft", overall_score=70),
        UseCase(title="unscored complete", customer_id=customer.id, status="completed"),
        UseCase(title="unscored draft", customer_id=customer.id, status="draft"),
    ])
    db_session.commit()
    assert InsightService.scope_state(db_session, customer.id) == {
        "total": 4, "included": 1, "unscored": 2, "not_completed": 2,
        "missing_count": 3, "ready": True, "all_scored": False, "all_completed": False,
    }


def test_build_context_aggregates_both_score_shapes(db_session):
    customer, first = seed(
        db_session, score=80, department="IT", estimated_savings=100, estimated_revenue=50,
        scores={"dimension_scores": [{"name": "Data Readiness", "score": 80}]},
    )
    db_session.add_all([
        UseCase(
            title="Finance", customer_id=customer.id, status="completed", overall_score=60,
            department="Finance", estimated_savings=25, estimated_revenue=25,
            scores={"data_readiness": 60, "roi_potential": 40},
        ),
        UseCase(title="Missing", customer_id=customer.id, status="draft", overall_score=None),
    ])
    db_session.commit()
    context = InsightService.build_context(db_session, customer.id)
    assert context["average_score"] == 70.0
    assert context["departments"] == [
        {"name": "IT", "use_case_count": 1, "avg_score": 80.0, "total_impact": 150.0},
        {"name": "Finance", "use_case_count": 1, "avg_score": 60.0, "total_impact": 50.0},
    ]
    assert context["strongest_dimension"] == {"name": "Data Readiness", "average": 70.0}
    assert context["weakest_dimension"] == {"name": "ROI Potential", "average": 40.0}
    assert context["top_use_cases"][0]["title"] == first.title
    assert context["lowest_use_cases"][0]["title"] == "Finance"
    assert context["missing_titles"] == ["Missing"]
    assert context["missing_reasons"] == {"unscored": 1, "not_completed": 1}
    assert context["total_impact"] == 200.0


@pytest.mark.asyncio
async def test_generate_upserts_and_missing_note(db_session):
    customer, _ = seed(db_session)
    db_session.add(UseCase(title="Excluded", customer_id=customer.id, status="draft"))
    db_session.commit()
    with patch("backend.clients.ai_client.AIClient.complete", new=AsyncMock(return_value=VALID)):
        first = await InsightService.generate(db_session, customer.id, "alice")
        first_time = first["generated_at"]
        second = await InsightService.generate(db_session, customer.id, "bob")
    assert db_session.query(ReadinessInsight).count() == 1
    assert second["generated_by"] == "bob"
    assert second["generated_at"] >= first_time
    payload = second["insight_data"]
    assert payload["model_used"] is True and payload["context"]
    assert "1 of 2" in payload["missing_note"] and "Excluded" in payload["missing_note"]


@pytest.mark.asyncio
async def test_generate_complete_portfolio_has_null_missing_note(db_session):
    customer, _ = seed(db_session)
    with patch("backend.clients.ai_client.AIClient.complete", new=AsyncMock(return_value=VALID)):
        result = await InsightService.generate(db_session, customer.id)
    assert result["insight_data"]["missing_note"] is None


@pytest.mark.asyncio
async def test_failure_does_not_modify_existing_row(db_session):
    customer, _ = seed(db_session)
    row = ReadinessInsight(
        customer_id=customer.id, customer_name=customer.name,
        insight_data={"old": True}, data_fingerprint="old", status="completed",
    )
    db_session.add(row)
    db_session.commit()
    with patch("backend.clients.ai_client.AIClient.complete", new=AsyncMock(side_effect=OSError("down"))):
        with pytest.raises(RuntimeError, match="down"):
            await InsightService.generate(db_session, customer.id)
    db_session.refresh(row)
    assert row.insight_data == {"old": True} and row.data_fingerprint == "old"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    "garbage",
    '{"summary":"ok","strengths":[],"weaknesses":["w"],"priorities":["p"]}',
    '{"summary":"ok","strengths":"x","weaknesses":["w"],"priorities":["p"]}',
    '{"summary":"ok","strengths":["s"],"weaknesses":["w"]}',
])
async def test_invalid_response_stores_nothing(db_session, response):
    customer, _ = seed(db_session)
    with patch("backend.clients.ai_client.AIClient.complete", new=AsyncMock(return_value=response)):
        with pytest.raises(RuntimeError):
            await InsightService.generate(db_session, customer.id)
    assert db_session.query(ReadinessInsight).count() == 0


@pytest.mark.asyncio
async def test_fenced_json_parses(db_session):
    customer, _ = seed(db_session)
    with patch("backend.clients.ai_client.AIClient.complete", new=AsyncMock(return_value=f"```json\n{VALID}\n```")):
        assert (await InsightService.generate(db_session, customer.id))["insight_data"]["summary"]


def test_generate_if_ready_conditions_and_deduplicates(db_session):
    customer, _ = seed(db_session)
    missing = UseCase(title="Missing", customer_id=customer.id, status="draft")
    db_session.add(missing)
    db_session.commit()
    complete = AsyncMock(return_value=VALID)
    with patch("backend.clients.ai_client.AIClient.complete", new=complete):
        assert InsightService.generate_if_ready(db_session, customer.id, "full") is None
        result = InsightService.generate_if_ready(db_session, customer.id, "bulk")
        assert "Missing" in result["insight_data"]["missing_note"]
        assert InsightService.generate_if_ready(db_session, customer.id, "bulk") is None
    assert complete.await_count == 1


def test_routes_auth_generate_cache_and_stale(db_session, client):
    customer, uc = seed(db_session)
    outsider = User(username="outsider", email="out@test", hashed_password=HASH, approved=1, is_active=1)
    member = User(username="member", email="mem@test", hashed_password=HASH, approved=1, is_active=1)
    db_session.add_all([outsider, member])
    db_session.flush()
    db_session.add(CustomerUser(customer_id=customer.id, user_id=member.id, role="member"))
    db_session.commit()
    url = f"/api/analytics/readiness-insight/?customer_id={customer.id}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=token("outsider")).status_code == 404  # 404-first (R4/Q7)
    empty = client.get(url, headers=token("member"))
    assert empty.status_code == 200 and empty.json()["insight"] is None and empty.json()["stale"] is False
    complete = AsyncMock(return_value=VALID)
    with patch("backend.clients.ai_client.AIClient.complete", new=complete):
        posted = client.post(url.replace("readiness-insight/", "readiness-insight/generate/"), headers=token("member"))
    assert posted.status_code == 200 and posted.json()["generated_by"] == "member"
    complete.reset_mock()
    with patch("backend.clients.ai_client.AIClient.complete", new=complete):
        assert client.get(url, headers=token("member")).status_code == 200
    assert complete.await_count == 0
    uc.overall_score = 81
    db_session.commit()
    assert client.get(url, headers=token("member")).json()["stale"] is True


def test_post_errors(db_session, client):
    customer, _ = seed(db_session, score=None)
    url = f"/api/analytics/readiness-insight/generate/?customer_id={customer.id}"
    stub = AsyncMock(return_value=VALID)
    with patch("backend.clients.ai_client.AIClient.complete", new=stub):
        assert client.post(url).status_code == 401
        assert client.post(url, headers=token()).status_code == 400
        assert client.post("/api/analytics/readiness-insight/generate/?customer_id=99999", headers=token()).status_code == 404
    assert stub.await_count == 0


def test_trigger_real_thread_full_and_bulk(db_session):
    customer, _ = seed(db_session)
    with patch("backend.clients.ai_client.AIClient.complete", new=AsyncMock(return_value=VALID)), \
            insight_threads() as started:
        InsightService.trigger_async(customer.id, "full", "test")
    assert len(started) == 1
    row = insight_row(db_session, customer.id)
    assert row and row.generated_by == "test"

    db_session.delete(row)
    db_session.add(UseCase(title="Bulk excluded", customer_id=customer.id, status="draft"))
    db_session.commit()
    with patch("backend.clients.ai_client.AIClient.complete", new=AsyncMock(return_value=VALID)), \
            insight_threads() as started:
        InsightService.trigger_async(customer.id, "bulk")
    assert len(started) == 1
    row = insight_row(db_session, customer.id)
    assert row and "Bulk excluded" in row.insight_data["missing_note"]


def test_scoring_last_use_case_triggers_insight(db_session, client):
    customer, _ = seed(db_session, title="Already scored")
    last = UseCase(title="Last", customer_id=customer.id, status="completed")
    db_session.add(last)
    db_session.commit()
    scoring_result = {
        "dimension_scores": [
            {"name": "Data Readiness", "score": 75, "weight": 0.2, "description": "Ready"}
        ],
        "overall_score": 75,
        "reasoning": "Ready",
        "recommendations": ["Proceed"],
        "scored_at": "2026-09-03T00:00:00+00:00",
    }
    with patch(
        "backend.clients.ai_client.AIClient.score_use_case",
        new=AsyncMock(return_value=scoring_result),
    ), patch(
        "backend.clients.ai_client.AIClient.complete",
        new=AsyncMock(return_value=VALID),
    ), insight_threads() as started:
        response = client.post("/api/scoring/", json={"use_case_id": last.id}, headers=token())
        assert response.status_code == 200, response.text
    assert len(started) == 1
    row = insight_row(db_session, customer.id)
    assert row and row.insight_data["model_used"] is True
