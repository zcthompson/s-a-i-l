"""Customer alias tags — write surface (Part 14, A2).

Aliases are alternate names for a customer account. ``alias_norm`` uses the
matching normalization — NFKC + casefold + whitespace collapse (gap #6:
Unicode-aware, single source ``normalize_alias`` below; the intelligence
import's ``_norm`` is this function) — and is UNIQUE portfolio-wide, so one
alias always resolves to one customer. Stored norms were recomputed under
this form by migration 0030.

Write rules (deterministic, checked in this order):
- empty / whitespace-only → "Alias must not be empty";
- equal to the customer's own name → "Alias must differ from the customer name";
- equal to ANY other customer's name → "Alias matches an existing customer name";
- already an alias of ANY customer → "Alias already in use" (race-safe: the
  unique constraint + IntegrityError fallback, the H5 task source_key pattern).

Errors are ValueError carrying the exact message; the route maps them to
status codes.
"""

import unicodedata
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models.customer_alias import CustomerAlias
from backend.models.use_case import Customer

EMPTY = "Alias must not be empty"
OWN_NAME = "Alias must differ from the customer name"
OTHER_NAME = "Alias matches an existing customer name"
DUPLICATE = "Alias already in use"
NOT_FOUND = "Alias not found"


def normalize_alias(value) -> str:
    """The matching normalization: NFKC + casefold + whitespace collapse.

    NFKC folds full-width and compatibility characters to their canonical
    equivalents (ＮｏｒｔｈｗｉｎｄＦ -> NorthwindF); casefold is the Unicode-aware case
    mapping (a superset of ``lower`` — ß -> ss). This is the single source
    for alias norms (the intelligence import's ``_norm`` is this function);
    stored ``alias_norm`` values were recomputed under this form by
    migration 0030 (gap #6). ASCII-only input is byte-identical to the
    legacy lower+collapse form.
    """
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def _find_by_norm(db: Session, alias_norm: str):
    """Pre-check for an existing alias (any customer) with this normalization."""
    return db.query(CustomerAlias.id).filter(CustomerAlias.alias_norm == alias_norm).first()


def list_aliases(db: Session, customer: Customer) -> list[CustomerAlias]:
    """The customer's aliases in raw-alias codepoint order."""
    rows = db.query(CustomerAlias).filter(CustomerAlias.customer_id == customer.id).all()
    return sorted(rows, key=lambda row: row.alias)


def add_alias(db: Session, customer: Customer, alias: str, username: str) -> CustomerAlias:
    """Validate and insert one alias; commit and return the row."""
    alias_norm = normalize_alias(alias)
    if not alias_norm:
        raise ValueError(EMPTY)
    if alias_norm == normalize_alias(customer.name):
        raise ValueError(OWN_NAME)
    for (name,) in db.query(Customer.name).filter(Customer.id != customer.id):
        if normalize_alias(name) == alias_norm:
            raise ValueError(OTHER_NAME)
    if _find_by_norm(db, alias_norm) is not None:
        raise ValueError(DUPLICATE)
    row = CustomerAlias(customer_id=customer.id, alias=alias, alias_norm=alias_norm,
                        created_by=username, created_at=datetime.now(UTC))
    try:
        db.add(row)
        db.flush()
        db.commit()
    except IntegrityError:
        # A concurrent insert won the unique alias_norm slot after the pre-check.
        db.rollback()
        existing = (db.query(CustomerAlias.id)
                    .filter(CustomerAlias.alias_norm == alias_norm).scalar())
        if existing is None:
            raise
        raise ValueError(DUPLICATE) from None
    db.refresh(row)
    return row


def remove_alias(db: Session, customer: Customer, alias_id: int) -> None:
    """Delete one of the customer's aliases; another customer's id is not found."""
    row = (db.query(CustomerAlias)
           .filter(CustomerAlias.id == alias_id, CustomerAlias.customer_id == customer.id)
           .first())
    if row is None:
        raise ValueError(NOT_FOUND)
    db.delete(row)
    db.commit()
