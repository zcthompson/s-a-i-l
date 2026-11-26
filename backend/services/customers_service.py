"""Service layer for customer CRUD operations.

Provides customer-level business logic including access control,
summary statistics computation, and use case aggregation.
"""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.models.account_membership import AccountMembership
from backend.models.account_strategy import (
    AccountStrategy,
    AccountStrategySnapshot,
    strategy_contact_links,
    strategy_note_links,
    strategy_task_links,
)
from backend.models.collaboration import Comment, Notification, ScoreHistory
from backend.models.customer_alias import CustomerAlias
from backend.models.customer_contact import (
    ContactBuyingRole,
    CustomerContact,
    contact_notes,
    contact_technologies,
    contact_use_cases,
)
from backend.models.customer_engagement import (
    CustomerActivity,
    CustomerTask,
    TaskNotificationWindow,
    activity_contacts,
    task_evidence_activities,
    task_evidence_notes,
)
from backend.models.customer_knowledge import CustomerKnowledge, CustomerKnowledgeItem
from backend.models.customer_technology import CustomerTechnology
from backend.models.deal import (
    Deal,
    DealStageHistory,
    deal_activities,
    deal_contacts,
    deal_notes,
    deal_tasks,
    deal_technologies,
    deal_vendor_evidence,
)
from backend.models.intelligence_import import PartnerPipeline
from backend.models.redhat_opportunity_import import RedHatOpportunityRow
from backend.models.rep_intelligence import RepIntelligenceRow
from backend.models.rvtools_import import RvToolsHost, RvToolsImport, RvToolsLicense, RvToolsVM
from backend.models.sales_access import (
    InsideSalesAssignment,
    SalesOpsAssignment,
    SalesReporting,
)
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
    Customer,
    CustomerAssessment,
    CustomerUser,
    Department,
    Projection,
    ReadinessInsight,
    UseCase,
    User,
)
from backend.schemas.use_case import CustomerResponse
from backend.services import record_cleanup
from backend.services.customer_knowledge_service import delete_customer_knowledge


def get_accessible_customers(db: Session, user: dict) -> list[Customer]:
    """Return customers the user is allowed to see.

    Admin users see all customers. Everyone else sees the central
    policy's READ scope (``sales_access.customer_scope``).

    Ordered newest-first (created_at desc, id desc) so a just-created
    customer appears at the top of the list rather than at the end of a
    multi-page list (latent unsorted-rowid bug: a fresh customer was
    invisible on page 1 of a 900+ row list).
    """
    if user.get("is_admin") == 1:
        return list_all_customers(db)

    user_id = user.get("user_id") or user.get("id")
    if not user_id:
        return []

    # Read scope = the central policy's complete READ scope (Part 13 DV1):
    # junction + inside-sales + sales-ops + manager team + memberships +
    # reads-all. Computed ONCE for the list (fixed-query discipline).
    from backend.services import sales_access
    # PS administrators have no sales READ capability, even if stale
    # customer junctions remain. Other roles use the established batched scope.
    if sales_access.effective_role(user) == "ps_admin":
        return []
    allowed_ids = sales_access.customer_scope(user, db)
    if not allowed_ids:
        return []

    return (
        db.query(Customer)
        .filter(Customer.id.in_(allowed_ids))
        .order_by(Customer.created_at.desc(), Customer.id.desc())
        .all()
    )


def get_customer_by_name(db: Session, name: str) -> Customer | None:
    """Look up a customer by name, or return None."""
    return db.query(Customer).filter(Customer.name == name).first()


def prospect_name_conflict(db: Session, name: str) -> str | None:
    """Existing account name or alias that a new prospect name would duplicate.

    Uses the app's alias matching normalization (case and whitespace
    insensitive), so "Acme  corp" collides with "ACME Corp" or an "Acme Corp"
    alias. Returns the colliding name, or None.
    """
    from backend.services.customer_alias_service import normalize_alias

    wanted = normalize_alias(name)
    for (existing,) in db.query(Customer.name):
        if normalize_alias(existing) == wanted:
            return existing
    alias = (db.query(CustomerAlias.alias, Customer.name)
             .join(Customer, Customer.id == CustomerAlias.customer_id)
             .filter(CustomerAlias.alias_norm == wanted).first())
    return f"{alias[1]} (alias {alias[0]})" if alias else None


