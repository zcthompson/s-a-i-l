"""generic customer assessments (backend pins).

Rounds (``CustomerAssessment``) carry ``assessment_type`` ('ai' default |
'generic') + ``purpose``. The one-active-round invariant spans both types;
the AI-only surfaces (AI score, manual dimension scoring, prediction
generation) refuse generic-round use cases with an exact 422; the
readiness-insight auto-trigger is skipped (never raised) for them. Legacy
use cases with no round resolve to 'ai' (byte-identical legacy behavior).

Run: pytest tests/backend/test_assessment_type.py -v
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from tests.backend.common import _mk_user, _token

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

ROOT = Path(__file__).resolve().parents[2]
AI_422 = "AI scoring is not available on generic assessments"
ACTIVE_AI_409 = ("This customer already has an active assessment (AI). Archive it "
                 "(or delete its use cases) before starting a new one.")
ACTIVE_GENERIC_409 = ("This customer already has an active assessment (Generic). Archive it "
                      "(or delete its use cases) before starting a new one.")

SCORING_RESULT = {
    "dimension_scores": [{"name": "Data Readiness", "score": 75, "weight": 0.2, "description": "Ready"}],
    "overall_score": 75,
    "reasoning": "Ready",
    "recommendations": ["Proceed"],
    "scored_at": "2026-10-30T00:00:00+00:00",
}
PREDICTION_JSON = '{"predicted_score": 70, "trend": "improving", "confidence": 0.8, "reasoning": "ok"}'



def _admin() -> dict:
    return _token("admin", is_admin=True)


@pytest.fixture()
def world(db_session):
    """TypeCo with an owner (rep), an auditor junction, and an outsider
    (owner of a different customer). No rounds yet."""
    from backend.models.use_case import Customer, CustomerUser

    cust = Customer(name="TypeCo", description="T")
    other = Customer(name="TypeOther", description="O")
    db_session.add_all([cust, other])
    db_session.flush()
    owner = _mk_user(db_session, "ws5_owner", sales_role="rep")
    auditor = _mk_user(db_session, "ws5_auditor")
    outsider = _mk_user(db_session, "ws5_outsider", sales_role="rep")
    db_session.add_all([
        CustomerUser(customer_id=cust.id, user_id=owner.id, role="owner"),
        CustomerUser(customer_id=cust.id, user_id=auditor.id, role="auditor"),
        CustomerUser(customer_id=other.id, user_id=outsider.id, role="owner"),
    ])
    db_session.commit()
    return {"cust": cust.id, "name": cust.name}


def _round(db_session, customer_id: int, assessment_type: str = "ai", status: str = "active",
           purpose: str | None = None):
    from backend.models.use_case import CustomerAssessment
    a = CustomerAssessment(customer_id=customer_id, name=f"{assessment_type} round",
                           status=status, assessment_type=assessment_type, purpose=purpose)
    db_session.add(a)
    db_session.commit()
    return a


def _uc(db_session, customer_id: int, assessment_id: int | None, title: str = "UC",
        status: str = "active"):
    from backend.models.use_case import UseCase
    uc = UseCase(title=title, customer_id=customer_id, department="IT", status=status,
                 assessment_id=assessment_id)
    db_session.add(uc)
    db_session.commit()
    return uc


# ── 1. migration (R11) ──────────────────────────────────────────────────────


def _alembic(db_path, *args) -> str:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["SAIL_DATABASE_URL"] = f"sqlite:///{db_path}"
    res = subprocess.run([sys.executable, "-m", "alembic", *args],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stdout + res.stderr
    return res.stdout + res.stderr


def test_migration_0017_backfills_ai_idempotent_and_roundtrip(tmp_path):
    db_path = tmp_path / "ws5.db"
    _alembic(db_path, "upgrade", "0016_account_strategy")
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO customers (id, name) VALUES (1, 'C1')")
    con.execute("INSERT INTO assessments (id, customer_id, name, status) VALUES (1, 1, 'Old', 'archived')")
    con.execute("INSERT INTO assessments (id, customer_id, name, status) VALUES (2, 1, 'Cur', 'active')")
    con.commit()
    con.close()

    _alembic(db_path, "upgrade", "head")
    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT id, assessment_type, purpose FROM assessments ORDER BY id").fetchall()
    assert rows == [(1, "ai", None), (2, "ai", None)]
    # a fresh generic round persists; a new row with no type gets the server default
    con.execute("INSERT INTO assessments (id, customer_id, name, status, assessment_type, purpose) "
                "VALUES (3, 1, 'Disc', 'archived', 'generic', 'Why')")
    con.execute("INSERT INTO assessments (id, customer_id, name, status) VALUES (4, 1, 'New', 'archived')")
    con.commit()
    assert con.execute("SELECT assessment_type, purpose FROM assessments WHERE id = 3").fetchone() == (
        "generic", "Why")
    assert con.execute("SELECT assessment_type FROM assessments WHERE id = 4").fetchone() == ("ai",)
    con.close()

    # stamp-back re-run is a no-op (inspector-guarded), data untouched
    _alembic(db_path, "stamp", "0016_account_strategy")
    _alembic(db_path, "upgrade", "head")
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT id, assessment_type FROM assessments ORDER BY id").fetchall() == [
        (1, "ai"), (2, "ai"), (3, "generic"), (4, "ai")]
    con.close()
    assert "No new upgrade operations detected" in _alembic(db_path, "check")

    _alembic(db_path, "downgrade", "0016_account_strategy")
    con = sqlite3.connect(db_path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(assessments)")}
    con.close()
    assert "assessment_type" not in cols and "purpose" not in cols
    _alembic(db_path, "upgrade", "head")
    con = sqlite3.connect(db_path)
    assert {r[0] for r in con.execute("SELECT assessment_type FROM assessments")} == {"ai"}
    con.close()
    _alembic(db_path, "check")


# ── 2. create wire-compat (R4/R6) ───────────────────────────────────────────


def test_create_defaults_to_ai(client, world):
    r = client.post(f"/api/customers/{world['name']}/assessments/", headers=_token("ws5_owner"),
                    json={"name": "R1"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["assessment_type"] == "ai" and body["purpose"] is None


def test_create_generic_with_purpose_round_trips(client, world):
    r = client.post(f"/api/customers/{world['name']}/assessments/", headers=_token("ws5_owner"),
                    json={"name": "Discovery", "type": "generic", "purpose": "Map the estate"})
    assert r.status_code == 201, r.text
    assert (r.json()["assessment_type"], r.json()["purpose"]) == ("generic", "Map the estate")
    listed = client.get(f"/api/customers/{world['name']}/assessments/", headers=_token("ws5_owner")).json()
    assert [(a["assessment_type"], a["purpose"]) for a in listed] == [("generic", "Map the estate")]


def test_create_bad_type_is_422_naming_vocabulary(client, world):
    r = client.post(f"/api/customers/{world['name']}/assessments/", headers=_token("ws5_owner"),
                    json={"name": "R1", "type": "hybrid"})
    assert r.status_code == 422
    assert "ai" in r.text and "generic" in r.text
    assert client.get(f"/api/customers/{world['name']}/assessments/",
                      headers=_token("ws5_owner")).json() == []


# ── 3. one-active across types (R3) ─────────────────────────────────────────


def test_one_active_across_types_names_the_active_type(client, world):
    url = f"/api/customers/{world['name']}/assessments/"
    h = _token("ws5_owner")
    ai = client.post(url, headers=h, json={"name": "AI one"})
    assert ai.status_code == 201
    r = client.post(url, headers=h, json={"name": "Gen", "type": "generic"})
    assert r.status_code == 409 and r.json()["detail"] == ACTIVE_AI_409

    assert client.post(f"{url}{ai.json()['id']}/archive/", headers=h).status_code == 200
    gen = client.post(url, headers=h, json={"name": "Gen", "type": "generic"})
    assert gen.status_code == 201
    r = client.post(url, headers=h, json={"name": "AI two"})
    assert r.status_code == 409 and r.json()["detail"] == ACTIVE_GENERIC_409

    archived = client.post(f"{url}{gen.json()['id']}/archive/", headers=h)
    assert archived.status_code == 200
    assert archived.json()["assessment_type"] == "generic"
    assert client.post(url, headers=h, json={"name": "AI two"}).status_code == 201


# ── 4. R5 AI-surface gates ──────────────────────────────────────────────────


@pytest.fixture()
def no_insight():
    with patch("backend.services.insight_service.InsightService.trigger_async") as trig:
        yield trig


def test_generic_round_use_case_refused_on_all_ai_surfaces(client, db_session, world, no_insight):
    gen = _round(db_session, world["cust"], "generic")
    uc = _uc(db_session, world["cust"], gen.id)
    h = _token("ws5_owner")
    model = AsyncMock(return_value=SCORING_RESULT)
    pred_model = AsyncMock(return_value=PREDICTION_JSON)
    with patch("backend.clients.ai_client.AIClient.score_use_case", new=model), \
         patch("backend.services.prediction_service.AIPredictionService._call_model", new=pred_model):
        r = client.post("/api/scoring/", headers=h, json={"use_case_id": uc.id})
        assert (r.status_code, r.json()) == (422, {"detail": AI_422})
        r = client.post("/api/scoring/manual/", headers=h,
                        json={"use_case_id": uc.id, "scores": {}, "overall_score": 50.0})
        assert (r.status_code, r.json()) == (422, {"detail": AI_422})
        r = client.post(f"/api/analytics/predictions/generate/?use_case_id={uc.id}", headers=h)
        assert (r.status_code, r.json()) == (422, {"detail": AI_422})
    model.assert_not_called()
    pred_model.assert_not_called()
    from backend.models.use_case import AIPrediction, UseCase
    db_session.expire_all()
    assert db_session.query(AIPrediction).count() == 0
    assert db_session.get(UseCase, uc.id).overall_score is None
    # downstream forecast read stays honest-empty (not 422)
    r = client.get(f"/api/analytics/predictions/?customer_id={world['cust']}", headers=h)
    assert r.status_code == 200 and r.json() == []


def test_legacy_null_round_use_case_reaches_model_seam(client, db_session, world, no_insight):
    uc = _uc(db_session, world["cust"], None)
    model = AsyncMock(return_value=SCORING_RESULT)
    with patch("backend.clients.ai_client.AIClient.score_use_case", new=model):
        r = client.post("/api/scoring/", headers=_token("ws5_owner"), json={"use_case_id": uc.id})
    assert r.status_code == 200, r.text
    model.assert_called_once()


def test_ai_round_use_case_unaffected(client, db_session, world, no_insight):
    ai = _round(db_session, world["cust"], "ai")
    uc = _uc(db_session, world["cust"], ai.id)
    h = _token("ws5_owner")
    model = AsyncMock(return_value=SCORING_RESULT)
    pred_model = AsyncMock(return_value=PREDICTION_JSON)
    with patch("backend.clients.ai_client.AIClient.score_use_case", new=model), \
         patch("backend.services.prediction_service.AIPredictionService._call_model", new=pred_model):
        assert client.post("/api/scoring/", headers=h, json={"use_case_id": uc.id}).status_code == 200
        r = client.post("/api/scoring/manual/", headers=h,
                        json={"use_case_id": uc.id, "scores": {}, "overall_score": 50.0})
        assert r.status_code == 200, r.text
        r = client.post(f"/api/analytics/predictions/generate/?use_case_id={uc.id}", headers=h)
        assert r.status_code == 200, r.text
    model.assert_called_once()
    pred_model.assert_called_once()


def test_gate_runs_after_access_gates(client, db_session, world, no_insight):
    """Out-of-scope keeps the 404, in-scope auditor keeps the 403 — the 422
    never leaks a generic round's existence or precedes authorization."""
    gen = _round(db_session, world["cust"], "generic")
    uc = _uc(db_session, world["cust"], gen.id)
    r = client.post("/api/scoring/", headers=_token("ws5_outsider"), json={"use_case_id": uc.id})
    assert r.status_code == 404
    r = client.post("/api/scoring/", headers=_token("ws5_auditor"), json={"use_case_id": uc.id})
    assert r.status_code == 403


