"""Central sales-access policy resolver (shift to global customer management,
phase 2).

The directive (§4) requires ONE server-side policy layer that answers both
*permitted customer scope* and *permitted actions* — not a divergent check in
every route. This module is that layer. It is:

  * **Pure + additive.** It is a set of functions over the standard user dict
    (as built by ``auth.get_user_from_request``: username, is_admin, role,
    user_id, customer_ids, junction_roles) plus a DB session. Nothing calls
    it yet (phase 3 converts the routes), so existing authorization behavior
    is unchanged until callers adopt it.
  * **Empty scope = no data, never all**. Only a
    system admin (``is_admin == 1``) gets the "all customers" expansion; every
    other role gets an explicit union of granted customer ids, which may be
    empty.
  * **Sales-manager never implies system-admin** (rule 1). ``sales_role`` is
    orthogonal to ``is_admin``.
  * **Stable IDs only** (rule 2) — relationships derive from user/customer
    primary keys, never branch strings or display-name similarity.
  * **Auditor never confers write** (rule 7).

Role normalization
------------------
``effective_role(user)`` maps the legacy ``User.role`` + the new
``User.sales_role`` + ``is_admin`` onto one of:
    'system_admin' | 'ps_admin' | 'sales_manager' | 'rep' | 'inside_sales' |
    'sales_ops' | 'auditor' | 'user'

Legacy mapping (backward-compatible): an existing junction ``owner``/``member``
counts as a rep-scope grant; an existing ``auditor`` junction counts as an
auditor grant; ``is_admin=1`` stays system admin; ``role='ps_admin'`` stays
confined to the third-party-services surface.

``sales_ops`` is a per-account contributor: read-only on accounts it is
assigned to (sales_ops_assignments), plus write sales notes and contribute
customer knowledge. No account editing, team management or transfer.
"""

from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.models.account_membership import AccountMembership
from backend.models.sales_access import (
    InsideSalesAssignment,
    SalesOpsAssignment,
    SalesReporting,
)
from backend.models.use_case import Customer, CustomerUser

# Capability vocabulary (the action axes in the capability matrix).
CAP_READ = "read"
CAP_EXPORT = "export"
CAP_EDIT = "edit"
CAP_NOTES = "notes"
CAP_KNOWLEDGE = "knowledge"
CAP_MANAGE_TEAM = "manage_team"
CAP_TRANSFER_OWNERSHIP = "transfer_ownership"
CAP_SYSTEM_ADMIN = "system_admin"
# RBAC model axes (account memberships).
CAP_METADATA = "metadata"
CAP_MANAGE_COOWNERS = "manage_owners"
CAP_INSIDE_GRANTS = "inside_grants"
CAP_CREATE_SECTION = "create_section"
CAP_OWN_ITEMS = "own_items"
CAP_INTEL_UPLOADS = "intel_uploads"

CAP_CONTACTS = "contacts"
CAP_ACTIVITIES = "activities"
CAP_TASKS = "tasks"
CAP_STRATEGY = "strategy"
# Reserved for the CRM expansion: the
# section vocabulary already reserves these names in
# models/account_membership.py; these capabilities activate the gates with
# the H4 matrix shape (owner writes; inside-sales gated on a contribute
# grant for the matching section; legacy member parity; auditor/ps_admin/
# sales_admin denied).
CAP_OPPORTUNITIES = "opportunities"
CAP_FORECASTS = "forecasts"
CAP_COMPETITORS = "competitors"

ALL_CAPS = (CAP_READ, CAP_EXPORT, CAP_EDIT, CAP_NOTES, CAP_KNOWLEDGE,
            CAP_MANAGE_TEAM, CAP_TRANSFER_OWNERSHIP, CAP_SYSTEM_ADMIN,
            CAP_METADATA, CAP_MANAGE_COOWNERS, CAP_INSIDE_GRANTS,
            CAP_CREATE_SECTION, CAP_OWN_ITEMS, CAP_INTEL_UPLOADS, CAP_CONTACTS, CAP_ACTIVITIES, CAP_TASKS, CAP_STRATEGY,
            CAP_OPPORTUNITIES, CAP_FORECASTS, CAP_COMPETITORS)

