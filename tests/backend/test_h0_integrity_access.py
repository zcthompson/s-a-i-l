"""H0 account integrity and shared read gates, using synthetic accounts only."""

import json
from datetime import UTC, datetime
from urllib.parse import quote

import pytest
from backend.models.account_membership import AccountMembership
from backend.models.collaboration import AuditLog, Comment, Notification, ScoreHistory
from backend.models.customer_alias import CustomerAlias
from backend.models.customer_contact import (
    ContactBuyingRole,
    CustomerContact,
    contact_notes,
    contact_technologies,
    contact_use_cases,
)
from backend.models.customer_knowledge import CustomerKnowledge, CustomerKnowledgeItem
from backend.models.customer_technology import CustomerTechnology
from backend.models.intelligence_import import IntelligenceImport, PartnerPipeline
from backend.models.netsuite_import import NetSuiteImport, NetSuiteImportNote, NetSuiteImportRow
from backend.models.redhat_opportunity_import import RedHatOpportunityImport, RedHatOpportunityRow
from backend.models.rep_intelligence import RepIntelligenceImport, RepIntelligenceRow
from backend.models.rvtools_import import RvToolsHost, RvToolsImport, RvToolsLicense, RvToolsVM
from backend.models.sales_access import InsideSalesAssignment, SalesOpsAssignment
from backend.models.sales_evaluation import SalesEvaluation
from backend.models.sales_note import SalesNote, sales_note_technologies, sales_note_use_cases
from backend.models.technology_dependency import TechnologyDependency
from backend.models.third_party_service import (
    ThirdPartyService,
    ThirdPartyServiceDocument,
    third_party_service_use_cases,
)
from backend.models.use_case import (
    AIPrediction,
    Base,
    Customer,
    CustomerAssessment,
    CustomerUser,
    Department,
    Projection,
    ReadinessInsight,
    UseCase,
    User,
)
from backend.services import customers_service
from backend.services.customer_access import require_account_read_service
from backend.services.intelligence_import_service import customer_pipeline
from backend.services.membership_service import actor_context
from backend.tools.customer_brief import generate_customer_brief
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, or_, select, text
from sqlalchemy.orm import Session

from tests.backend.common import _headers


def _snapshot(db):
    """Capture all tables, including retained batches, for rollback assertions."""
    return {name: list(db.execute(select(table).order_by(*table.primary_key.columns)).mappings())
            for name, table in Base.metadata.tables.items()}


def _account_inventory(db, customer_id):
    """Walk metadata for account columns and child FKs, without a table allowlist."""
    parent_ids = {"customers": [customer_id]}
    for name, table in Base.metadata.tables.items():
        if "customer_id" in table.c and "id" in table.c:
            parent_ids[name] = list(db.scalars(select(table.c.id).where(
                table.c.customer_id == customer_id)))
    inventory = {}
    for name, table in Base.metadata.tables.items():
        conditions = []
        if name == "customers":
            conditions.append(table.c.id == customer_id)
        if "customer_id" in table.c:
            conditions.append(table.c.customer_id == customer_id)
        for column in table.c:
            for fk in column.foreign_keys:
                if fk.column.table.name in parent_ids:
                    conditions.append(column.in_(parent_ids[fk.column.table.name]))
        if conditions:
            inventory[name] = (or_(*conditions), list(db.execute(
                select(table).where(or_(*conditions)).order_by(*table.primary_key.columns)
            ).mappings()))
    # A new table carrying one of the contract's reference columns must be
    # reached by the walk, even if no rows for that customer are present.
    referencing = {name for name, table in Base.metadata.tables.items()
                   if {"customer_id", "use_case_id", "technology_id", "import_id"} & set(table.c.keys())}
    assert referencing <= inventory.keys()
    return inventory


