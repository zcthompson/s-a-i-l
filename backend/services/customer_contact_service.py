"""Contact validation, persistence, and evidence-only buying coverage."""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm.attributes import set_committed_value

from backend.models.customer_contact import (
    BUYING_ROLES,
    ContactBuyingRole,
    CustomerContact,
    contact_notes,
    contact_technologies,
    contact_use_cases,
)
from backend.models.customer_technology import CustomerTechnology
from backend.models.sales_note import VERIFICATION_STATES, SalesNote
from backend.models.use_case import UseCase
from backend.services import record_cleanup
from backend.services.account_engagement import last_meaningful_interaction_for
from backend.services.sales_personas import validate_persona

LAST_CONTACTED_BASIS = "No qualified interaction evidence recorded (editing a contact is not engagement)"
_LINKS = (
    ("related_note_ids", "related_notes", contact_notes, SalesNote, "note"),
    ("related_use_case_ids", "related_use_cases", contact_use_cases, UseCase, "use case"),
    ("related_technology_ids", "related_technologies", contact_technologies, CustomerTechnology, "technology"),
)


def list_contacts(db, customer_id, include_archived=False, search=None):
    query = db.query(CustomerContact).filter_by(customer_id=customer_id)
    if not include_archived:
        query = query.filter(CustomerContact.archived.is_(False))
    if search and search.strip():
        term = search.strip().replace("!", "!!").replace("%", "!%").replace("_", "!_")
        pattern = f"%{term}%"
        query = query.filter(or_(*(field.ilike(pattern, escape="!") for field in
                                  (CustomerContact.display_name, CustomerContact.title,
                                   CustomerContact.department))))
    contacts = query.order_by(CustomerContact.id).all()
    if not contacts:
        return contacts
    by_id = {contact.id: contact for contact in contacts}
    for field, _, table, _, _ in _LINKS:
        ids = {key: [] for key in by_id}
        for contact_id, related_id in db.execute(select(table).where(table.c.contact_id.in_(by_id))):
            ids[contact_id].append(related_id)
        for key, contact in by_id.items():
            setattr(contact, f"_{field}", ids[key])
    roles = {key: [] for key in by_id}
    for role in db.query(ContactBuyingRole).filter(ContactBuyingRole.contact_id.in_(by_id)).order_by(ContactBuyingRole.id):
        roles[role.contact_id].append(role)
    for key, contact in by_id.items():
        set_committed_value(contact, "buying_roles", roles[key])
    return contacts


def _verification(value):
    if value not in VERIFICATION_STATES:
        raise HTTPException(422, f"verification_state must be one of: {', '.join(VERIFICATION_STATES)}")


def _validated(db, customer_id, payload):
    data = dict(payload)
    if "display_name" in data:
        if not isinstance(data["display_name"], str) or not data["display_name"].strip():
            raise HTTPException(422, "display_name is required")
        data["display_name"] = data["display_name"].strip()
    if "persona" in data:
        error = validate_persona(data["persona"])
        if error:
            raise HTTPException(422, error)
    if "verification_state" in data:
        _verification(data["verification_state"])
    roles = data.pop("buying_roles", None)
    if roles is not None:
        seen = set()
        for role in roles:
            name = role.get("role")
            if name not in BUYING_ROLES:
                raise HTTPException(422, f"Unknown buying role '{name}'")
            if name in seen:
                raise HTTPException(422, f"Duplicate buying role '{name}'")
            seen.add(name)
            _verification(role.get("verification_state", "verified"))
    links = {}
    for field, relation, _, model, label in _LINKS:
        if field not in data:
            continue
        ids = data.pop(field) or []
        rows = db.query(model).filter(model.id.in_(ids), model.customer_id == customer_id).all() if ids else []
        found = {row.id for row in rows}
        for related_id in ids:
            if related_id not in found:
                raise HTTPException(422, f"Related {label} {related_id} does not belong to this customer")
        links[relation] = rows
    # The customer and audit identity are always supplied by the caller.
    allowed = {"display_name", "title", "email", "phone", "department", "persona", "source",
               "observation_date", "verification_state", "archived"}
    return {key: value for key, value in data.items() if key in allowed}, roles, links