# Membership role -> canonical permission set. ``sales_ops`` is an ALIAS of
# ``primary_owner`` (directive A1): one shared mapping, not a copied list.
_ROLE_ALIASES = {"sales_ops": "primary_owner"}
_MEMBERSHIP_LEVEL = {"primary_owner": "owner", "co_owner": "owner", "inside_sales": "member"}

# Roles each membership role may grant on its own account (directive matrix).
_GRANTABLE_BY_HELD = {
    "primary_owner": {"primary_owner", "co_owner", "inside_sales"},
    "co_owner": {"inside_sales"},
}
# What a sales_admin may grant; Global Admin and Auditor are system-admin only.
_SALES_ADMIN_GRANTS = {"primary_owner", "co_owner", "sales_ops", "inside_sales"}


def effective_role(user: dict) -> str:
    """Normalize legacy + new role fields to a single effective role string.

    Precedence (highest first):
      1. is_admin == 1              -> system_admin  (exclusive, rule 1)
      2. role == 'ps_admin'         -> ps_admin      (3rd-party surface only)
      3. sales_role                 -> that value (rep/inside_sales/
                                        sales_manager/sales_ops/auditor)
      4. role == 'auditor' (legacy) -> auditor
      5. else                        -> 'user'
    """
    if user.get("is_admin") == 1:
        return "system_admin"
    if user.get("role") == "ps_admin":
        return "ps_admin"
    sr = (user.get("sales_role") or "").strip()
    if sr in ("rep", "inside_sales", "sales_manager", "sales_ops", "auditor", "sales_admin"):
        return sr
    if (user.get("role") or "").strip() == "auditor":
        return "auditor"
    return "user"


def _transitive_report_ids(db: Session | None, user_id: int) -> set:
    """Direct + transitive report user ids of ``user_id`` (cycle-safe).

    Returns a set of user ids (NOT including the manager's own id) reachable
    by following sales_reporting.manager_user_id down to rep_user_id. A cycle
    is cut off by tracking visited ids.
    """
    if user_id is None or db is None:
        return set()
    seen = set()
    frontier = [user_id]
    while frontier:
        nid = frontier.pop()
        if nid in seen:
            continue
        seen.add(nid)
        rows = (
            db.query(SalesReporting.rep_user_id)
            .filter(SalesReporting.manager_user_id == nid)
            .all()
        )
        frontier.extend(r[0] for r in rows if r[0] not in seen)
    seen.discard(user_id)
    return seen


def _owned_customer_ids_for_users(db: Session | None, user_ids) -> set:
    """Customer ids owned (owner role) by any user in ``user_ids``."""
    user_ids = set(user_ids)
    if not user_ids or db is None:
        return set()
    rows = (
        db.query(CustomerUser.customer_id)
        .filter(
            CustomerUser.user_id.in_(user_ids),
            CustomerUser.role == "owner",
        )
        .all()
    )
    return {r[0] for r in rows}


def _inside_sales_customer_ids(db: Session | None, user_id: int) -> set:
    if db is None:
        return set()
    rows = (
        db.query(InsideSalesAssignment.customer_id)
        .filter(InsideSalesAssignment.inside_sales_user_id == user_id)
        .all()
    )
    return {r[0] for r in rows}


def _sales_ops_customer_ids(db: Session | None, user_id: int) -> set:
    if db is None:
        return set()
    rows = (
        db.query(SalesOpsAssignment.customer_id)
        .filter(SalesOpsAssignment.user_id == user_id)
        .all()
    )
    return {r[0] for r in rows}


