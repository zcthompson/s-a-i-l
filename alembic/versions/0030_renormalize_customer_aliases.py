"""Recompute customer alias norms under the Unicode-aware normalization (gap #6).

``normalize_alias`` gained NFKC + casefold (it was ``lower`` + collapse).
Existing ``alias_norm`` values are recomputed so stored rows stay consistent
with live matching:

- rows whose recomputed norm equals the stored norm are untouched;
- two rows sharing a recomputed norm (a collision that was legal under the
  legacy normalization) keep the smallest id (the oldest row) and the rest
  are deleted — logged with the alias texts;
- a row whose recomputed norm equals ANY customer name's recomputed norm
  (including its own customer's) is deleted — under the new normalization it
  would route imports to a different customer, violating the write invariants
  (OTHER_NAME / OWN_NAME) — logged with the alias text.

Fixed-point (NFKC / casefold / whitespace collapse are idempotent), so a
re-run is a no-op. Downgrade restores the legacy norm (``lower`` + collapse)
for surviving rows; rows deleted by the upgrade are unrecoverable (their
texts are recorded in the upgrade log).
"""
import logging
import unicodedata

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger(__name__)

revision: str = "0030_renormalize_customer_aliases"
down_revision: str = "0029_netsuite_import"
branch_labels: object = None
depends_on: object = None


def _new_norm(value: str | None) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def _old_norm(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("customer_aliases"):
        return
    aliases = bind.execute(
        sa.text("SELECT id, customer_id, alias FROM customer_aliases ORDER BY id")
    ).fetchall()
    if not aliases:
        return
    customer_norms = {
        _new_norm(name) for (name,) in bind.execute(sa.text("SELECT name FROM customers")).fetchall()
    }

    groups: dict[str, list[tuple[int, int, str]]] = {}
    for aid, cid, alias in aliases:
        groups.setdefault(_new_norm(alias), []).append((aid, cid, alias))

    deleted: list[tuple[int, int, str]] = []
    for norm, rows in groups.items():
        if norm in customer_norms:
            # Under the new normalization this alias matches a customer NAME —
            # every such row would route to that customer, not its own.
            deleted.extend(rows)
        elif len(rows) > 1:
            # rows are in ascending id order — the oldest keeps the norm.
            deleted.extend(rows[1:])
    for aid, cid, alias in deleted:
        logger.warning(
            "alias %r (id %s, customer_id %s) removed by the Unicode re-normalization "
            "(its new norm %r matches a customer name or an older alias)",
            alias, aid, cid, _new_norm(alias),
        )
    deleted_ids = {d[0] for d in deleted}
    for aid in deleted_ids:
        bind.execute(sa.text("DELETE FROM customer_aliases WHERE id = :id"), {"id": aid})

    updated = 0
    for aid, _cid, alias in aliases:
        if aid in deleted_ids:
            continue
        if _old_norm(alias) != _new_norm(alias):
            bind.execute(
                sa.text("UPDATE customer_aliases SET alias_norm = :norm WHERE id = :id"),
                {"norm": _new_norm(alias), "id": aid},
            )
            updated += 1
    logger.info("alias re-normalization: %d norm(s) updated, %d row(s) removed", updated, len(deleted))


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("customer_aliases"):
        return
    restored = 0
    for aid, alias in bind.execute(sa.text("SELECT id, alias FROM customer_aliases")).fetchall():
        old, new = _old_norm(alias), _new_norm(alias)
        if old != new:
            bind.execute(
                sa.text("UPDATE customer_aliases SET alias_norm = :norm WHERE id = :id"),
                {"norm": old, "id": aid},
            )
            restored += 1
    logger.warning(
        "downgrade restored the legacy alias norms (%d row(s)); rows deleted by the "
        "0030 upgrade (customer-name or duplicate collisions) are unrecoverable",
        restored,
    )