def list_all_customers(db: Session) -> list[Customer]:
    """Return all customers (unfiltered admin listing), newest-first.

    Ordered by ``created_at`` DESC (then ``id`` DESC as a tie-break) so a
    just-created customer appears at the top of the list rather than at the
    end of a multi-page list (latent unsorted-rowid bug: a fresh customer was
    invisible on page 1 of a 900+ row list).
    """
    return (
        db.query(Customer)
        .order_by(Customer.created_at.desc(), Customer.id.desc())
        .all()
    )


def check_customer_access(db: Session, customer: Customer, user: dict) -> bool:
    """Check if the customer is in the user's central READ scope.
    
    Admin users always have access.
    """
    if user.get("is_admin") == 1:
        return True
    
    user_id = user.get("user_id") or user.get("id")
    if not user_id:
        return False

    # The central policy's complete READ scope (Part 13 DV1; see
    # get_accessible_customers).
    from backend.services import sales_access
    return customer.id in sales_access.customer_scope(user, db)


def _sales_context_fields(
    owners: list,
    manager,
    inside_users: list,
    ops_users: list,
) -> tuple:
    """Derive (primary_rep, rep_sales_role, manager_name, inside_sales,
    sales_ops) from already-loaded sales-structure records.

    Single source of the owner-selection rule so the per-customer path
    (db queries) and the batched list path (pre-fetched context) produce
    byte-identical values: exactly one rep-role owner wins; otherwise the
    first owner (in CustomerUser.id order); display_name or username.
    """
    primary_rep = None
    rep_sales_role = None
    manager_name = None
    rep_owners = [owner for owner in owners if owner.sales_role == "rep"]
    owner = rep_owners[0] if len(rep_owners) == 1 else (owners[0] if owners else None)
    if owner is not None:
        primary_rep = owner.display_name or owner.username
        rep_sales_role = owner.sales_role
        if manager is not None:
            manager_name = manager.display_name or manager.username
    inside_sales = [
        {"name": user.display_name or user.username}
        for user in inside_users
    ]
    sales_ops = [
        {"name": user.display_name or user.username}
        for user in ops_users
    ]
    return primary_rep, rep_sales_role, manager_name, inside_sales, sales_ops