def load_membership_context(user: dict, db: Session | None) -> dict:
    """Attach ``membership_roles`` / ``section_grants`` to the user dict.

    One query; expired rows are ignored. Without a user id or session the
    context is empty (fail-closed: no membership grants).
    """
    roles: dict = {}
    grants: dict = {}
    uid = user.get("user_id") or user.get("id")
    if uid is not None and db is not None:
        now = datetime.utcnow()
        rows = (
            db.query(AccountMembership)
            .filter(
                AccountMembership.user_id == uid,
                or_(AccountMembership.expires_at.is_(None), AccountMembership.expires_at > now),
            )
            .all()
        )
        for m in rows:
            roles.setdefault(m.customer_id, []).append(m.role)
            if m.role == "inside_sales":
                grants[m.customer_id] = dict(m.section_grants or {})
    user["membership_roles"] = roles
    user["section_grants"] = grants
    return user


def _membership_roles(user: dict, db: Session | None) -> dict:
    if "membership_roles" not in user:
        load_membership_context(user, db)
    return user.get("membership_roles") or {}


def auditor_read_only(user: dict) -> bool:
    """True for an in-role auditor (sales_role or legacy role), never admin."""
    return effective_role(user) == "auditor"


def _reads_all(user: dict) -> bool:
    """Roles whose READ scope is the whole application."""
    return effective_role(user) in ("auditor", "sales_admin")


def _all_customer_ids(db: Session | None) -> set:
    if db is None:
        return set()
    return {r[0] for r in db.query(Customer.id).all()}


def customer_scope(user: dict, db: Session | None) -> set:
    """Return the set of customer ids ``user`` is authorized to see.

    Rules:
      * system admin (is_admin=1) -> a special sentinel is NOT returned; the
        caller treats is_admin as unrestricted (see ``is_unrestricted``).
        This function still returns the explicit union for symmetry, but the
        authoritative "all" decision is made by ``is_unrestricted``.
      * sales_manager -> customers owned by their (transitive) reports, PLUS
        any explicit junction grants they also hold.
      * rep / inside_sales / user -> the explicit union of: junction
        owner/member rows + inside-sales assignments (counted only for
        inside_sales holders, matching ``_access``) + account memberships.
      * auditor / sales_admin -> ALL customers (read scope; auditors never
        write — see ``can``).

    An empty result means NO customer data — never all (rule 11).
    """
    scope = set()
    uid = user.get("user_id") or user.get("id")

    # junction grants (owner / member / auditor) — the caller's explicit
    # customer access. NOTE: scope is READ visibility, so auditor junction
    # rows count toward scope; the WRITE restrictions (auditor = read-only)
    # are enforced in can(), not in the scope.
    scope |= set(user.get("customer_ids") or [])

    # inside-sales assignments (customer-specific; role-gated to match
    # _access — an assignment row held by a non-inside_sales user does not
    # widen scope
    if uid is not None and effective_role(user) == "inside_sales":
        scope |= _inside_sales_customer_ids(db, uid)

    # sales-ops assignments (customer-specific)
    if uid is not None and effective_role(user) == "sales_ops":
        scope |= _sales_ops_customer_ids(db, uid)

    # manager scope: customers owned by (transitive) reports
    if effective_role(user) == "sales_manager" and uid is not None:
        reports = _transitive_report_ids(db, uid)
        scope |= _owned_customer_ids_for_users(db, reports)

    # account memberships (primary_owner / co_owner / sales_ops / inside_sales)
    scope |= set(_membership_roles(user, db))

    # directive: auditor reads the entire application; sales_admin sees all
    # accounts (read) to manage their memberships.
    if _reads_all(user):
        scope |= _all_customer_ids(db)

    return scope


def is_unrestricted(user: dict) -> bool:
    """True only for a system admin. 'Global' never means bypassing
    permissions for any other role."""
    return user.get("is_admin") == 1


# Per-customer access LEVELS (capability is derived from the caller's highest
# level on that customer). Ordering by privilege: none < auditor <
# contributor < member < owner. A junction role AND a sales role both contribute; the MAX wins.
#   owner   = account owner (rep) or sales_manager on a team customer
#   member  = supporting access (member junction, or inside-sales assignment)
#   contributor = sales_ops on an assigned account (read + notes + knowledge)
#   auditor = read-only (auditor junction)
_LEVEL_ORDER = {"none": 0, "auditor": 1, "contributor": 2, "member": 3, "owner": 4}