def _apply(db, contact, data, roles, links, username):
    for key, value in data.items():
        if key == "archived":
            if value is None:
                continue
            contact.archived_at = datetime.utcnow() if value else None
        setattr(contact, key, value)
    if roles is not None:
        # Flush the old set before insertion to respect the unique pair constraint.
        contact.buying_roles = []
        db.flush()
        contact.buying_roles = [ContactBuyingRole(**role) for role in roles]
    for relation, rows in links.items():
        setattr(contact, relation, rows)
    for field, *_ in _LINKS:
        contact.__dict__.pop(f"_{field}", None)
    contact.updated_by = username
    db.commit()
    db.refresh(contact)
    return contact


def create_contact(db, customer_id, payload: dict, username: str):
    if "display_name" not in payload:
        raise HTTPException(422, "display_name is required")
    data, roles, links = _validated(db, customer_id, payload)
    data.pop("archived", None)
    contact = CustomerContact(customer_id=customer_id, created_by=username)
    db.add(contact)
    return _apply(db, contact, data, roles, links, username)


def update_contact(db, contact, payload: dict, username: str):
    return _apply(db, contact, *_validated(db, contact.customer_id, payload), username)


def delete_contact(db, contact):
    if db.execute(select(contact_notes.c.contact_id).where(contact_notes.c.contact_id == contact.id).limit(1)).first():
        raise HTTPException(409, "Contact has linked sales notes; archive the contact instead (historical note references are preserved)")
    record_cleanup.contacts(db, [contact.id])
    db.delete(contact)
    db.commit()


def contact_coverage_for(db, customer_id):
    archived_count = (select(func.count(CustomerContact.id))
                      .where(CustomerContact.customer_id == customer_id, CustomerContact.archived.is_(True))
                      .scalar_subquery())
    # An outer join preserves the archived count even when there are no active contacts.
    anchor = select(archived_count.label("archived_count")).subquery()
    contacts = db.query(CustomerContact.id, CustomerContact.persona, anchor.c.archived_count).select_from(anchor).outerjoin(
        CustomerContact, (CustomerContact.customer_id == customer_id) & CustomerContact.archived.is_(False)).all()
    ids = [row.id for row in contacts if row.id is not None]
    roles = dict.fromkeys(BUYING_ROLES, 0)
    for (role,) in db.query(ContactBuyingRole.role).filter(ContactBuyingRole.contact_id.in_(ids)).all():
        roles[role] += 1
    personas = {}
    unknown = 0
    for row in contacts:
        if row.id is None:
            continue
        if row.persona is None:
            unknown += 1
        else:
            personas[row.persona] = personas.get(row.persona, 0) + 1
    gaps = []
    if not ids:
        gaps.append("No contacts recorded")
    if not roles["economic_buyer"]:
        gaps.append("No economic buyer recorded")
    if not roles["champion"]:
        gaps.append("No champion recorded")
    last = last_meaningful_interaction_for(db, customer_id)
    basis = (f"Last meaningful interaction {last.isoformat()} (recorded activities and dated notes; "
             "imports, record edits, and scheduling are not engagement)" if last else LAST_CONTACTED_BASIS)
    return {"customer_id": customer_id, "calc_version": "contact-coverage/2", "source": "customer_contacts",
            "contacts_recorded": len(ids), "archived_count": contacts[0].archived_count,
            "roles": roles, "economic_buyer_recorded": bool(roles["economic_buyer"]),
            "champion_recorded": bool(roles["champion"]), "personas": personas,
            "persona_unknown": unknown, "gaps": gaps, "last_contacted": last.isoformat() if last else None,
            "last_contacted_basis": basis}


def contact_coverage_card(coverage, customer_name):
    gaps = coverage["gaps"]
    if not gaps:
        return None
    return {"id": f"contact-coverage-{coverage['customer_id']}", "type": "contact_coverage",
            "severity": "high" if "No contacts recorded" in gaps or "No economic buyer recorded" in gaps else "medium",
            "title": "; ".join(gaps),
            "detail": f"{coverage['contacts_recorded']} contacts recorded; {sum(coverage['roles'].values())} buying role(s) recorded",
            "evidence": {"source": "customer_contacts", "source_id": coverage["customer_id"],
                         "source_name": "Account contact coverage"}}