def build_customer_response(
    customer: Customer,
    use_cases: list[UseCase],
    db: Session | None = None,
    sales_context: dict | None = None,
    aliases_context: dict | None = None,
) -> CustomerResponse:
    """Build a complete CustomerResponse with computed fields.
    
    Prefer department_id (FK) over legacy department string for
    department name resolution. Falls back to legacy string when
    department_id is not set.

    ``sales_context`` (H2): a pre-fetched batched context keyed by customer
    id — ``{"owners": [...], "manager": ...|None, "inside": [...], "ops":
    [...]}`` per customer — used instead of the per-customer ``db`` queries
    so the LIST route stays a fixed number of batch queries (no N+1). When
    omitted, the historical per-customer ``db`` path runs unchanged.

    ``aliases_context`` (Part 14, A4): the same batched pattern for customer
    aliases — ``{customer_id: [raw alias, ...]}`` — so the LIST route stays
    a fixed number of batch queries. When omitted and a session is present,
    a single per-customer read runs (the detail path); with neither, the
    payload carries an empty list.
    """
    dept_names: list[str] = [d.name for d in customer.departments if d.name]
    for uc in use_cases:
        # Prefer department_id FK, fall back to legacy department string
        dept_id = uc.department_id  # type: ignore[union-attr]
        if dept_id and uc.department_obj:  # type: ignore[union-attr]
            dept_name = uc.department_obj.name or ""  # type: ignore[union-attr]
        else:
            dept_name = str(uc.department or "")  # type: ignore[union-attr]
        if dept_name and dept_name not in dept_names:
            dept_names.append(dept_name)
    total_impact = sum(
        (uc.estimated_savings or 0) + (uc.estimated_revenue or 0)
        for uc in use_cases
    )

    primary_rep = None
    rep_sales_role = None
    manager_name = None
    inside_sales: list[dict] = []
    sales_ops: list[dict] = []
    if sales_context is not None:
        ctx = sales_context.get(customer.id, {})
        (primary_rep, rep_sales_role, manager_name,
         inside_sales, sales_ops) = _sales_context_fields(
            ctx.get("owners", []), ctx.get("manager"),
            ctx.get("inside", []), ctx.get("ops", []),
        )
    elif db is not None:
        owners = (
            db.query(User)
            .join(CustomerUser, CustomerUser.user_id == User.id)
            .filter(
                CustomerUser.customer_id == customer.id,
                CustomerUser.role == "owner",
            )
            .order_by(CustomerUser.id)
            .all()
        )
        manager = None
        rep_owners = [owner for owner in owners if owner.sales_role == "rep"]
        owner = rep_owners[0] if len(rep_owners) == 1 else (owners[0] if owners else None)
        if owner is not None:
            manager = (
                db.query(User)
                .join(SalesReporting, SalesReporting.manager_user_id == User.id)
                .filter(SalesReporting.rep_user_id == owner.id)
                .first()
            )
        inside_users = (
            db.query(User)
            .join(
                InsideSalesAssignment,
                InsideSalesAssignment.inside_sales_user_id == User.id,
            )
            .filter(InsideSalesAssignment.customer_id == customer.id)
            .order_by(InsideSalesAssignment.id)
            .all()
        )
        ops_users = (
            db.query(User)
            .join(SalesOpsAssignment, SalesOpsAssignment.user_id == User.id)
            .filter(SalesOpsAssignment.customer_id == customer.id)
            .order_by(SalesOpsAssignment.id)
            .all()
        )
        (primary_rep, rep_sales_role, manager_name,
         inside_sales, sales_ops) = _sales_context_fields(
            owners, manager, inside_users, ops_users,
        )

    if aliases_context is not None:
        aliases = list(aliases_context.get(customer.id, []))
    elif db is not None:
        aliases = [
            alias for (alias,) in db.query(CustomerAlias.alias)
            .filter_by(customer_id=customer.id)
            .order_by(CustomerAlias.alias)
            .all()
        ]
    else:
        aliases = []

    return CustomerResponse(
        id=int(customer.id),
        name=customer.name,
        description=customer.description,
        vertical=customer.vertical,
        branch=customer.branch,
        sales_area=customer.sales_area,
        primary_subsidiary=customer.primary_subsidiary,
        primary_rep=primary_rep,
        rep_sales_role=rep_sales_role,
        manager_name=manager_name,
        inside_sales=inside_sales,
        sales_ops=sales_ops,
        created_at=customer.created_at.isoformat(),
        updated_at=customer.updated_at.isoformat(),
        use_case_count=len(use_cases),
        departments=dept_names,
        total_impact=float(total_impact),
        aliases=aliases,
    )


def get_customer_use_cases(db: Session, customer: Customer) -> list[UseCase]:
    """Return all use cases for a customer."""
    return db.query(UseCase).filter(UseCase.customer_id == customer.id).all()


def assert_customer_owner_or_admin(db: Session, customer: Customer, user: dict) -> None:
    """Require global admin or the authoritative customer owner junction role."""
    del db  # The authenticated user's junction_roles are populated by auth.
    if user.get("is_admin") != 1 and user.get("junction_roles", {}).get(customer.id) != "owner":
        raise ValueError("Customer owner or admin required")