def _access(user: dict, db: Session | None, customer_id: int):
    """(highest level, set of grant kinds) the caller holds on ``customer_id``.

    Kinds: ``junction_owner`` / ``manager`` (legacy full owner),
    ``primary_owner`` / ``co_owner`` / ``sales_ops`` / ``inside_sales``
    (memberships), ``legacy_member`` (junction member or an inside-sales
    assignment with no membership row — ungated, legacy parity).
    """
    lvl = "none"
    kinds: set = set()

    def bump(level: str, kind: str) -> None:
        nonlocal lvl
        kinds.add(kind)
        if _LEVEL_ORDER[level] > _LEVEL_ORDER[lvl]:
            lvl = level

    jr = (user.get("junction_roles") or {}).get(customer_id)
    if jr == "owner":
        bump("owner", "junction_owner")
    elif jr == "member":
        bump("member", "legacy_member")
    elif jr == "auditor":
        bump("auditor", "auditor")

    held = _membership_roles(user, db).get(customer_id) or []
    for r in held:
        canon = _ROLE_ALIASES.get(r, r)
        level = _MEMBERSHIP_LEVEL.get(canon)
        if level is not None:
            bump(level, r)

    role = effective_role(user)
    uid = user.get("user_id") or user.get("id")
    if role == "inside_sales" and uid is not None and customer_id in _inside_sales_customer_ids(db, uid):
        # With a membership row the section gating applies; without one the
        # legacy assignment keeps its ungated member access.
        if "inside_sales" not in held:
            bump("member", "legacy_member")
    if role == "sales_ops" and uid is not None and customer_id in _sales_ops_customer_ids(db, uid):
        bump("contributor", "legacy_contributor")
    if role == "sales_manager" and customer_id in customer_scope(user, db):
        bump("owner", "manager")
    return lvl, kinds


def _customer_level(user: dict, db: Session | None, customer_id: int) -> str:
    """The caller's highest access level on ``customer_id``.

    Legacy-compat: a ``CustomerUser`` junction role confers a level even when
    the user has no ``sales_role`` (owner→owner, member→member, auditor→
    auditor), so existing owners/members are NOT locked out. New sales roles
    add: inside-sales assignments → member; a sales_manager in scope for the
    customer → owner (full team administration). Account memberships add:
    primary_owner / sales_ops (alias) / co_owner → owner, inside_sales →
    member.
    """
    return _access(user, db, customer_id)[0]


def _section_level(user: dict, customer_id: int, section: str | None) -> str | None:
    if section is None:
        return None
    grants = (user.get("section_grants") or {}).get(customer_id) or {}
    return grants.get(section, "read")


def may_grant_role(actor: dict, target_role: str,
                   customer_id: int | None = None,
                   db: Session | None = None) -> bool:
    """Pure grant-policy check: may ``actor`` hand out ``target_role``?

    * system_admin: anything.
    * sales_admin: primary_owner / co_owner / sales_ops / inside_sales only
      (never Global Admin or Auditor).
    * account holders (need ``customer_id``): primary_owner may grant
      primary_owner (the transfer path), co_owner and inside_sales; sales_ops
      is an alias of primary_owner for co-owner management but may not mint
      a primary_owner/sales_ops; co_owner may only grant inside_sales access.
    * No one grants a role they do not hold; everything else is denied.
    """
    role = effective_role(actor)
    if role == "system_admin":
        return True
    if role == "sales_admin":
        return target_role in _SALES_ADMIN_GRANTS
    if role in ("ps_admin", "auditor") or customer_id is None:
        return False
    _, kinds = _access(actor, db, customer_id)
    allowed: set = set()
    for k in kinds:
        if k in ("junction_owner", "manager"):
            k = "primary_owner"
        if k == "sales_ops":
            allowed |= {"co_owner", "inside_sales"}
        else:
            allowed |= _GRANTABLE_BY_HELD.get(k, set())
    return target_role in allowed