def _seed_integrity(db):
    """Populate every customer dependency for A and B plus shared history."""
    owner = User(username="h0_owner", email="h0_owner@test.local", hashed_password="unused",
                 is_admin=0, approved=1, is_active=1)
    db.add(owner)
    batches = [IntelligenceImport(file_name=f"pipeline-{i}.csv", file_sha256=str(i) * 64,
                                 file_data=b"synthetic", total_rows=2, matched_accounts=2,
                                 matched_rows=2, unmatched_accounts=0, unmatched_report="[]",
                                 imported_by="h0_owner") for i in (1, 2)]
    rep_batch = RepIntelligenceImport(
        file_name="rep.csv", file_sha256="a" * 64, file_data=b"synthetic", total_rows=2,
        imported_rows=2, imported_with_issues=0, skipped_rows=0, status="completed",
        technologies_created=2, technologies_refreshed=0, imported_by="h0_owner")
    redhat_batch = RedHatOpportunityImport(file_name="synthetic.xlsx", file_sha256="d" * 64,
        file_data=b"synthetic", imported_by="h0_owner", total_rows=2, matched_rows=2,
        matched_accounts=2, unmatched_json="[]")
    netsuite_batch = NetSuiteImport(file_name="synthetic.csv", file_sha256="e" * 64,
                                   layout="csv", imported_by="h0_owner")
    db.add_all([*batches, rep_batch, redhat_batch, netsuite_batch])
    db.flush()
    accounts = []
    for name in ("Alpha Corp", "Beta, Inc."):
        customer = Customer(name=name)
        db.add(customer)
        db.flush()
        accounts.append(customer)
        department = Department(customer_id=customer.id, name="IT")
        assessment = CustomerAssessment(customer_id=customer.id, name="Round one", created_by=owner.username)
        db.add_all([department, assessment])
        db.flush()
        uc = UseCase(customer_id=customer.id, department_id=department.id,
                     assessment_id=assessment.id, title=f"{name} initiative")
        techs = [CustomerTechnology(customer_id=customer.id, name=f"Platform {i}", category="software")
                 for i in (1, 2)]
        note = SalesNote(customer_id=customer.id, category="discovery", title="Discovery", content=name)
        service = ThirdPartyService(customer_id=customer.id, vendor_name="Synthetic Partner",
                                    service_category="technical", description="Synthetic service")
        rv = RvToolsImport(customer_id=customer.id, file_name="inventory.xlsx", file_sha256="b" * 64,
                           file_data=b"synthetic", host_count=1, vm_count=1, datastore_count=0,
                           license_count=1, imported_by=owner.username)
        docs = [CustomerKnowledge(customer_id=customer.id, knowledge_type="markdown",
                                  file_name=f"document-{i}.md", file_data=b"synthetic",
                                  uploaded_at=datetime.now(UTC)) for i in (1, 2)]
        db.add_all([uc, *techs, note, service, rv, *docs])
        db.flush()
        db.add_all([
            CustomerUser(customer_id=customer.id, user_id=owner.id, role="owner", granted_by=owner.id),
            AccountMembership(customer_id=customer.id, user_id=owner.id, role="inside_sales"),
            InsideSalesAssignment(customer_id=customer.id, inside_sales_user_id=owner.id),
            SalesOpsAssignment(customer_id=customer.id, user_id=owner.id),
            Projection(customer_id=customer.id, customer_name=name, projection_data={"synthetic": True}),
            ReadinessInsight(customer_id=customer.id, customer_name=name,
                             insight_data={"synthetic": True}, data_fingerprint="c" * 64),
            SalesEvaluation(customer_id=customer.id, evaluation_name="Synthetic evaluation"),
            ScoreHistory(use_case_id=uc.id, score=50),
            Comment(use_case_id=uc.id, user_name=owner.username, content="Synthetic comment"),
            AIPrediction(customer_id=customer.id, use_case_id=uc.id, horizon_days=30, predicted_score=50),
            Notification(customer_id=customer.id, user_name=owner.username, type="test", message=name),
            TechnologyDependency(customer_id=customer.id, source_id=techs[0].id,
                                 target_id=techs[1].id, relationship_type="depends_on"),
            ThirdPartyServiceDocument(customer_id=customer.id, service_id=service.id,
                                      document_type="sow", file_name="sow.txt", file_data=b"synthetic"),
            RvToolsHost(import_id=rv.id, host_name="synthetic-host"),
            RvToolsVM(import_id=rv.id, name="synthetic-vm"),
            RvToolsLicense(import_id=rv.id, name="synthetic-license"),
            RepIntelligenceRow(import_id=rep_batch.id, source_row=len(accounts),
                               customer_id=customer.id, technology_id=techs[0].id, status="imported"),
            NetSuiteImportRow(import_id=netsuite_batch.id, source_row=len(accounts),
                              customer_name=name, subscription_id="synthetic-subscription",
                              customer_id=customer.id, technology_id=techs[0].id,
                              risk_note_id=note.id, observation_note_id=note.id, disposition="created"),
            NetSuiteImportRow(import_id=netsuite_batch.id, source_row=10 + len(accounts),
                              customer_name=name, technology_id=techs[1].id, disposition="associated"),
            NetSuiteImportRow(import_id=netsuite_batch.id, source_row=20 + len(accounts),
                              customer_name=name, risk_note_id=note.id, disposition="skipped"),
            NetSuiteImportRow(import_id=netsuite_batch.id, source_row=30 + len(accounts),
                              customer_name=name, customer_id=customer.id, disposition="skipped"),
            NetSuiteImportNote(customer_id=customer.id, subscription_id="synthetic-subscription",
                               kind="term_ending", note_id=note.id),
            # Retained rows can have only an inventory link or only an account link.
            RepIntelligenceRow(import_id=rep_batch.id, source_row=10 + len(accounts),
                               technology_id=techs[1].id, status="imported"),
            RepIntelligenceRow(import_id=rep_batch.id, source_row=20 + len(accounts),
                               customer_id=customer.id, status="imported"),
            AuditLog(user_id=owner.id, username=owner.username, action="synthetic.before",
                     customer_id=customer.id, details="{}"),
            *[CustomerKnowledgeItem(customer_id=customer.id, source_knowledge_id=doc.id,
                                    kind="customer_fact", name="Synthetic fact") for doc in docs],
            *[PartnerPipeline(customer_id=customer.id, import_id=batch.id,
                              customer_account_name=name, source_row=len(accounts)) for batch in batches],
            RedHatOpportunityRow(customer_id=customer.id, import_id=redhat_batch.id,
                                 source_row=len(accounts), source_account=name,
                                 matched_by="name", fields_json="{}"),
            # Part 14 (A1): alias tags are account-owned metadata — the
            # metadata-derived walk covers them; the delete must too.
            CustomerAlias(customer_id=customer.id, alias=f"{name} Synthetic",
                          alias_norm=f"{name.lower()} synthetic", created_by=owner.username),
            CustomerAlias(customer_id=customer.id, alias=f"Second {name} Synthetic",
                          alias_norm=f"second {name.lower()} synthetic", created_by=owner.username),
        ])
        contact = CustomerContact(customer_id=customer.id, display_name="Synthetic contact")
        db.add(contact)
        db.flush()
        from backend.models.customer_engagement import (
            CustomerActivity,
            CustomerTask,
            TaskNotificationWindow,
            activity_contacts,
            task_evidence_activities,
            task_evidence_notes,
        )
        activity = CustomerActivity(customer_id=customer.id, type="call", actor=owner.username,
                                    occurred_date=datetime.now(UTC).date(), created_by=owner.username)
        task = CustomerTask(customer_id=customer.id, title="Synthetic follow-up", created_by=owner.username)
        db.add_all([activity, task])
        db.flush()
        db.execute(activity_contacts.insert().values(activity_id=activity.id, contact_id=contact.id))
        db.execute(task_evidence_notes.insert().values(task_id=task.id, note_id=note.id))
        db.execute(task_evidence_activities.insert().values(task_id=task.id, activity_id=activity.id))
        db.add(TaskNotificationWindow(task_id=task.id, window="due_soon", user_name=owner.username))
        db.add(ContactBuyingRole(contact_id=contact.id, role="champion"))
        db.execute(contact_notes.insert().values(contact_id=contact.id, note_id=note.id))
        db.execute(contact_use_cases.insert().values(contact_id=contact.id, use_case_id=uc.id))
        db.execute(contact_technologies.insert().values(contact_id=contact.id, technology_id=techs[0].id))
        db.execute(sales_note_use_cases.insert().values(note_id=note.id, use_case_id=uc.id))
        db.execute(sales_note_technologies.insert().values(note_id=note.id, technology_id=techs[0].id))
        db.execute(third_party_service_use_cases.insert().values(service_id=service.id, use_case_id=uc.id))
        from backend.models.account_strategy import (
            AccountStrategy,
            AccountStrategySnapshot,
            strategy_contact_links,
            strategy_note_links,
            strategy_task_links,
        )
        strategy = AccountStrategy(customer_id=customer.id, objectives="Synthetic strategy",
                                   version=1, created_by=owner.username, updated_by=owner.username)
        db.add(strategy)
        db.flush()
        db.add(AccountStrategySnapshot(customer_id=customer.id, plan_number=1, note="Synthetic publish",
                                       published_by=owner.username,
                                       content={"objectives": "Synthetic strategy", "desired_outcomes": None,
                                                "risks": None, "plays": None, "discovery_gaps": None,
                                                "version": 1}))
        db.execute(strategy_task_links.insert().values(strategy_id=strategy.id, task_id=task.id))
        db.execute(strategy_contact_links.insert().values(strategy_id=strategy.id, contact_id=contact.id))
        db.execute(strategy_note_links.insert().values(strategy_id=strategy.id, note_id=note.id))
        # E6 deals with every link kind and stage history.
        from backend.models.deal import (
            Deal,
            DealStageHistory,
            PipelineStage,
            deal_activities,
            deal_contacts,
            deal_notes,
            deal_tasks,
            deal_technologies,
            deal_vendor_evidence,
        )
        stage = db.query(PipelineStage).filter_by(key="synthetic_open").first()
        if stage is None:
            stage = PipelineStage(key="synthetic_open", label="Synthetic open", stage_class="open", position=1, active=True)
            db.add(stage)
            db.flush()
        deal = Deal(customer_id=customer.id, name="Synthetic deal", stage_id=stage.id, created_by=owner.username,
                    owner_user_id=owner.id, owner_name=owner.username)
        db.add(deal)
        db.flush()
        db.add(DealStageHistory(deal_id=deal.id, to_stage_id=stage.id, actor=owner.username, at=datetime.now(UTC)))
        db.execute(deal_contacts.insert().values(deal_id=deal.id, contact_id=contact.id, role="champion"))
        db.execute(deal_tasks.insert().values(deal_id=deal.id, task_id=task.id))
        db.execute(deal_activities.insert().values(deal_id=deal.id, activity_id=activity.id))
        db.execute(deal_notes.insert().values(deal_id=deal.id, note_id=note.id))
        db.execute(deal_technologies.insert().values(deal_id=deal.id, technology_id=techs[0].id))
        db.execute(deal_vendor_evidence.insert().values(deal_id=deal.id, import_id=batches[0].id, opportunity_number="SYNTHETIC"))
    db.commit()
    return accounts


