"""Explicit child cleanup for record deletion (ER-12).

Runtime SQLite never enforces the schema's declared ON DELETE actions
(``PRAGMA foreign_keys`` is off), so every delete path must remove or clear
child rows itself. A surviving link row could otherwise attach to a later
record that reuses the deleted ID, possibly in another account.

Each function stages its statements on the caller's session and takes a list
of parent IDs; the caller deletes the parents and owns commit/rollback.
Account and user deletion have their own complete paths
(``customers_service.delete_customer_with_use_cases``,
``UserService.delete_user``).
"""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.models.account_strategy import (
    strategy_contact_links,
    strategy_note_links,
    strategy_task_links,
)
from backend.models.collaboration import Comment, ScoreHistory
from backend.models.customer_contact import (
    ContactBuyingRole,
    contact_notes,
    contact_technologies,
    contact_use_cases,
)
from backend.models.customer_engagement import (
    TaskNotificationWindow,
    activity_contacts,
    task_evidence_activities,
    task_evidence_notes,
)
from backend.models.customer_technology import CustomerTechnology
from backend.models.deal import (
    DealStageHistory,
    deal_activities,
    deal_contacts,
    deal_notes,
    deal_tasks,
    deal_technologies,
    deal_vendor_evidence,
)
from backend.models.netsuite_import import NetSuiteImportNote, NetSuiteImportRow
from backend.models.rep_intelligence import RepIntelligenceRow
from backend.models.sales_note import SalesNote, sales_note_technologies, sales_note_use_cases
from backend.models.technology_dependency import TechnologyDependency
from backend.models.third_party_service import (
    ThirdPartyServiceDocument,
    third_party_service_use_cases,
)
from backend.models.use_case import AIPrediction


def _links(db: Session, table, column, ids) -> None:
    db.execute(table.delete().where(column.in_(ids)))


def technologies(db: Session, ids) -> None:
    """Links, dependencies and retained import evidence of technologies."""
    ids = list(ids)
    if not ids:
        return
    _links(db, contact_technologies, contact_technologies.c.technology_id, ids)
    _links(db, sales_note_technologies, sales_note_technologies.c.technology_id, ids)
    _links(db, deal_technologies, deal_technologies.c.technology_id, ids)
    db.query(TechnologyDependency).filter(or_(
        TechnologyDependency.source_id.in_(ids), TechnologyDependency.target_id.in_(ids),
    )).delete(synchronize_session=False)
    # Import rows are history: keep them, without the inventory link.
    db.query(RepIntelligenceRow).filter(RepIntelligenceRow.technology_id.in_(ids)).update(
        {RepIntelligenceRow.technology_id: None}, synchronize_session=False)

    db.query(NetSuiteImportRow).filter(NetSuiteImportRow.technology_id.in_(ids)).update(
        {NetSuiteImportRow.technology_id: None}, synchronize_session=False)


def netsuite_customers(db: Session, ids) -> dict[str, int]:
    """Retain staging evidence, sever identities and prevent rematch resurrection."""
    ids = list(ids)
    if not ids:
        return {"netsuite_import_notes": 0}
    technology_ids = db.query(CustomerTechnology.id).filter(CustomerTechnology.customer_id.in_(ids))
    note_ids = db.query(SalesNote.id).filter(SalesNote.customer_id.in_(ids))
    db.query(NetSuiteImportRow).filter(or_(
        NetSuiteImportRow.customer_id.in_(ids), NetSuiteImportRow.technology_id.in_(technology_ids),
        NetSuiteImportRow.risk_note_id.in_(note_ids), NetSuiteImportRow.observation_note_id.in_(note_ids),
    )).update(
        {NetSuiteImportRow.customer_id: None, NetSuiteImportRow.technology_id: None,
         NetSuiteImportRow.risk_note_id: None, NetSuiteImportRow.observation_note_id: None,
         NetSuiteImportRow.disposition: "customer_deleted", NetSuiteImportRow.reason: "Customer deleted"},
        synchronize_session=False)
    count = db.query(NetSuiteImportNote).filter(NetSuiteImportNote.customer_id.in_(ids)).delete(synchronize_session=False)
    return {"netsuite_import_notes": count}


def contacts(db: Session, ids) -> None:
    ids = list(ids)
    if not ids:
        return
    for table in (activity_contacts, contact_notes, contact_technologies, contact_use_cases, strategy_contact_links,
                  deal_contacts):
        _links(db, table, table.c.contact_id, ids)
    db.query(ContactBuyingRole).filter(ContactBuyingRole.contact_id.in_(ids)).delete(synchronize_session=False)


def sales_notes(db: Session, ids) -> None:
    ids = list(ids)
    if not ids:
        return
    for table in (contact_notes, sales_note_technologies, sales_note_use_cases, strategy_note_links,
                  task_evidence_notes, deal_notes):
        _links(db, table, table.c.note_id, ids)

    for column in (NetSuiteImportRow.risk_note_id, NetSuiteImportRow.observation_note_id):
        db.query(NetSuiteImportRow).filter(column.in_(ids)).update({column: None}, synchronize_session=False)
    db.query(NetSuiteImportNote).filter(NetSuiteImportNote.note_id.in_(ids)).update(
        {NetSuiteImportNote.note_id: None}, synchronize_session=False)


def tasks(db: Session, ids) -> None:
    ids = list(ids)
    if not ids:
        return
    for table in (strategy_task_links, task_evidence_notes, task_evidence_activities, deal_tasks):
        _links(db, table, table.c.task_id, ids)
    db.query(TaskNotificationWindow).filter(TaskNotificationWindow.task_id.in_(ids)).delete(
        synchronize_session=False)


def activities(db: Session, ids) -> None:
    ids = list(ids)
    if not ids:
        return
    for table in (activity_contacts, task_evidence_activities, deal_activities):
        _links(db, table, table.c.activity_id, ids)


def deals(db: Session, ids) -> None:
    """Links and stage history of deals (E6)."""
    ids = list(ids)
    if not ids:
        return
    for table in (deal_contacts, deal_tasks, deal_activities, deal_notes, deal_technologies, deal_vendor_evidence):
        _links(db, table, table.c.deal_id, ids)
    db.query(DealStageHistory).filter(DealStageHistory.deal_id.in_(ids)).delete(synchronize_session=False)


def use_cases(db: Session, ids) -> None:
    ids = list(ids)
    if not ids:
        return
    for model in (ScoreHistory, Comment, AIPrediction):
        db.query(model).filter(model.use_case_id.in_(ids)).delete(synchronize_session=False)
    for table in (contact_use_cases, sales_note_use_cases, third_party_service_use_cases):
        _links(db, table, table.c.use_case_id, ids)


def third_party_services(db: Session, ids) -> None:
    ids = list(ids)
    if not ids:
        return
    db.query(ThirdPartyServiceDocument).filter(ThirdPartyServiceDocument.service_id.in_(ids)).delete(
        synchronize_session=False)
    _links(db, third_party_service_use_cases, third_party_service_use_cases.c.service_id, ids)
