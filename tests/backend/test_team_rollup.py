"""Synthetic E4 scope, coverage and fixed-query checks."""

from datetime import UTC, datetime

from backend.models.customer_contact import ContactBuyingRole, CustomerContact
from backend.models.customer_engagement import CustomerActivity, CustomerTask
from backend.models.intelligence_import import IntelligenceImport, PartnerPipeline
from backend.models.sales_access import SalesReporting
from backend.models.use_case import Customer, CustomerUser, User
from backend.services.team_rollup_service import team_rollup_for

from tests.backend.test_customer_contacts import headers, statements


def test_team_rollup_scope_shared_owners_and_coverage(client, db_session):
    manager = User(username="team_manager", sales_role="sales_manager", is_active=1, approved=1)
    reps = [User(username=f"team_rep_{i}", sales_role="rep", is_active=1, approved=1) for i in range(2)]
    outsider = User(username="outside_rep", sales_role="rep", is_active=1, approved=1)
    inactive = User(username="inactive_rep", sales_role="rep", is_active=0, approved=1)
    accounts = [Customer(name=f"Synthetic rollup {i}") for i in range(3)]
    batch = IntelligenceImport(file_name="synthetic.csv", file_sha256="f" * 64, file_data=b"",
        total_rows=2, matched_accounts=2, matched_rows=2, unmatched_accounts=0,
        unmatched_report="[]", imported_by="team_manager")
    db_session.add_all([manager, *reps, outsider, inactive, *accounts, batch])
    db_session.flush()
    db_session.add_all([SalesReporting(manager_user_id=manager.id, rep_user_id=rep.id) for rep in reps])
    db_session.add(SalesReporting(manager_user_id=manager.id, rep_user_id=inactive.id))
    db_session.add_all([CustomerUser(customer_id=accounts[0].id, user_id=rep.id, role="owner") for rep in reps])
    db_session.add(CustomerUser(customer_id=accounts[1].id, user_id=reps[1].id, role="owner"))
    db_session.add(CustomerUser(customer_id=accounts[2].id, user_id=outsider.id, role="owner"))
    db_session.add_all([
        PartnerPipeline(customer_id=accounts[0].id, import_id=batch.id, customer_account_name="Synthetic",
            opportunity_number="a", source_row=1, est_acv_usd=100,
            current_contract_end_date=datetime(2025, 1, 1).date()),
        PartnerPipeline(customer_id=accounts[0].id, import_id=batch.id, customer_account_name="Synthetic",
            opportunity_number="a", source_row=2, est_acv_usd=None),
        PartnerPipeline(customer_id=accounts[2].id, import_id=batch.id, customer_account_name="Synthetic",
            opportunity_number="secret", source_row=3, est_acv_usd=9999),
        CustomerTask(customer_id=accounts[0].id, title="Synthetic", created_by="team_manager",
                     due_date=datetime(2025, 1, 1).date()),
        CustomerActivity(customer_id=accounts[0].id, type="call", actor="team_manager",
                         created_by="team_manager", occurred_date=datetime(2025, 1, 1).date()),
    ])
    contact = CustomerContact(customer_id=accounts[0].id, display_name="Synthetic contact")
    db_session.add(contact)
    db_session.flush()
    db_session.add(ContactBuyingRole(contact_id=contact.id, role="economic_buyer"))
    db_session.commit()
    response = client.get("/api/rollups/team/", headers=headers(manager.username))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["team"]["accounts"] == 2
    assert result["team"]["pipeline"]["acv"] == {"total": 100.0, "coverage": "partial",
        "lines_included": 1, "lines_excluded": 1, "accounts_no_data": 1}
    assert [rep["accounts"] for rep in result["reps"]] == [1, 2]
    assert result["team"]["open_tasks"] == 1
    assert result["team"]["overdue_tasks"] == 1
    assert result["team"]["renewal_counts"]["overdue"] == 1
    assert result["team"]["no_recorded_interaction"] == 1
    assert result["team"]["no_contacts_recorded"] == 1
    assert result["team"]["no_economic_buyer_recorded"] == 1
    assert result["team"]["no_champion_recorded"] == 2
    assert client.get("/api/rollups/team/", headers=headers(outsider.username)).status_code == 403
    assert client.get("/api/rollups/team/").status_code == 401


def test_team_rollup_fixed_queries_and_cycle(db_session):
    manager = User(username="scale_manager", sales_role="sales_manager", is_active=1, approved=1)
    reps = [User(username=f"scale_rep_{i:02}", sales_role="rep", is_active=1, approved=1) for i in range(50)]
    accounts = [Customer(name=f"Synthetic scale {i:04}") for i in range(1000)]
    batch = IntelligenceImport(file_name="scale.csv", file_sha256="a" * 64, file_data=b"",
        total_rows=1000, matched_accounts=1000, matched_rows=1000, unmatched_accounts=0,
        unmatched_report="[]", imported_by="scale_manager")
    db_session.add_all([manager, *reps, *accounts, batch])
    db_session.flush()
    db_session.add_all([SalesReporting(manager_user_id=manager.id, rep_user_id=rep.id) for rep in reps[:-1]])
    db_session.add(SalesReporting(manager_user_id=reps[0].id, rep_user_id=reps[-1].id))
    db_session.add(SalesReporting(manager_user_id=reps[0].id, rep_user_id=manager.id))
    db_session.add_all([CustomerUser(customer_id=account.id, user_id=reps[i % len(reps)].id, role="owner")
                        for i, account in enumerate(accounts)])
    db_session.add_all([PartnerPipeline(customer_id=account.id, import_id=batch.id,
        customer_account_name="Synthetic", opportunity_number=f"opp-{i}", source_row=i,
        est_acv_usd=1.0) for i, account in enumerate(accounts)])
    db_session.commit()
    ctx = {"username": manager.username, "sales_role": "sales_manager", "role": "user", "is_admin": 0}
    with statements(db_session) as sql:
        result = team_rollup_for(db_session, ctx, datetime(2026, 11, 4, tzinfo=UTC))
    assert len(sql) <= 15
    assert len(result["reps"]) == 50 and result["team"]["accounts"] == 1000
    assert all(rep["accounts"] == 20 for rep in result["reps"])
    assert result["team"]["pipeline"]["acv"]["total"] == 1000.0