def _assert_deleted(db, before):
    for name, (condition, rows) in before.items():
        if name in ("audit_logs", "rep_intelligence_rows", "netsuite_import_rows"):
            assert rows
            table = Base.metadata.tables[name]
            retained = list(db.execute(select(table).where(table.c.id.in_([r["id"] for r in rows]))).mappings())
            assert len(retained) == len(rows)
            if name == "rep_intelligence_rows":
                assert all(r["customer_id"] is None and r["technology_id"] is None for r in retained)
            elif name == "netsuite_import_rows":
                assert all(r["customer_id"] is None and r["technology_id"] is None
                           and r["risk_note_id"] is None and r["observation_note_id"] is None
                           and r["disposition"] == "customer_deleted" for r in retained)
            else:
                assert retained == rows
        else:
            assert rows, f"fixture must exercise {name}"
            assert db.scalar(select(func.count()).select_from(Base.metadata.tables[name]).where(condition)) == 0, name


def test_delete_covers_metadata_with_foreign_keys_off(client, db_session):
    db_session.commit()
    if db_session.bind.dialect.name == "sqlite":
        db_session.execute(text("PRAGMA foreign_keys=OFF"))
        db_session.commit()
        assert db_session.scalar(text("PRAGMA foreign_keys")) == 0
    a, b = _seed_integrity(db_session)
    a_id, a_name, b_id = a.id, a.name, b.id
    before_a = _account_inventory(db_session, a_id)
    before_b = _account_inventory(db_session, b_id)
    batches = {name: rows for name, rows in _snapshot(db_session).items()
               if name in ("intelligence_imports", "rep_intelligence_imports", "redhat_opportunity_imports")}
    db_session.commit()
    response = client.delete(f"/api/customers/{quote(a_name, safe='')}/", headers=_headers("h0_owner"))
    assert response.status_code == 204, response.text
    db_session.expire_all()
    _assert_deleted(db_session, before_a)
    assert {n: rows for n, (_, rows) in _account_inventory(db_session, b_id).items()} == {
        n: rows for n, (_, rows) in before_b.items()}
    after = _snapshot(db_session)
    assert {name: after[name] for name in batches} == batches
    audit = db_session.query(AuditLog).filter_by(action="customer.delete").one()
    assert audit.customer_id == a_id and audit.username == "h0_owner" and audit.target_id is None
    details = json.loads(audit.details)
    assert details["customer_name"] == a_name
    assert details["deleted_counts"] == {name: len(rows) for name, (_, rows) in before_a.items()
                                         if name not in ("audit_logs", "rep_intelligence_rows", "netsuite_import_rows")}
    assert customer_pipeline(db_session, b.name)["import_id"] == batches["intelligence_imports"][-1]["id"]
    with pytest.raises(HTTPException) as exc:
        customer_pipeline(db_session, a_name)
    assert exc.value.status_code == 404