# ── 5. insight auto-trigger skip (R5) ───────────────────────────────────────


def _admin_user():
    return {"username": "admin", "is_admin": 1, "junction_roles": {}, "customer_ids": []}


def test_generic_completion_skips_insight_trigger(db_session, world, caplog):
    from backend.models.use_case import ReadinessInsight
    from backend.services.use_case_service import UseCaseService
    gen = _round(db_session, world["cust"], "generic")
    uc = _uc(db_session, world["cust"], gen.id)
    with patch("backend.services.insight_service.InsightService.trigger_async") as trig, \
         caplog.at_level("WARNING", logger="backend.services.use_case_service"):
        updated = UseCaseService.update(db_session, uc.id, user=_admin_user(), status="completed")
    assert updated.status == "completed"
    trig.assert_not_called()
    assert db_session.query(ReadinessInsight).count() == 0
    skipped = [r for r in caplog.records if "skipped" in r.getMessage()]
    assert len(skipped) == 1
    assert str(uc.id) in skipped[0].getMessage() and str(world["cust"]) in skipped[0].getMessage()


@pytest.mark.parametrize("round_type", [None, "ai"])
def test_legacy_and_ai_completion_still_fire_insight(db_session, world, round_type):
    from backend.services.use_case_service import UseCaseService
    assessment_id = _round(db_session, world["cust"], round_type).id if round_type else None
    uc = _uc(db_session, world["cust"], assessment_id)
    with patch("backend.services.insight_service.InsightService.trigger_async") as trig:
        UseCaseService.update(db_session, uc.id, user=_admin_user(), status="completed")
    trig.assert_called_once()
    assert trig.call_args.args[:2] == (world["cust"], "full")


