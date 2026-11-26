"""Sales evaluation engine tests — direct engine calls and route authorization.

The engine (backend/services/evaluation_engine.py) is fully deterministic:
it reads use cases + customer knowledge from the DB and computes
readiness/environment/gap/risk/growth/sales-approach values arithmetically.
No LLM calls — these tests exercise the deterministic path only.

Route tests follow the repo's TestClient auth pattern (test_integration.py):
a real JWT via create_access_token. Admins (is_admin=1) bypass the
CustomerUser junction check — the same convention as customers.py /
sales_section.py. The 403 test uses a non-admin user with no junction row.
"""

from datetime import UTC, datetime

import pytest
from backend.models.sales_evaluation import SalesEvaluation
from backend.services.evaluation_engine import create_sales_evaluation

from tests.backend.common import _admin_headers


@pytest.fixture()
def customer_1(db_session):
    """Seed a customer and return it (route POSTs 404 without a Customer row)."""
    from backend.models.use_case import Customer

    c = Customer(name="Sales Eval Test Customer", description="deterministic test customer")
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)
    return c


def _seed_environment(db_session, customer_id: int) -> None:
    """Seed a scored use case plus software + hardware knowledge rows."""
    from backend.models.customer_knowledge import CustomerKnowledge as CKModel
    from backend.models.use_case import UseCase

    uc = UseCase(
        title="Test Use Case",
        description="Testing sales evaluation",
        customer_id=customer_id,
        overall_score=85.5,
        scores={"technical_feasibility": 90.0, "financial_viability": 81.0},
    )
    db_session.add(uc)

    kw1 = CKModel(
        customer_id=customer_id,
        knowledge_type="software_inventory",
        file_name="sw_inventory.csv",
        file_data=b"software,version,status,vendor\nPostgreSQL,13,commercial,ACME Corp\n",
        uploaded_at=datetime.now(UTC),
        extracted_text="PostgreSQL 13 commercial ACME Corp",
    )
    kw2 = CKModel(
        customer_id=customer_id,
        knowledge_type="hardware_inventory",
        file_name="hw_inventory.csv",
        file_data=b"hardware,model,status\nServer R740,active\n",
        uploaded_at=datetime.now(UTC),
        extracted_text="Server R740 active",
    )
    db_session.add_all([kw1, kw2])
    db_session.commit()


class TestSalesEvaluationEngine:
    """Direct engine tests for create_sales_evaluation."""

    def test_engine_direct_with_customer_data(self, db_session, customer_1):
        """Engine direct: seed customer + use cases + knowledge, then create."""
        _seed_environment(db_session, customer_1.id)

        evaluation = create_sales_evaluation(
            db=db_session,
            customer_id=customer_1.id,
            evaluation_name="Test Sales Evaluation",
        )

        assert evaluation is not None
        assert evaluation.evaluation_name == "Test Sales Evaluation"
        assert isinstance(evaluation.readiness_overall, float)
        assert 0 <= evaluation.readiness_overall <= 100
        assert isinstance(evaluation.readiness_dimensions, dict)
        assert isinstance(evaluation.environment_score, float)
        assert 0 <= evaluation.environment_score <= 100
        assert isinstance(evaluation.environment_factors, dict)
        assert isinstance(evaluation.risk_factors, list)
        assert isinstance(evaluation.growth_opportunities, list)
        assert isinstance(evaluation.sales_approach, dict)

        # The record is persisted
        persisted = (
            db_session.query(SalesEvaluation)
            .filter(SalesEvaluation.id == evaluation.id)
            .first()
        )
        assert persisted is not None
        assert persisted.evaluation_name == "Test Sales Evaluation"

    def test_engine_deterministic_no_real_inference(self, db_session, customer_1):
        """create_sales_evaluation is fully deterministic for fixed data —
        two evaluations from the same inputs produce identical scores."""
        _seed_environment(db_session, customer_1.id)

        eval1 = create_sales_evaluation(
            db=db_session, customer_id=customer_1.id, evaluation_name="Det Evaluation 1"
        )
        eval2 = create_sales_evaluation(
            db=db_session, customer_id=customer_1.id, evaluation_name="Det Evaluation 2"
        )

        assert eval1.readiness_overall == eval2.readiness_overall
        assert eval1.environment_score == eval2.environment_score
        assert eval1.readiness_dimensions == eval2.readiness_dimensions
        assert eval1.evaluation_name != eval2.evaluation_name

    def test_engine_with_no_environment_data(self, db_session, customer_1):
        """Engine handles a customer with no use cases or knowledge (defaults)."""
        evaluation = create_sales_evaluation(
            db=db_session,
            customer_id=customer_1.id,
            evaluation_name="Empty Customer Evaluation",
        )
        assert evaluation is not None
        assert isinstance(evaluation.readiness_overall, float)
        assert 0 <= evaluation.readiness_overall <= 100
        assert isinstance(evaluation.environment_score, float)
        assert 0 <= evaluation.environment_score <= 100