def test_delete_covers_metadata_with_foreign_keys_on(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'h0-fk-on.db'}")
    try:
        with engine.connect() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
            Base.metadata.create_all(connection)
            connection.commit()
            with Session(bind=connection) as db:
                a, b = _seed_integrity(db)
                before_a = _account_inventory(db, a.id)
                before_b = _account_inventory(db, b.id)
                batches = db.query(IntelligenceImport).count(), db.query(RepIntelligenceImport).count()
                customers_service.delete_customer_with_use_cases(db, a)
                db.commit()
                _assert_deleted(db, before_a)
                assert {n: rows for n, (_, rows) in _account_inventory(db, b.id).items()} == {
                    n: rows for n, (_, rows) in before_b.items()}
                assert (db.query(IntelligenceImport).count(), db.query(RepIntelligenceImport).count()) == batches
                assert list(db.execute(text("PRAGMA foreign_key_check"))) == []
    finally:
        engine.dispose()


def test_delete_failure_rolls_back_helpers_and_all_tables(client, db_session, monkeypatch):
    a, b = _seed_integrity(db_session)
    name = a.name
    before = _snapshot(db_session)
    db_session.commit()
    original = customers_service.delete_customer_knowledge
    completed = []

    def fail_after_helper_commit(*args):
        result = original(*args)
        completed.append(args[1])
        if len(completed) == 2:
            raise RuntimeError("synthetic failure after confined helper commits")
        return result

    monkeypatch.setattr(customers_service, "delete_customer_knowledge", fail_after_helper_commit)
    # Use the real route/dependency/client path, while letting TestClient
    # return the server's 500 instead of re-raising its exception.
    with TestClient(client.app, raise_server_exceptions=False) as failing_client:
        response = failing_client.delete(f"/api/customers/{quote(name, safe='')}/",
                                         headers=_headers("h0_owner"))
    assert response.status_code == 500
    assert len(completed) == 2
    db_session.expire_all()
    assert _snapshot(db_session) == before
    assert db_session.query(AuditLog).filter_by(action="customer.delete").count() == 0


