#!/usr/bin/env python3
"""Verify seeded data in CI.

Expected counts mirror backend/seed.py output:
- 65 use cases across 5 customers
- 60 departments
- 33 users (1 admin) and 32 customer_users junction rows

Run from the repo root against the database the seed step wrote
(SAIL_DATABASE_URL=sqlite:///./sail.db in CI).
"""

import sqlite3

EXPECTED = {
    "use_cases": 65,
    "customers": 5,
    "departments": 60,
    "users": 33,
    "customer_users": 32,
}


def main():
    conn = sqlite3.connect("sail.db")
    cursor = conn.cursor()
    failures = []
    for table, expected in EXPECTED.items():
        cursor.execute(f"SELECT count(*) FROM {table}")
        count = cursor.fetchone()[0]
        status = "OK" if count == expected else "MISMATCH"
        print(f"{table}: {count} (expected {expected}) — {status}")
        if count != expected:
            failures.append(table)
    conn.close()
    if failures:
        raise AssertionError(f"Seed verification failed for: {', '.join(failures)}")
    print("Seeded data verified successfully")


if __name__ == "__main__":
    main()