# ── 6. R6 / R7 / R9 payloads ────────────────────────────────────────────────


def test_bootstrap_result_carries_ai_type(client, world):
    r = client.post(f"/api/customers/{world['name']}/assessments/from-template/",
                    headers=_token("ws5_owner"), json={"template_id": "customer-support"})
    assert r.status_code == 201, r.text
    assert r.json()["assessment_type"] == "ai" and r.json()["purpose"] is None


def test_graph_active_assessment_carries_type_and_purpose(db_session, world):
    from backend.services.customer_intelligence import _assessment_summary_section
    _round(db_session, world["cust"], "generic", purpose="Discovery")
    section = _assessment_summary_section(db_session, world["cust"])
    active = section["active_assessment"]
    assert (active["assessment_type"], active["purpose"]) == ("generic", "Discovery")
    assert set(active) == {"id", "name", "status", "assessment_type", "purpose",
                           "total_count", "scored_count", "progress_pct"}


def test_round_scoped_export_meta_carries_type_and_purpose(db_session, world):
    from backend.services.export_service import resolve_export_scope
    gen = _round(db_session, world["cust"], "generic", status="archived", purpose="Why")
    _uc(db_session, world["cust"], gen.id)
    _, _, meta = resolve_export_scope(db_session, _admin_user(), assessment_id=gen.id)
    assert (meta["assessment_type"], meta["purpose"]) == ("generic", "Why")
    # non-round export meta is unchanged
    _, _, cust_meta = resolve_export_scope(db_session, _admin_user(), customer_name=world["name"])
    assert "assessment_type" not in cust_meta and "purpose" not in cust_meta