def delete_customer_with_use_cases(db: Session, customer: Customer) -> dict[str, int]:
    """Stage a complete account deletion and return per-table deleted counts.

    The caller commits or rolls back the transaction. Explicit child-first
    deletes work with SQLite foreign keys both off and on. Customer's ORM
    cascades cover departments, users, projections, readiness and assessments.
    Audits and multi-account import batches retain their original evidence;
    rep intelligence rows retain history with both account/inventory links NULL.
    """
    db.flush()
    use_case_ids = [row[0] for row in db.query(UseCase.id).filter(UseCase.customer_id == customer.id).all()]
    technology_ids = [row[0] for row in db.query(CustomerTechnology.id).filter_by(customer_id=customer.id)]
    note_ids = [row[0] for row in db.query(SalesNote.id).filter_by(customer_id=customer.id)]
    service_ids = [row[0] for row in db.query(ThirdPartyService.id).filter_by(customer_id=customer.id)]
    import_ids = [row[0] for row in db.query(RvToolsImport.id).filter_by(customer_id=customer.id)]
    deleted = {}

    def delete_rows(model, condition):
        deleted[model.__tablename__] = db.query(model).filter(condition).delete(synchronize_session=False)

    def delete_links(table, condition):
        deleted[table.name] = db.execute(table.delete().where(condition)).rowcount

    # A write starts the outer SQLite transaction before helpers use savepoints.
    delete_rows(ScoreHistory, ScoreHistory.use_case_id.in_(use_case_ids))
    delete_rows(Comment, Comment.use_case_id.in_(use_case_ids))
    delete_rows(AIPrediction, or_(
        AIPrediction.use_case_id.in_(use_case_ids), AIPrediction.customer_id == customer.id,
    ))

    documents = db.query(CustomerKnowledge).filter_by(customer_id=customer.id).all()
    item_scope = or_(CustomerKnowledgeItem.customer_id == customer.id,
                     CustomerKnowledgeItem.source_knowledge_id.in_([doc.id for doc in documents]))
    deleted["customer_knowledge_items"] = db.query(CustomerKnowledgeItem).filter(item_scope).count()
    # The helper commits internally; confine those commits to savepoints on
    # the caller's connection (the intelligence-import deletion pattern).
    with Session(bind=db.connection(), join_transaction_mode="create_savepoint") as knowledge_db:
        for document in documents:
            delete_customer_knowledge(knowledge_db, document.id, customer.id)
    deleted["customer_knowledge"] = len(documents)
    # Also clean denormalized customer links left without a source document.
    db.query(CustomerKnowledgeItem).filter_by(customer_id=customer.id).delete(synchronize_session=False)

    delete_links(sales_note_use_cases, or_(sales_note_use_cases.c.note_id.in_(note_ids),
                                         sales_note_use_cases.c.use_case_id.in_(use_case_ids)))
    delete_links(sales_note_technologies, or_(sales_note_technologies.c.note_id.in_(note_ids),
                                            sales_note_technologies.c.technology_id.in_(technology_ids)))
    contact_ids = [r[0] for r in db.query(CustomerContact.id).filter_by(customer_id=customer.id).all()]
    delete_links(contact_notes, or_(contact_notes.c.contact_id.in_(contact_ids),
                                    contact_notes.c.note_id.in_(note_ids)))
    delete_links(contact_use_cases, or_(contact_use_cases.c.contact_id.in_(contact_ids),
                                        contact_use_cases.c.use_case_id.in_(use_case_ids)))
    delete_links(contact_technologies, or_(contact_technologies.c.contact_id.in_(contact_ids),
                                           contact_technologies.c.technology_id.in_(technology_ids)))
    activity_ids = [r[0] for r in db.query(CustomerActivity.id).filter_by(customer_id=customer.id)]
    task_ids = [r[0] for r in db.query(CustomerTask.id).filter_by(customer_id=customer.id)]
    strategy_ids = [r[0] for r in db.query(AccountStrategy.id).filter_by(customer_id=customer.id)]
    for table in (strategy_task_links, strategy_contact_links, strategy_note_links):
        delete_links(table, table.c.strategy_id.in_(strategy_ids))
    delete_rows(AccountStrategySnapshot, AccountStrategySnapshot.customer_id == customer.id)
    # E6 deals: links and stage history first (counted for the audit), then the deals.
    deal_ids = [r[0] for r in db.query(Deal.id).filter_by(customer_id=customer.id)]
    for table in (deal_contacts, deal_tasks, deal_activities, deal_notes, deal_technologies, deal_vendor_evidence):
        delete_links(table, table.c.deal_id.in_(deal_ids))
    delete_rows(DealStageHistory, DealStageHistory.deal_id.in_(deal_ids))
    delete_rows(Deal, Deal.customer_id == customer.id)
    delete_rows(AccountStrategy, AccountStrategy.customer_id == customer.id)
    delete_links(activity_contacts, or_(activity_contacts.c.activity_id.in_(activity_ids),
                                        activity_contacts.c.contact_id.in_(contact_ids)))
    delete_links(task_evidence_notes, or_(task_evidence_notes.c.task_id.in_(task_ids),
                                          task_evidence_notes.c.note_id.in_(note_ids)))
    delete_links(task_evidence_activities, or_(task_evidence_activities.c.task_id.in_(task_ids),
                                               task_evidence_activities.c.activity_id.in_(activity_ids)))
    delete_rows(CustomerActivity, CustomerActivity.customer_id == customer.id)
    delete_rows(TaskNotificationWindow, TaskNotificationWindow.task_id.in_(task_ids))
    delete_rows(CustomerTask, CustomerTask.customer_id == customer.id)
    # Part 14 (A1): alias tags are account-owned metadata — the delete covers
    # them explicitly (works with SQLite foreign keys both off and on).
    delete_rows(CustomerAlias, CustomerAlias.customer_id == customer.id)
    delete_rows(ContactBuyingRole, ContactBuyingRole.contact_id.in_(contact_ids))
    delete_rows(CustomerContact, CustomerContact.customer_id == customer.id)
    deleted.update(record_cleanup.netsuite_customers(db, [customer.id]))
    record_cleanup.sales_notes(db, note_ids)
    delete_rows(SalesNote, SalesNote.customer_id == customer.id)
    delete_rows(TechnologyDependency, or_(TechnologyDependency.customer_id == customer.id,
                                         TechnologyDependency.source_id.in_(technology_ids),
                                         TechnologyDependency.target_id.in_(technology_ids)))
    db.query(RepIntelligenceRow).filter(or_(
        RepIntelligenceRow.customer_id == customer.id,
        RepIntelligenceRow.technology_id.in_(technology_ids),
    )).update({RepIntelligenceRow.customer_id: None, RepIntelligenceRow.technology_id: None},
              synchronize_session=False)
    delete_rows(CustomerTechnology, CustomerTechnology.customer_id == customer.id)

    for model in (RvToolsHost, RvToolsVM, RvToolsLicense):
        delete_rows(model, model.import_id.in_(import_ids))
    delete_rows(RvToolsImport, RvToolsImport.customer_id == customer.id)
    delete_rows(SalesEvaluation, SalesEvaluation.customer_id == customer.id)

    # Customer has no services cascade. The document relationship's
    # passive_deletes=True also skips unloaded children with FK enforcement
    # off, so services, documents and links need explicit deletion here.
    delete_links(third_party_service_use_cases, or_(
        third_party_service_use_cases.c.service_id.in_(service_ids),
        third_party_service_use_cases.c.use_case_id.in_(use_case_ids),
    ))
    delete_rows(ThirdPartyServiceDocument, or_(
        ThirdPartyServiceDocument.customer_id == customer.id,
        ThirdPartyServiceDocument.service_id.in_(service_ids),
    ))
    delete_rows(ThirdPartyService, ThirdPartyService.customer_id == customer.id)
    for model in (AccountMembership, InsideSalesAssignment, Notification, SalesOpsAssignment,
                  PartnerPipeline, RedHatOpportunityRow):
        delete_rows(model, model.customer_id == customer.id)
    delete_rows(UseCase, UseCase.customer_id == customer.id)

    # Count the verified ORM cascades before deleting their parent. Counts
    # include zeroes so audit evidence records every covered table.
    for model in (Department, CustomerUser, Projection, ReadinessInsight, CustomerAssessment):
        deleted[model.__tablename__] = db.query(model).filter_by(customer_id=customer.id).count()
    db.delete(customer)
    db.flush()
    deleted["customers"] = 1
    return deleted