def test_pipeline_retained_batch_falls_back_or_returns_empty(db_session):
    a, b = _seed_integrity(db_session)
    latest = customer_pipeline(db_session, a.name)["import_id"]
    db_session.query(PartnerPipeline).filter_by(customer_id=a.id, import_id=latest).delete()
    db_session.commit()
    older = customer_pipeline(db_session, a.name)
    assert older["import_id"] < latest and len(older["rows"]) == 1
    db_session.query(PartnerPipeline).filter_by(customer_id=a.id).delete()
    db_session.commit()
    empty = customer_pipeline(db_session, a.name)
    assert empty["import_id"] is None and empty["source_file"] is None and empty["rows"] == []
    assert customer_pipeline(db_session, b.name)["import_id"] == latest
    assert db_session.query(IntelligenceImport).count() == 2


@pytest.fixture()
def access_world(db_session):
    a, b = Customer(name="Alpha Corp"), Customer(name="Beta, Inc.")
    db_session.add_all([a, b])
    db_session.flush()
    users = {}
    for name, sales_role, role in (("h0_member", None, None), ("h0_other", None, None),
                                   ("h0_auditor", "auditor", None), ("h0_ps", None, "ps_admin"),
                                   ("h0_outsider", None, None), ("h0_sales_admin", "sales_admin", None)):
        user = User(username=name, email=f"{name}@test.local", hashed_password="unused",
                    is_admin=0, approved=1, is_active=1, sales_role=sales_role, role=role)
        db_session.add(user)
        db_session.flush()
        users[name] = user.id
    db_session.add_all([
        CustomerUser(customer_id=a.id, user_id=users["h0_member"], role="member"),
        CustomerUser(customer_id=b.id, user_id=users["h0_other"], role="member"),
    ])
    db_session.commit()
    return a.id, b.id, users


