"""Idempotent department registry sync (data repair, no schema changes).

Repairs two known data inconsistencies (see SESSION_HANDBOOK 2026-08-19):

1. Use-case department names missing from the ``departments`` registry
   (e.g. Acme's 'Operations' rows were removed from the registry through the
   UI, which NULLs ``use_cases.department_id`` on the affected use cases).
2. Use cases with ``department_id`` NULL whose ``department`` name matches a
   registry row for the same customer.

Safe to re-run: only inserts missing registry rows and fills NULL
``department_id`` values; never deletes or overwrites existing data.

Usage (inside the backend container, after docker cp into the container):
    python /tmp/sync_departments.py
Usage (host, against an explicit DB file):
    DB_PATH=/path/to/sail.db venv/bin/python scripts/sync_departments.py
"""

import os
import sqlite3
import sys


def main() -> int:
    db_path = os.environ.get("DB_PATH") or "/app/sail.db"
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    created = 0
    linked = 0
    try:
        customers = cur.execute("SELECT id, name FROM customers").fetchall()
        for cid, cname in customers:
            reg = {
                r[0]
                for r in cur.execute(
                    "SELECT name FROM departments WHERE customer_id = ?", (cid,)
                )
            }
            uc_names = {
                r[0]
                for r in cur.execute(
                    "SELECT DISTINCT department FROM use_cases "
                    "WHERE customer_id = ? AND department IS NOT NULL AND department != ''",
                    (cid,),
                )
            }
            for name in sorted(uc_names - reg):
                cur.execute(
                    "INSERT INTO departments (name, customer_id) VALUES (?, ?)",
                    (name, cid),
                )
                created += 1
                print(f"  + created registry row: {cname} / {name}")
            orphans = cur.execute(
                "SELECT id, department FROM use_cases "
                "WHERE customer_id = ? AND department_id IS NULL "
                "AND department IS NOT NULL AND department != ''",
                (cid,),
            ).fetchall()
            for uc_id, uc_dept in orphans:
                match = cur.execute(
                    "SELECT id FROM departments WHERE customer_id = ? AND name = ?",
                    (cid, uc_dept),
                ).fetchone()
                if match:
                    cur.execute(
                        "UPDATE use_cases SET department_id = ? WHERE id = ?",
                        (match[0], uc_id),
                    )
                    linked += 1
                    print(f"  ~ linked use case {uc_id} -> {uc_dept} (dept id {match[0]})")
        con.commit()
        print(f"Done: {created} registry rows created, {linked} use cases linked.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