# ── 7. R10 authorization unchanged ──────────────────────────────────────────


def test_round_routes_authorization_unchanged(client, world):
    base = f"/api/customers/{world['name']}/assessments/"
    missing = "/api/customers/NoSuchTypeCo/assessments/"
    h = _token("ws5_outsider")
    for method, kwargs in (("get", {}), ("post", {"json": {"name": "R", "type": "generic"}})):
        out = getattr(client, method)(base, headers=h, **kwargs)
        miss = getattr(client, method)(missing, headers=h, **kwargs)
        assert out.status_code == miss.status_code == 404
        assert out.json() == miss.json()
    r = client.post(base, headers=_token("ws5_auditor"), json={"name": "R", "type": "generic"})
    # the create-round gate is central CAP_EDIT (auditor = no).
    assert (r.status_code, r.json()["detail"]) == (403, "Not authorized to modify this customer")
    r = client.post(base, headers=_token("ws5_owner"), json={"name": "R", "type": "generic"})
    assert r.status_code == 201


# ── 8. primary integration pins (2026-10-30 integration pass) ──────────────


def test_bulk_score_multiple_refuses_generic_round_use_case(client, db_session, world, no_insight):
    """R5 gap closed at the shared seam (bulk.py calls score_use_case_sync
    directly): generic-round use cases are reported per item with the exact
    message, never scored, and the insight trigger never fires."""
    gen = _round(db_session, world["cust"], "generic")
    uc = _uc(db_session, world["cust"], gen.id)
    h = _token("ws5_owner")
    with patch("backend.clients.ai_client.AIClient.score_use_case", new=AsyncMock(return_value=SCORING_RESULT)) as model:
        r = client.post("/api/bulk/score-multiple/", headers=h, json=[uc.id])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success_count"] == 0 and body["error_count"] == 1
    assert body["errors"][0] == {"use_case_id": uc.id, "error": AI_422}
    model.assert_not_called()
    no_insight.assert_not_called()


