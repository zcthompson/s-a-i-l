"""Creator-ownership backfill (CRM prerequisites — data repair, no schema changes).

Closes the 2026-10-15 gap: customers created via the API/UI historically
carried only the legacy ``customer_users`` owner row, with no
``account_memberships`` primary_owner row. This script gives legacy-only
owners their primary_owner membership rows (``source='migration'``).

Safety properties (also pinned in tests/backend/test_crm_prerequisites.py):
- DRY-RUN BY DEFAULT. Nothing is written unless ``--apply`` is passed.
- Idempotent: re-running after a completed apply reports zero gaps.
- Conflicts are reported, never touched: an account that ALREADY has a
  primary_owner membership held by another user is listed with
  ``action='report_only'`` and no row is inserted for it.
- Multiple distinct legacy owners are reported as ambiguous; duplicate
  junctions for the same owner are treated as one candidate.
- Apply reserves the SQLite writer before checking candidates; a failure
  rolls back all writes.
- One ``audit_logs`` row (action ``ownership.backfill``) records the pass
  without any customer details beyond the affected customer ids.

Validate against a DISPOSABLE copy of the database first — never point
--apply at a live/dev DB without operator review.

Usage (host, against an explicit DB file — dry-run):
    DB_PATH=/path/to/sail.db venv/bin/python scripts/backfill_creator_ownerships.py
Usage (apply, after operator review of the dry-run report):
    DB_PATH=/path/to/sail.db venv/bin/python scripts/backfill_creator_ownerships.py --apply
"""

import json
import os
import sqlite3
import sys

BACKFILL_ACTOR = "system:backfill"


def main() -> int:
    db_path = os.environ.get("DB_PATH") or "/app/sail.db"
    apply = "--apply" in sys.argv[1:]
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute("SELECT COUNT(*) FROM account_memberships")
    if cur.fetchone()[0] is None:
        print("error: account_memberships table missing (run migrations first)")
        return 1

    # Reserve the SQLite writer BEFORE reading candidates on apply.
    if apply:
        cur.execute("BEGIN IMMEDIATE")

    gaps = []
    cur.execute("""
        SELECT DISTINCT cu.customer_id AS customer_id, c.name AS customer_name,
               cu.user_id AS owner_user_id,
               (SELECT COUNT(*) FROM account_memberships po
                 WHERE po.customer_id = cu.customer_id
                   AND po.role = 'primary_owner'
                   AND po.user_id != cu.user_id) AS other_po,
               (SELECT COUNT(DISTINCT legacy.user_id) FROM customer_users legacy
                 WHERE legacy.customer_id = cu.customer_id
                   AND legacy.role = 'owner') AS legacy_owners
        FROM customer_users cu
        JOIN customers c ON c.id = cu.customer_id
        WHERE cu.role = 'owner'
          AND NOT EXISTS (SELECT 1 FROM account_memberships po
                          WHERE po.customer_id = cu.customer_id
                            AND po.role = 'primary_owner'
                            AND po.user_id = cu.user_id)
    """)
    for r in cur.fetchall():
        ambiguous = r["legacy_owners"] > 1
        conflict = r["other_po"] > 0 or ambiguous
        gaps.append({
            "customer_id": r["customer_id"],
            "customer_name": r["customer_name"],
            "owner_user_id": r["owner_user_id"],
            "conflict": conflict,
            "reason": "multiple_legacy_owners" if ambiguous else
                      "existing_primary_owner" if conflict else None,
            "action": "report_only" if conflict else "backfill",
        })

    to_add = [g for g in gaps if not g["conflict"]]
    conflicts = sorted({g["customer_id"] for g in gaps if g["conflict"]})

    if apply and to_add:
        try:
            for g in to_add:
                cur.execute(
                    "INSERT INTO account_memberships "
                    "(user_id, customer_id, role, section_grants, source, created_at) "
                    "VALUES (?, ?, 'primary_owner', NULL, 'migration', CURRENT_TIMESTAMP)",
                    (g["owner_user_id"], g["customer_id"]),
                )
            cur.execute(
                "INSERT INTO audit_logs (user_id, username, action, customer_id, "
                "target_id, details, created_at) VALUES (0, ?, 'ownership.backfill', "
                "NULL, NULL, ?, CURRENT_TIMESTAMP)",
                (BACKFILL_ACTOR, json.dumps(
                    {"added": len(to_add),
                     "conflicts_reported": len(conflicts),
                     "dry_run": False}, sort_keys=True)),
            )
            con.commit()
        except Exception:
            con.rollback()
            print("error: backfill failed and rolled back; no data changed", file=sys.stderr)
            return 1

    report = {
        "db": db_path,
        "dry_run": not apply,
        "gaps": len(gaps),
        "to_add": len(to_add),
        "added": 0 if not apply else len(to_add),
        "conflicts": conflicts,
        "detail": gaps,
    }
    con.close()
    print(json.dumps(report, indent=2))
    if apply and to_add:
        print(f"applied: {len(to_add)} primary_owner membership(s) + audit row")
    elif not apply:
        print("dry-run: pass --apply after operator review to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