def can(user: dict, db: Session | None, capability: str, customer_id: int | None = None,
        section: str | None = None, is_own_item: bool = False) -> bool:
    """Answer a single permitted-action question.

    ``customer_id`` scopes the check to one customer. When it is None the
    check is capability-only and only the organization-wide axes resolve
    (system_admin / ps_admin); customer-scoped capabilities require a target
    customer (fail-closed). ``section`` / ``is_own_item`` refine contributor
    (inside_sales) checks; ``is_own_item`` never grants write on its own.
    """
    role = effective_role(user)

    if capability == CAP_SYSTEM_ADMIN:
        # Exclusive system-admin authority (rule 1): is_admin only.
        return user.get("is_admin") == 1

    if role == "system_admin":
        # System admin has every capability across the organization.
        return True

    # ps_admin is confined to the third-party-services surface (rule 37).
    # This resolver governs SALES/account capabilities; ps_admin has none of
    # them here (its PS surface is checked by customer_access.ps_*). Return
    # False for all sales capabilities so ps_admin is NOT elevated.
    if role == "ps_admin":
        return False

    if customer_id is None:
        # A customer-scoped capability cannot be asserted without a target.
        return False

    if role == "auditor":
        # Directive: auditor reads/exports (audit reports) everywhere, writes
        # nothing. No own-item or section grant can raise this.
        return capability in (CAP_READ, CAP_EXPORT)

    if role == "sales_admin":
        # Manages users/memberships via the dedicated admin endpoints, not
        # account content; reads all accounts but cannot bulk export.
        return capability == CAP_READ

    # Scope gate: the caller must be authorized to see this customer at all.
    if not is_unrestricted(user) and customer_id not in customer_scope(user, db):
        return False

    lvl, kinds = _access(user, db, customer_id)

    if lvl == "owner":
        full = bool(kinds & {"junction_owner", "manager", "primary_owner"})
        if capability == CAP_TRANSFER_OWNERSHIP:
            return full
        if capability == CAP_MANAGE_COOWNERS:
            return full or "sales_ops" in kinds
        return capability in (
            CAP_READ, CAP_EXPORT, CAP_EDIT, CAP_NOTES, CAP_KNOWLEDGE, CAP_MANAGE_TEAM,
            CAP_METADATA, CAP_INSIDE_GRANTS, CAP_CREATE_SECTION, CAP_OWN_ITEMS, CAP_INTEL_UPLOADS, CAP_CONTACTS, CAP_ACTIVITIES, CAP_TASKS, CAP_STRATEGY,
            CAP_OPPORTUNITIES, CAP_FORECASTS, CAP_COMPETITORS,
        )

    gated = "inside_sales" in kinds and "legacy_member" not in kinds
    if gated and lvl == "member":
        if capability == CAP_READ:
            return True
        if capability in (CAP_NOTES, CAP_KNOWLEDGE, CAP_CREATE_SECTION, CAP_OWN_ITEMS,
                          CAP_INTEL_UPLOADS, CAP_CONTACTS, CAP_ACTIVITIES, CAP_TASKS, CAP_STRATEGY,
                          CAP_OPPORTUNITIES, CAP_FORECASTS, CAP_COMPETITORS):
            return _section_level(user, customer_id,
                                  "intel_uploads" if capability == CAP_INTEL_UPLOADS
                                  else section) == "contribute"
        return False

    if capability in (CAP_READ, CAP_EXPORT):
        # read-only and up may read/export their in-scope customers.
        return lvl in ("auditor", "contributor", "member", "owner")
    if capability in (CAP_NOTES, CAP_KNOWLEDGE):
        # contributor (sales_ops) may write notes/knowledge but not edit.
        return lvl in ("contributor", "member", "owner")
    if capability in (CAP_CONTACTS, CAP_ACTIVITIES, CAP_TASKS, CAP_STRATEGY,
                      CAP_OPPORTUNITIES, CAP_FORECASTS, CAP_COMPETITORS):
        return lvl in ("member", "owner")
    if capability == CAP_EDIT:
        # member (supporting) and owner may edit account content; auditor may not.
        return lvl in ("member", "owner")
    if capability == CAP_INTEL_UPLOADS:
        return (lvl in ("contributor", "member")
                and _section_level(user, customer_id, "intel_uploads") == "contribute")
    if capability == CAP_MANAGE_TEAM:
        return lvl == "owner"
    if capability in (CAP_CREATE_SECTION, CAP_OWN_ITEMS):
        return lvl == "member"

    return False


