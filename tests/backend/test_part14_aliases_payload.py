"""shared-seam pins: alias payloads, import matching.

- customer LIST/DETAIL payloads gain ``aliases`` (raw strings, sorted) —
  the list carries them via ONE batched query (the H2 fixed-query
  convention: the customer_aliases query count must NOT scale with the
  number of accounts or aliases);
- pipeline + rep CSV imports match name-first-then-alias; the reports
  read back ``matched_by`` ("name" | "alias") and legacy rows read back
  as "name" exactly as they matched before aliases existed.

Run: pytest tests/backend/test_part14_aliases_payload.py -v
"""

import csv
import io
from urllib.parse import quote

import pytest
from backend.models.customer_alias import CustomerAlias
from backend.models.intelligence_import import PartnerPipeline
from backend.models.use_case import Customer
from sqlalchemy import event

from tests.backend.common import _headers

BASE_PIPELINE = "/api/intelligence-import/"
BASE_REP = "/api/rep-intelligence/"
PIPE_HEADER = [
    "Customer Account", "Opportunity Name", "Opp Stage", "Est. ACV Line Amount (USD)",
    "Product Offering Group", "Close Date", "Partner Account", "FLAG - Growth / Risk",
]
REP_HEADER = ["customer_name", "technology_name"]


def _alias(db, customer, alias, norm=None):
    row = CustomerAlias(
        customer_id=customer.id, alias=alias,
        alias_norm=norm if norm is not None else " ".join(alias.lower().split()),
        created_by="admin",
    )
    db.add(row)
    db.commit()
    return row