class TestSalesEvaluationRoutes:
    """Route authorization and CRUD tests for the sales-evaluations endpoints."""

    def test_unauthenticated_gets_401(self, client, db_session, customer_1):
        r = client.get(f"/api/sales-evaluations/?customer_id={customer_1.id}")
        assert r.status_code == 401

    def test_admin_can_post_evaluation(self, client, db_session, customer_1):
        """Admin POSTs /api/sales-evaluations/?customer_id=N — 200 plus an id."""
        _seed_environment(db_session, customer_1.id)

        r = client.post(
            f"/api/sales-evaluations/?customer_id={customer_1.id}",
            json={"evaluation_name": "Route Test Evaluation"},
            headers=_admin_headers(db_session),
        )
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
        assert data["evaluation_name"] == "Route Test Evaluation"

    def test_admin_gets_list(self, client, db_session, customer_1):
        """Admin: GET list returns the created evaluation."""
        _seed_environment(db_session, customer_1.id)

        r = client.post(
            f"/api/sales-evaluations/?customer_id={customer_1.id}",
            json={"evaluation_name": "List Test Evaluation"},
            headers=_admin_headers(db_session),
        )
        assert r.status_code == 200

        r = client.get(
            f"/api/sales-evaluations/?customer_id={customer_1.id}",
            headers=_admin_headers(db_session),
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1
        assert any(e["evaluation_name"] == "List Test Evaluation" for e in data)

    def test_admin_gets_single_evaluation(self, client, db_session, customer_1):
        """Admin: per-id GET returns the evaluation."""
        _seed_environment(db_session, customer_1.id)

        r = client.post(
            f"/api/sales-evaluations/?customer_id={customer_1.id}",
            json={"evaluation_name": "Get Test Evaluation"},
            headers=_admin_headers(db_session),
        )
        assert r.status_code == 200
        eval_id = r.json()["id"]

        r = client.get(f"/api/sales-evaluations/{eval_id}", headers=_admin_headers(db_session))
        assert r.status_code == 200
        assert r.json()["evaluation_name"] == "Get Test Evaluation"

    def test_admin_can_put_evaluation(self, client, db_session, customer_1):
        """Admin: PUT updates name and status."""
        _seed_environment(db_session, customer_1.id)

        r = client.post(
            f"/api/sales-evaluations/?customer_id={customer_1.id}",
            json={"evaluation_name": "Put Test Evaluation"},
            headers=_admin_headers(db_session),
        )
        assert r.status_code == 200
        eval_id = r.json()["id"]

        r = client.put(
            f"/api/sales-evaluations/{eval_id}",
            json={"evaluation_name": "Updated Evaluation", "status": "active"},
            headers=_admin_headers(db_session),
        )
        assert r.status_code == 200
        assert r.json()["evaluation_name"] == "Updated Evaluation"
        assert r.json()["status"] == "active"

    def test_admin_can_delete_evaluation(self, client, db_session, customer_1):
        """Admin: DELETE removes the evaluation (subsequent GET is 404)."""
        _seed_environment(db_session, customer_1.id)

        r = client.post(
            f"/api/sales-evaluations/?customer_id={customer_1.id}",
            json={"evaluation_name": "Delete Test Evaluation"},
            headers=_admin_headers(db_session),
        )
        assert r.status_code == 200
        eval_id = r.json()["id"]

        r = client.delete(f"/api/sales-evaluations/{eval_id}", headers=_admin_headers(db_session))
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"

        r = client.get(f"/api/sales-evaluations/{eval_id}", headers=_admin_headers(db_session))
        assert r.status_code == 404

    def test_non_admin_without_customer_user_404_list_404_by_id(self, client, db_session, customer_1):
        """Non-admin user with NO CustomerUser row: the same 404 as a missing
        customer on list AND on per-id get (404-first, R4/Q7 — no oracle)."""
        from backend.auth import create_access_token, hash_password
        from backend.models.use_case import User

        member = User(
            username="member_403",
            email="member403@test.local",
            hashed_password=hash_password("member_403"),
            display_name="Member 403",
            department="Sales",
            is_admin=0,
            approved=1,
            is_active=1,
        )
        db_session.add(member)
        db_session.commit()
        headers = {
            "Authorization": f"Bearer {create_access_token({'sub': 'member_403', 'is_admin': False})}"
        }

        # 404 on list — no CustomerUser row for this customer (R4/Q7)
        r = client.get(f"/api/sales-evaluations/?customer_id={customer_1.id}", headers=headers)
        assert r.status_code == 404

        # per-id get of an existing evaluation: the same 404 as a missing one
        # (404-first, R4/Q7)
        _seed_environment(db_session, customer_1.id)
        admin_r = client.post(
            f"/api/sales-evaluations/?customer_id={customer_1.id}",
            json={"evaluation_name": "ShouldNotSee"},
            headers=_admin_headers(db_session),
        )
        assert admin_r.status_code == 200
        eval_id = admin_r.json()["id"]

        r = client.get(f"/api/sales-evaluations/{eval_id}", headers=headers)
        assert r.status_code == 404
        assert r.json()["detail"] == "Evaluation not found"


class TestAuditorWriteGap:
    """shift-to-global-customer-management phase 3 — the auditor write gap.

    An ``auditor`` junction role is read-only: it has a CustomerUser row for the
    customer (so the READ gate passes), but mutations must be rejected by the
    central resolver's EDIT capability (a read gate is not a write gate,
    directive §4 rule 8). A legacy ``owner`` junction (no sales_role) must
    still write — no lockout (directive §3 / legacy preservation).
    """

    def _user_headers(self, db_session, username):
        from backend.auth import create_access_token
        return {"Authorization": f"Bearer {create_access_token({'sub': username, 'is_admin': False})}"}

    def _mk_user(self, db_session, username, role):
        from backend.auth import hash_password
        from backend.models.use_case import Customer, CustomerUser, User
        u = User(
            username=username, email=f"{username}@test.local",
            hashed_password=hash_password(username), display_name=username,
            department="Sales", is_admin=0, approved=1, is_active=1,
        )
        db_session.add(u)
        db_session.flush()
        cust = db_session.query(Customer).filter(Customer.name == "Sales Eval Test Customer").first()
        db_session.add(CustomerUser(customer_id=cust.id, user_id=u.id, role=role, granted_by=u.id))
        db_session.commit()
        return u

    def test_auditor_read_ok_write_denied(self, client, db_session, customer_1):
        self._mk_user(db_session, "auditor_x", "auditor")
        headers = self._user_headers(db_session, "auditor_x")
        _seed_environment(db_session, customer_1.id)

        # Read gate: auditor (junction row) may LIST.
        r = client.get(f"/api/sales-evaluations/?customer_id={customer_1.id}", headers=headers)
        assert r.status_code == 200

        # Admin creates an evaluation the auditor can then read.
        admin_r = client.post(
            f"/api/sales-evaluations/?customer_id={customer_1.id}",
            json={"evaluation_name": "AuditorReadOnly"},
            headers=_admin_headers(db_session),
        )
        assert admin_r.status_code == 200
        eval_id = admin_r.json()["id"]

        # Read gate: auditor may GET the single evaluation.
        r = client.get(f"/api/sales-evaluations/{eval_id}", headers=headers)
        assert r.status_code == 200

        # WRITE gap: auditor is rejected on create / update / delete.
        r = client.post(
            f"/api/sales-evaluations/?customer_id={customer_1.id}",
            json={"evaluation_name": "AuditorShouldNotCreate"},
            headers=headers,
        )
        assert r.status_code == 403, f"auditor create should be 403, got {r.status_code}"
        r = client.put(f"/api/sales-evaluations/{eval_id}", json={"evaluation_name": "x"}, headers=headers)
        assert r.status_code == 403, f"auditor update should be 403, got {r.status_code}"
        r = client.delete(f"/api/sales-evaluations/{eval_id}", headers=headers)
        assert r.status_code == 403, f"auditor delete should be 403, got {r.status_code}"

    def test_legacy_owner_junction_still_writes(self, client, db_session, customer_1):
        """No sales_role, just a CustomerUser owner junction -> must write (no lockout)."""
        self._mk_user(db_session, "owner_legacy", "owner")
        headers = self._user_headers(db_session, "owner_legacy")
        _seed_environment(db_session, customer_1.id)

        r = client.post(
            f"/api/sales-evaluations/?customer_id={customer_1.id}",
            json={"evaluation_name": "LegacyOwnerWrites"},
            headers=headers,
        )
        assert r.status_code == 200, f"legacy owner create should pass, got {r.status_code} {r.text[:200]}"
        eval_id = r.json()["id"]

        r = client.put(f"/api/sales-evaluations/{eval_id}", json={"status": "completed"}, headers=headers)
        assert r.status_code == 200

        r = client.delete(f"/api/sales-evaluations/{eval_id}", headers=headers)
        assert r.status_code == 200