def summary(user: dict, db: Session | None) -> dict:
    """A compact, UI-consumable capability/scope summary.

    Exposes scope as a label only (never an unbounded list for non-admins)
    and the boolean capability flags. The API enforcement remains
    authoritative (customer_scope/can); this is for rendering.
    """
    role = effective_role(user)
    unrestricted = is_unrestricted(user)
    if unrestricted:
        scope_label = "All authorized customers"
    else:
        n = len(customer_scope(user, db))
        scope_label = (
            f"My customers ({n})" if role in ("rep",) else f"Authorized customers ({n})"
        )
    return {
        "role": role,
        "unrestricted": unrestricted,
        "scope_label": scope_label,
        "capabilities": {c: can(user, db, c) for c in ALL_CAPS},
    }


def account_read_predicate(user, customer_id):
    """SQL form of CAP_READ for bounded-query portfolio reads.

    Uses the same grants and role precedence as can(); task assignment is
    deliberately absent. ``user`` may be an ORM alias. No active-user check
    is folded in: callers use that separate history/notification condition.
    """
    from sqlalchemy import and_, exists, select

    # UNION (rather than UNION ALL) terminates even for malformed hierarchy cycles.
    reporting = select(SalesReporting.manager_user_id.label("manager"),
                       SalesReporting.rep_user_id.label("report")).cte(recursive=True)
    reporting = reporting.union(select(reporting.c.manager, SalesReporting.rep_user_id).join(
        SalesReporting, SalesReporting.manager_user_id == reporting.c.report))
    junction = exists(select(CustomerUser.id).where(
        CustomerUser.user_id == user.id, CustomerUser.customer_id == customer_id,
        CustomerUser.role.in_(("owner", "member", "auditor"))))
    membership = exists(select(AccountMembership.id).where(
        AccountMembership.user_id == user.id, AccountMembership.customer_id == customer_id,
        AccountMembership.role.in_((*_MEMBERSHIP_LEVEL, *_ROLE_ALIASES)),
        or_(AccountMembership.expires_at.is_(None), AccountMembership.expires_at > datetime.utcnow())))
    inside = exists(select(InsideSalesAssignment.id).where(
        InsideSalesAssignment.inside_sales_user_id == user.id,
        InsideSalesAssignment.customer_id == customer_id))
    ops = exists(select(SalesOpsAssignment.id).where(
        SalesOpsAssignment.user_id == user.id, SalesOpsAssignment.customer_id == customer_id))
    team = exists(select(CustomerUser.id).join(reporting, reporting.c.report == CustomerUser.user_id).where(
        reporting.c.manager == user.id, CustomerUser.customer_id == customer_id, CustomerUser.role == "owner"))
    # SQL NULLs must behave like effective_role's empty-string normalization.
    from sqlalchemy import func
    role = func.coalesce(user.role, "")
    sales_role = func.trim(func.coalesce(user.sales_role, ""))
    recognized = ("rep", "inside_sales", "sales_manager", "sales_ops", "auditor", "sales_admin")
    global_read = or_(sales_role.in_(("auditor", "sales_admin")),
                      and_(sales_role.not_in(recognized), func.trim(role) == "auditor"))
    return or_(func.coalesce(user.is_admin, 0) == 1, and_(role != "ps_admin", or_(
        global_read, junction, membership,
        and_(sales_role == "inside_sales", inside),
        and_(sales_role == "sales_ops", ops),
        and_(sales_role == "sales_manager", or_(team, inside)),
    )))
