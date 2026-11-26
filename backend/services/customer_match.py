"""Customer matching for the Intelligence Import (Part 14 import remediation).

Operator rules (2026-11-01): every Intelligence Import maps a supplied account
name to an EXISTING customer by customer name OR alias, case-insensitive
(``normalize_alias`` — NFKC + casefold + whitespace collapse, the same
normalization the alias write rules use; gap #6 made it Unicode-aware); a name
that cannot be matched is skipped and counted in the import's warning, never
blocks the rest of the file, and never creates a customer.

A supplied name resolves to exactly one customer or to a skip reason:
- ``unmatched`` — no customer name or alias equals it;
- ``ambiguous`` — it equals more than one customer (two normalized-equal
  names, or one customer's name and another customer's alias). Names and
  aliases are unique by rule, so this is defensive: such a row is reported,
  never routed to whichever customer happens to win.

The matcher loads customers and aliases in two fixed queries — never a
per-row lookup.
"""

import re
import unicodedata
from collections import defaultdict

from sqlalchemy.orm import Session

from backend.models.customer_alias import CustomerAlias
from backend.models.use_case import Customer
from backend.services.customer_alias_service import normalize_alias

UNMATCHED = "unmatched"
AMBIGUOUS = "ambiguous"


def _suggestion_key(value):
    text = unicodedata.normalize("NFKD", value).casefold().replace("&", " and ")
    return " ".join(token for token in re.findall(r"[a-z0-9]+", text)
                    if token not in {"the", "inc", "incorporated", "corp", "corporation", "company",
                                     "co", "llc", "ltd", "limited"})


class CustomerMatcher:
    """Resolve supplied account names against customer names + aliases."""

    def __init__(self, db: Session):
        self.by_id = {}
        self._names = defaultdict(list)
        for customer in db.query(Customer).order_by(Customer.id).all():
            self.by_id[customer.id] = customer
            self._names[normalize_alias(customer.name)].append(customer)
        self._aliases = {}
        for alias_norm, customer_id in db.query(
            CustomerAlias.alias_norm, CustomerAlias.customer_id,
        ).all():
            customer = self.by_id.get(customer_id)
            if customer is not None:
                self._aliases[alias_norm] = customer

        self._suggestions = defaultdict(set)
        for customer in self.by_id.values():
            key = _suggestion_key(customer.name)
            if key:
                self._suggestions[key].add(customer.id)
        for alias, customer in self._aliases.items():
            key = _suggestion_key(alias)
            if key:
                self._suggestions[key].add(customer.id)

    def suggest(self, name, scope=None):
        """Return one globally unambiguous, accessible suggestion; never match.

        Scope is a set of accessible customer IDs, or None for unrestricted
        access. Filter only after checking global ambiguity to avoid treating
        an ambiguous supplied name as an account identity.
        """
        candidates = self._suggestions.get(_suggestion_key(name or ""), set())
        if len(candidates) == 1:
            cid = next(iter(candidates))
            if scope is None or cid in scope:
                return {"customer_id": cid, "customer_name": self.by_id[cid].name}
        return None

    def resolve(self, supplied):
        """Return ``(customer, "name" | "alias")`` or ``(None, reason)``."""
        key = normalize_alias(supplied)
        if not key:
            return None, UNMATCHED
        candidates = {customer.id: customer for customer in self._names.get(key, [])}
        aliased = self._aliases.get(key)
        if aliased is not None:
            candidates.setdefault(aliased.id, aliased)
        if len(candidates) > 1:
            return None, AMBIGUOUS
        if not candidates:
            return None, UNMATCHED
        customer = next(iter(candidates.values()))
        return customer, "name" if self._names.get(key) else "alias"