@pytest.mark.parametrize("name, status", [("h0_member", 200), ("h0_other", 403),
                                          ("h0_outsider", 403), ("h0_auditor", 200),
                                          ("h0_ps", 403), ("h0_sales_admin", 200), ("admin", 200)])
def test_account_read_service_without_request(db_session, access_world, name, status):
    a_id, b_id, users = access_world
    user = db_session.query(User).filter_by(username=name).one()
    context = actor_context(db_session, user.id)
    if status == 200:
        assert require_account_read_service(db_session, context, a_id).id == a_id
    else:
        with pytest.raises(HTTPException) as exc:
            require_account_read_service(db_session, context, a_id)
        assert exc.value.status_code == status
    with pytest.raises(HTTPException) as exc:
        require_account_read_service(db_session, context, 999999)
    assert exc.value.status_code == 404


@pytest.mark.parametrize("surface", ["overview", "workspace", "graph"])
# Out-of-scope callers get the same 404 as a missing customer (404-first, R4/Q7).
@pytest.mark.parametrize("name, status", [(None, 401), ("h0_member", 200), ("h0_other", 404),
                                          ("h0_outsider", 404), ("h0_auditor", 200),
                                          ("h0_ps", 404), ("h0_sales_admin", 200), ("admin", 200)])
def test_intelligence_http_read_policy(client, access_world, surface, name, status):
    a_id, b_id, users = access_world
    headers = _headers(name) if name else {}
    response = client.get(f"/api/customers/{a_id}/intelligence/{surface}/", headers=headers)
    assert response.status_code == status, response.text
    missing = client.get(f"/api/customers/999999/intelligence/{surface}/", headers=headers)
    assert missing.status_code == (404 if name else 401)


def test_brief_authorizes_before_assembly_and_isolates_accounts(db_session, access_world):
    a_id, b_id, users = access_world
    context = actor_context(db_session, users["h0_other"])

    class UnreadableContent:
        def __iter__(self):
            raise AssertionError("unauthorized input was inspected before the account gate")

    with pytest.raises(HTTPException) as exc:
        generate_customer_brief(db_session, context, a_id, UnreadableContent())
    assert exc.value.status_code == 403
    use_cases = [
        {"customer_id": a_id, "title": "Alpha secret", "overall_score": 90, "vendor": "Alpha vendor"},
        {"customer_id": b_id, "title": "Beta initiative", "overall_score": 80, "vendor": "Beta vendor"},
    ]
    for user in (context, {"is_admin": 1}, {"sales_role": "auditor"}):
        brief = generate_customer_brief(db_session, user, b_id, use_cases)
        assert brief["summary"]["total_use_cases"] == 1
        assert brief["key_use_cases"][0]["title"] == "Beta initiative"
        assert "Alpha" not in json.dumps(brief)