def _pipeline_csv(rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(PIPE_HEADER)
    for account in rows:
        writer.writerow([account, " Platform ", " Negotiation ", "$1,000",
                         "RHEL", "2026-10-30", " Partner ", "growth"])
    return stream.getvalue().encode()


def _rep_csv(rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(REP_HEADER)
    for name in rows:
        writer.writerow([name, "Synthetic Platform"])
    return stream.getvalue().encode()


@pytest.fixture()
def world(db_session):
    zeta = Customer(name="Zeta Co")
    alpha = Customer(name="Alpha LLC")
    midway = Customer(name="Midway")
    db_session.add_all([zeta, alpha, midway])
    db_session.commit()
    # Deliberately unsorted + case-mixed: the payload must come back
    # sorted (codepoint order) regardless of insertion order.
    _alias(db_session, zeta, "zeta")
    _alias(db_session, zeta, "Alpha Alias")
    _alias(db_session, midway, "Midway  Group")
    return {"zeta": zeta, "alpha": alpha, "midway": midway}


def _family_counts(statements, family):
    return sum(1 for statement in statements if family in statement.lower())


class TestAliasPayloads:
    def test_list_payload_carries_sorted_aliases(self, client, world):
        response = client.get("/api/customers/", headers=_headers())
        assert response.status_code == 200, response.text
        rows = {row["name"]: row for row in response.json()}
        assert rows["Zeta Co"]["aliases"] == ["Alpha Alias", "zeta"]
        assert rows["Alpha LLC"]["aliases"] == []
        assert rows["Midway"]["aliases"] == ["Midway  Group"]

    def test_list_alias_query_count_does_not_scale(self, client, db_session, world):
        engine = db_session.get_bind().engine
        statements = []

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            response = client.get("/api/customers/", headers=_headers())
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert response.status_code == 200
        # One batched alias query — never one per account (H2 defect class).
        # (The total statement count is NOT pinned here: build_customer_response
        # lazy-loads the departments relationship per customer — pre-existing,
        # out of scope for this change. The alias path is what this pin guards.)
        assert _family_counts(statements, "customer_aliases") == 1
        baseline_alias_queries = _family_counts(statements, "customer_aliases")

        # Two more accounts (one with two aliases): the alias query count is
        # identical — the batch query does not scale with rows.
        extra = Customer(name="Extra One")
        extra2 = Customer(name="Extra Two")
        db_session.add_all([extra, extra2])
        db_session.commit()
        _alias(db_session, extra2, "extra two")
        _alias(db_session, extra2, "Another Extra")

        statements.clear()
        event.listen(engine, "before_cursor_execute", record)
        try:
            response = client.get("/api/customers/", headers=_headers())
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert response.status_code == 200
        assert _family_counts(statements, "customer_aliases") == 1
        assert _family_counts(statements, "customer_aliases") == baseline_alias_queries
        rows = {row["name"]: row for row in response.json()}
        assert rows["Extra Two"]["aliases"] == ["Another Extra", "extra two"]

    def test_detail_payload_carries_aliases_single_read(self, client, db_session, world):
        engine = db_session.get_bind().engine
        statements = []

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            response = client.get(
                f"/api/customers/{quote(world['zeta'].name, safe='')}/", headers=_headers())
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert response.status_code == 200, response.text
        assert response.json()["aliases"] == ["Alpha Alias", "zeta"]
        # The detail path is ONE read — not one per alias.
        assert _family_counts(statements, "customer_aliases") == 1


class TestImportMatching:
    def _world2(self, db_session):
        alpha = Customer(name="Alpha Corp")
        omega = Customer(name="Omega Ltd")
        db_session.add_all([alpha, omega])
        db_session.commit()
        _alias(db_session, alpha, "alpha")
        _alias(db_session, omega, "omega group")
        return alpha, omega

    def test_pipeline_matches_name_first_then_alias(self, client, db_session):
        alpha, omega = self._world2(db_session)
        response = client.post(
            BASE_PIPELINE, headers=_headers(),
            files={"file": ("pipeline.csv", _pipeline_csv([
                "ALPHA  CORP",     # name match
                "alpha",           # alias match
                "omega group",     # alias match (case/whitespace normalized)
                "Omega Ltd",       # name match
                "Nobody Inc",      # unmatched
            ]), "text/csv")})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["matched_accounts"] == 2
        assert body["matched_rows"] == 4
        assert body["unmatched"] == [
            {"account_name": "Nobody Inc", "row_count": 1, "reason": "unmatched"}]
        assert body["skipped_rows"] == 1
        by_name = {item["customer_name"]: item for item in body["matched"]}
        # Name rows present → the entry reports "name" (name-first).
        assert by_name["Alpha Corp"]["matched_by"] == "name"
        assert by_name["Alpha Corp"]["row_count"] == 2
        # Every spelling the file used is listed with how it matched.
        assert by_name["Alpha Corp"]["supplied_names"] == [
            {"name": "ALPHA  CORP", "row_count": 1, "matched_by": "name"},
            {"name": "alpha", "row_count": 1, "matched_by": "alias"},
        ]
        assert by_name["Omega Ltd"]["matched_by"] == "name"
        assert by_name["Omega Ltd"]["row_count"] == 2

    def test_pipeline_alias_only_rows_report_alias(self, client, db_session):
        alpha, omega = self._world2(db_session)
        response = client.post(
            BASE_PIPELINE, headers=_headers(),
            files={"file": ("pipeline.csv", _pipeline_csv([
                "alpha",
                "OMEGA GROUP",
            ]), "text/csv")})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["matched_accounts"] == 2
        assert body["matched_rows"] == 2
        by_name = {item["customer_name"]: item for item in body["matched"]}
        assert by_name["Alpha Corp"]["matched_by"] == "alias"
        assert by_name["Omega Ltd"]["matched_by"] == "alias"
        # The rows landed on the right customers (alias resolution).
        assert db_session.query(PartnerPipeline).filter_by(
            customer_id=alpha.id).count() == 1

    def test_pipeline_name_colliding_with_foreign_alias_is_skipped(self, client, db_session):
        # Defense pin: names and aliases are
        # unique by rule, but if a foreign alias's norm collided with a
        # customer name (raw-DB legacy), the row must be reported as
        # ambiguous — never silently routed to either customer.
        acme = Customer(name="Acme")
        other = Customer(name="Other Co")
        db_session.add_all([acme, other])
        db_session.commit()
        db_session.add(CustomerAlias(customer_id=other.id, alias="acme",
                                     alias_norm="acme", created_by="admin"))
        db_session.commit()
        response = client.post(
            BASE_PIPELINE, headers=_headers(),
            files={"file": ("pipeline.csv", _pipeline_csv(["ACME"]), "text/csv")})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["matched_accounts"] == 0 and body["skipped_rows"] == 1
        assert body["unmatched"] == [
            {"account_name": "ACME", "row_count": 1, "reason": "ambiguous"}]
        assert db_session.query(PartnerPipeline).count() == 0

    def test_rep_csv_alias_match_and_matched_by(self, client, db_session):
        alpha, _omega = self._world2(db_session)
        response = client.post(
            BASE_REP, headers=_headers(),
            files={"file": ("observations.csv", _rep_csv([
                "alpha co",        # no such alias → unmatched skip
                "alpha",           # alias match
                "ALPHA CORP",      # name match
            ]), "text/csv")})
        assert response.status_code == 201, response.text
        body = response.json()
        detail = client.get(f"{BASE_REP}{body['import_id']}/", headers=_headers())
        assert detail.status_code == 200, detail.text
        rows = detail.json()["rows"]
        by_supplied = {row["customer_name_supplied"]: row for row in rows}
        assert by_supplied["alpha"]["matched_by"] == "alias"
        assert by_supplied["alpha"]["customer_name"] == "Alpha Corp"
        assert by_supplied["ALPHA CORP"]["matched_by"] == "name"
        assert by_supplied["ALPHA CORP"]["customer_name"] == "Alpha Corp"
        # The unmatched row keeps its exact skip disposition — unchanged.
        skipped = by_supplied["alpha co"]
        assert "matched_by" not in skipped
        assert skipped["status"] == "skipped"
        assert skipped["issues"][0]["code"] == "customer_unmatched"
        assert db_session.query(PartnerPipeline).count() == 0
        # The import warning count; the rest imported; no customer created.
        assert detail.json()["unmatched_customer_rows"] == 1
        assert body["imported_rows"] == 2 and body["skipped_rows"] == 1
        assert db_session.query(Customer).count() == 2

    def test_rep_csv_legacy_rows_read_back_as_name(self, client, db_session):
        # Rows whose supplied name is norm-equal the customer name read back
        # as "name" — the pre-alias historical fact, even while a distinct
        # alias on the same customer exists.
        alpha, _omega = self._world2(db_session)
        response = client.post(
            BASE_REP, headers=_headers(),
            files={"file": ("observations.csv", _rep_csv(["alpha corp"]),
                            "text/csv")})
        assert response.status_code == 201, response.text
        body = response.json()
        detail = client.get(f"{BASE_REP}{body['import_id']}/", headers=_headers())
        assert detail.status_code == 200
        row = detail.json()["rows"][0]
        assert row["matched_by"] == "name"
        assert row["customer_id"] == alpha.id