def test_template_bootstrap_refused_on_active_generic_round(client, db_session, world):
    """R8 honesty at the API: template bootstrap seeds AI use cases and must
    not land them in a generic round (ensure_active would return it)."""
    _round(db_session, world["cust"], "generic")
    r = client.post(
        f"/api/customers/{world['name']}/assessments/from-template/",
        headers=_token("ws5_owner"), json={"template_id": "customer-support"},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == (
        "An AI template cannot be seeded into a generic assessment. "
        "Archive it (or start an AI round) first."
    )
    # no use cases were seeded into the generic round
    from backend.models.use_case import UseCase
    assert db_session.query(UseCase).count() == 0


def test_use_case_payload_carries_round_type(client, db_session, world):
    """R5/R8 payload field: the use-case response exposes its round type so
    every FE surface can gate AI-only controls without an extra request."""
    gen = _round(db_session, world["cust"], "generic")
    uc_gen = _uc(db_session, world["cust"], gen.id, title="Gen UC")
    _round(db_session, world["cust"], "ai", status="archived")  # keep one generic active
    uc_legacy = _uc(db_session, world["cust"], None, title="Legacy UC")
    r = client.get(f"/api/use-cases/{uc_gen.id}/", headers=_token("ws5_owner"))
    assert r.status_code == 200
    assert r.json()["assessment_type"] == "generic"
    r = client.get(f"/api/use-cases/{uc_legacy.id}/", headers=_admin())
    assert r.status_code == 200
    assert r.json()["assessment_type"] == "ai"


def test_graph_node_uses_generic_domain_and_stable_id(db_session, world):
    """R7: a generic active round renders under its own 'assessment_generic'
    domain ('Generic Assessments') with the stable 'assessment-<id>' node id;
    an AI round is byte-identical to the pre-WS5 shape ('assessment' domain,
    'AI Assessments' hub) — including the unchanged node id."""
    from backend.models.use_case import CustomerAssessment
    from backend.services.customer_intelligence import build_customer_intelligence_graph

    gen = _round(db_session, world["cust"], "generic")
    g = build_customer_intelligence_graph(db_session, world["cust"])
    gen_nodes = [n for n in g["nodes"] if n["id"] == f"assessment-{gen.id}"]
    assert len(gen_nodes) == 1
    assert (gen_nodes[0]["type"], gen_nodes[0]["category"]) == ("assessment_generic", "assessment_generic")
    assert gen_nodes[0]["metadata"]["assessment_type"] == "generic"
    hubs = {n["label"]: n for n in g["nodes"] if n["type"] == "domain"}
    assert "Generic Assessments" in hubs
    assert "AI Assessments" not in hubs

    db_session.query(CustomerAssessment).filter(
        CustomerAssessment.id == gen.id).update({"status": "archived"}, synchronize_session=False)
    ai = _round(db_session, world["cust"], "ai")
    g2 = build_customer_intelligence_graph(db_session, world["cust"])
    ai_nodes = [n for n in g2["nodes"] if n["id"] == f"assessment-{ai.id}"]
    assert len(ai_nodes) == 1
    assert (ai_nodes[0]["type"], ai_nodes[0]["category"]) == ("assessment", "assessment")
    hubs2 = {n["label"] for n in g2["nodes"] if n["type"] == "domain"}
    assert "AI Assessments" in hubs2 and "Generic Assessments" not in hubs2
