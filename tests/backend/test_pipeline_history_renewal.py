"""H3 acceptance contracts over deterministic synthetic retained snapshots."""

from contextlib import contextmanager
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from backend.auth import create_access_token
from backend.models.intelligence_import import PartnerPipeline
from backend.models.use_case import Customer, CustomerUser, User
from backend.services import intelligence_import_service as imports
from backend.services import pipeline_read_model as pipeline
from fastapi import HTTPException
from sqlalchemy import event

from tests.backend._shared import add_pipeline_batch

REFERENCE = date(2026, 10, 27)
AS_OF = "2026-10-27T12:00:00Z"
DATED = ("overdue", "within_30", "within_60", "within_90", "within_180")
DELTAS = ("added", "observed_removed", "stage_changes", "close_date_changes",
          "name_changes", "amount_changes")


@pytest.fixture()
def account(db_session):
    customer = Customer(name="Synthetic H3 Account")
    db_session.add(customer)
    db_session.flush()
    return customer


def _batch(number):
    return SimpleNamespace(id=number, file_name=f"synthetic-{number}.csv",
                           created_at=datetime(2026, 10, 25, 12), imported_by="admin")


def _line(number="OPP-1", *, row_id=1, **fields):
    return PartnerPipeline(id=row_id, import_id=1, customer_id=1,
                           customer_account_name="Synthetic H3 Account",
                           **{"source_row": row_id, "opportunity_number": number,
                              "opp_stage": "Discover", "currency_code": "USD", **fields})


def _compare(before, after):
    return pipeline.compare_pipeline_snapshots(before, after, _batch(1), _batch(2), as_of=AS_OF)


def _cards(summary):
    return [card for bucket in (*DATED, "unknown_date") for card in summary["buckets"][bucket]]


@contextmanager
def _statements(db):
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(db.bind, "before_cursor_execute", record)


def test_missing_ids_are_never_matched_or_delta_money():
    before = [_line(None, est_acv_usd=100), _line(" ", row_id=2, est_acv_usd=200)]
    after = [_line("", row_id=3, est_acv_usd=300), _line(None, row_id=4, est_acv_usd=400)]
    result = _compare(before, after)
    assert result["unidentified"] == {"from": 2, "to": 2}
    assert result["opportunity_count"] == {"from": 0, "to": 0}
    assert all(result[key] == [] for key in (*DELTAS, "unchanged", "ambiguity"))
    assert pipeline.summarize_pipeline_rows(before)["amounts"]["acv"]["total"] == 300.0
    assert pipeline.summarize_pipeline_rows(after)["amounts"]["acv"]["total"] == 700.0


def test_reordered_duplicate_looking_lines_preserve_opportunity_totals():
    before = [_line(" OPP-1 ", row_id=1, product_sku="SAME", est_acv_usd=0.1),
              _line(row_id=2, product_sku="SAME", est_acv_usd=0.2)]
    after = [_line(row_id=4, source_row=8, product_sku="SAME", est_acv_usd=0.2),
             _line(row_id=3, source_row=9, product_sku="SAME", est_acv_usd=0.1)]
    result = _compare(before, after)
    assert result["unchanged"] == ["OPP-1"]
    assert all(result[key] == [] for key in DELTAS)
    assert _compare(list(reversed(before)), list(reversed(after))) == result
    assert not any("line_changes" in key for key in result)
    renewal = pipeline.renewal_attention_for_rows([
        _line(row_id=1, product_sku="SAME", est_acv_usd=0.1,
              current_contract_end_date=REFERENCE),
        _line(row_id=2, product_sku="SAME", est_acv_usd=0.2,
              current_contract_end_date=REFERENCE),
    ], reference_date=REFERENCE, as_of=AS_OF)
    assert len(_cards(renewal)) == 1
    assert _cards(renewal)[0]["est_acv"] == {
        "total": 0.3, "coverage": "quantified", "lines_included": 2, "lines_excluded": 0,
    }


def test_partial_import_keeps_each_accounts_latest_snapshot(db_session, account):
    other = Customer(name="Synthetic H3 Partial Other")
    db_session.add(other)
    db_session.flush()
    first = add_pipeline_batch(db_session, [(account, [{
        "current_contract_end_date": REFERENCE, "est_acv_usd": 45,
    }])])
    before = imports.customer_pipeline(db_session, account.name)
    second = add_pipeline_batch(db_session, [(other, [{"est_acv_usd": 900}])])
    after = imports.customer_pipeline(db_session, account.name)
    assert after["import_id"] == first.id
    assert after["history"] == before["history"]
    assert after["rows"] == before["rows"]
    assert after["totals"] == before["totals"]
    assert {key: value for key, value in after["renewals"].items() if key != "as_of"} == {
        key: value for key, value in before["renewals"].items() if key != "as_of"
    }
    assert imports.customer_pipeline(db_session, other.name)["import_id"] == second.id


def test_history_is_grouped_scoped_newest_first_and_metadata_only(db_session, account):
    first = add_pipeline_batch(db_session, [(account, [
        {"opportunity_number": " OPP-1 "}, {"opportunity_number": "OPP-1"},
        {"opportunity_number": None}, {"opportunity_number": "  "},
    ])])
    second = add_pipeline_batch(db_session, [(account, [{"opportunity_number": "OPP-2"}])])
    db_session.expire_all()
    customer_id = account.id
    with _statements(db_session) as sql:
        history = pipeline.pipeline_snapshot_history(db_session, customer_id)
    assert len(sql) <= 2
    assert not any("file_data" in statement for statement in sql)
    assert history == [
        {"import_id": second.id, "source_file": "synthetic-pipeline.csv",
         "imported_at": "2026-10-25T22:20:01.123456Z", "imported_by": "admin",
         "line_count": 1, "opportunity_count": 1, "selected": True},
        {"import_id": first.id, "source_file": "synthetic-pipeline.csv",
         "imported_at": "2026-10-25T22:20:01.123456Z", "imported_by": "admin",
         "line_count": 4, "opportunity_count": 1, "selected": False},
    ]


def test_identical_reimport_has_zero_delta_claims(db_session, account):
    fields = [{"opportunity_number": "OPP-2", "est_acv_usd": 0.1},
              {"opportunity_number": "OPP-1", "est_acv_usd": 0.2}]
    first = add_pipeline_batch(db_session, [(account, fields)])
    add_pipeline_batch(db_session, [(account, fields)])
    result = imports.customer_pipeline(db_session, account.name, compare_with=first.id)
    comparison = result["comparison"]
    assert all(comparison[key] == [] for key in DELTAS)
    assert comparison["unchanged"] == ["OPP-1", "OPP-2"]
    assert not {"events", "tasks", "alerts"}.intersection(comparison)


def test_date_conflicts_remain_visible_and_suppress_stage_and_close_deltas():
    before = [_line(row_id=1, close_date=date(2026, 11, 1), est_acv_usd=10),
              _line(row_id=2, close_date=date(2026, 12, 1), est_acv_usd=20)]
    after = [_line(row_id=3, close_date=date(2027, 1, 1), opp_stage="Negotiate",
                   current_contract_end_date=REFERENCE, est_acv_usd=40),
             _line(row_id=4, close_date=date(2027, 2, 1), opp_stage="Negotiate",
                   current_contract_end_date=REFERENCE + timedelta(days=30), est_acv_usd=None)]
    result = _compare(before, after)
    assert result["stage_changes"] == result["close_date_changes"] == []
    assert result["ambiguity"] == [{
        "opportunity_number": "OPP-1",
        "from_conflicts": ["close_date: '2026-11-01', '2026-12-01'"],
        "to_conflicts": ["close_date: '2027-01-01', '2027-02-01'"],
        "note": "conflicting source values in a snapshot — stage/close deltas for it are suppressed (visible, not fabricated)",
    }]
    assert result["amount_changes"][0]["acv"] == {"from": 30.0, "to": 40.0, "delta": 10.0}
    renewal = pipeline.renewal_attention_for_rows(after, reference_date=REFERENCE, as_of=AS_OF)
    assert len(_cards(renewal)) == 1
    card = renewal["buckets"]["within_30"][0]
    assert card["renewal_date"] == "2026-10-27" and card["days"] == 0
    assert card["conflicting_end_dates"] == ["2026-10-27", "2026-11-26"]
    assert card["est_acv"]["coverage"] == "partial"


@pytest.mark.parametrize("days,bucket", [
    (-1, "overdue"), (0, "within_30"), (30, "within_30"),
    (31, "within_60"), (60, "within_60"), (61, "within_90"),
    (90, "within_90"), (91, "within_180"), (180, "within_180"), (181, "beyond_180"),
])
def test_exact_inclusive_bucket_boundaries(days, bucket):
    result = pipeline.renewal_attention_for_rows([
        _line(current_contract_end_date=REFERENCE + timedelta(days=days), net_new_vs_renewal="New"),
    ], reference_date=REFERENCE, as_of=AS_OF)
    assert result["reference_date"] == "2026-10-27"
    assert result["as_of"] == AS_OF
    assert result["calculation_version"] == "pipeline-renewal/1"
    assert result["counts"] == {key: int(key == bucket) for key in (*DATED, "beyond_180", "unknown_date")}
    if bucket == "beyond_180":
        assert result["buckets"]["beyond_180_count"] == 1
        assert _cards(result) == []
    else:
        assert result["buckets"][bucket][0]["days"] == days
        assert result["buckets"][bucket][0]["reported_renewal"] is False


def test_unknown_date_requires_reported_renewal_and_never_uses_close_or_original_end():
    rows = [_line("UNKNOWN", net_new_vs_renewal=" ReNeWaL ", close_date=REFERENCE,
                  contract_end_date=date(2025, 1, 1)),
            _line("NEW", row_id=2, net_new_vs_renewal="New", close_date=REFERENCE),
            _line(None, row_id=3, net_new_vs_renewal="Renewal", current_contract_end_date=REFERENCE)]
    result = pipeline.renewal_attention_for_rows(rows, reference_date=REFERENCE, as_of=AS_OF)
    assert result["counts"]["unknown_date"] == 1
    assert sum(result["counts"].values()) == 1
    card = result["buckets"]["unknown_date"][0]
    assert card["opportunity_number"] == "UNKNOWN"
    assert card["renewal_date"] is None and card["days"] is None
    assert card["original_contract_end"] == "2025-01-01"
    assert card["est_acv"]["total"] is None
    assert card["net_new_vs_renewal_values"] == [" ReNeWaL "]


def test_stage_close_amount_and_name_changes_are_independent_and_raw():
    before = [_line("ALL", opp_stage=" Discover ", close_date=date(2026, 11, 30),
                    opportunity_name=" Raw old ", est_acv_usd=1000, est_tcv_usd=None),
              _line("BLANK", row_id=2, opp_stage=None),
              _line("WON", row_id=3, opp_stage="Closed - Won"),
              _line("NAME", row_id=4, opportunity_name=" Raw name "),
              _line("EQUAL", row_id=5, opportunity_name=" Straße "),
              _line("NULLNAME", row_id=6)]
    after = [_line("ALL", row_id=10, opp_stage="Negotiate", close_date=date(2027, 1, 31),
                   opportunity_name=" Raw new ", est_acv_usd=1200, est_tcv_usd=50),
             _line("BLANK", row_id=20, opp_stage="Validate"),
             _line("WON", row_id=30, opp_stage="cLoSeD Lost"),
             _line("NAME", row_id=40, opportunity_name="Name expanded"),
             _line("EQUAL", row_id=50, opportunity_name="STRASSE"),
             _line("NULLNAME", row_id=60, opportunity_name="Added name")]
    result = _compare(before, after)
    stages = {entry["opportunity_number"]: entry for entry in result["stage_changes"]}
    assert stages["ALL"] == {
        "opportunity_number": "ALL", "from_stage": " Discover ", "to_stage": "Negotiate",
        "from_class": "open", "to_class": "open", "line_ids_from": [1], "line_ids_to": [10],
    }
    assert stages["BLANK"]["from_stage"] is None and stages["BLANK"]["from_class"] == "unknown"
    assert stages["WON"]["from_stage"] == "Closed - Won"
    assert stages["WON"]["to_stage"] == "cLoSeD Lost"
    assert (stages["WON"]["from_class"], stages["WON"]["to_class"]) == ("won", "lost")
    assert result["close_date_changes"] == [{
        "opportunity_number": "ALL", "from_close_date": "2026-11-30",
        "to_close_date": "2027-01-31", "slip_days": 62,
        "line_ids_from": [1], "line_ids_to": [10],
    }]
    assert result["amount_changes"] == [{
        "opportunity_number": "ALL", "acv": {"from": 1000.0, "to": 1200.0, "delta": 200.0},
        "tcv": {"from": None, "to": 50.0, "delta": None},
        "line_ids_from": [1], "line_ids_to": [10],
    }]
    assert result["name_changes"] == [
        {"opportunity_number": "ALL", "name_from": " Raw old ", "name_to": " Raw new ",
         "line_ids_from": [1], "line_ids_to": [10]},
        {"opportunity_number": "NAME", "name_from": " Raw name ", "name_to": "Name expanded",
         "line_ids_from": [4], "line_ids_to": [40]},
        {"opportunity_number": "NULLNAME", "name_from": None, "name_to": "Added name",
         "line_ids_from": [6], "line_ids_to": [60]},
    ]
    assert result["unchanged"] == ["EQUAL"]


def test_stage_conflicts_suppress_both_deltas_but_not_name_or_amount():
    result = _compare([
        _line(opp_stage="Discover", opportunity_name="Old", est_acv_usd=10),
        _line(row_id=2, opp_stage="Validate", opportunity_name="Old", est_acv_usd=10),
    ], [_line(row_id=3, opp_stage="Closed Lost", opportunity_name="New", est_acv_usd=30)])
    assert result["stage_changes"] == result["close_date_changes"] == []
    assert result["ambiguity"][0]["from_conflicts"] == ["stage: 'Discover', 'Validate'"]
    assert len(result["name_changes"]) == len(result["amount_changes"]) == 1
    assert result["unchanged"] == []


def test_observed_removed_reports_source_state_and_exact_honesty_notes():
    result = _compare([_line("REMOVED", opp_stage="Negotiate", est_acv_usd=None)], [])
    assert result["calculation_version"] == "pipeline-snapshot-compare/1"
    assert result["as_of"] == AS_OF
    assert result["notes"] == [
        "Observed-removed opportunities are absent from the later retained snapshot; this is not evidence of closed-lost, zero pipeline, or churn.",
        "No velocity or win rate is supported by snapshot observations alone.",
        "imported_at values are import times, not business effective dates.",
    ]
    assert result["observed_removed"] == [{
        "opportunity_number": "REMOVED", "opportunity_name": None,
        "stage_raw": "Negotiate", "stage_class": "open", "close_date": None,
        "est_acv_usd": None, "est_tcv_usd": None, "reported_renewal": False,
        "line_ids": [1], "line_source_rows": [1],
    }]
    for side, number in (("from", 1), ("to", 2)):
        assert result[side] == {
            "import_id": number, "source_file": f"synthetic-{number}.csv",
            "imported_at": "2026-10-25T12:00:00Z", "imported_by": "admin",
            "note": "imported_at is import time, not a business effective date",
        }


def test_zero_batch_account_is_honest_empty_and_cannot_compare(db_session, account):
    result = imports.customer_pipeline(db_session, account.name)
    assert result["history"] == []
    assert result["renewals"]["snapshot"] is None
    assert all(value == 0 for value in result["renewals"]["counts"].values())
    assert _cards(result["renewals"]) == []
    assert "comparison" not in result
    with pytest.raises(HTTPException) as error:
        imports.customer_pipeline(db_session, account.name, compare_with=999)
    assert error.value.status_code == 400
    assert pipeline.renewal_attention_for_rows([], reference_date=REFERENCE)["snapshot"] is None


@pytest.mark.parametrize("account_count", [1, 8])
def test_scoped_renewal_batch_and_rollup_agree_with_bounded_queries(db_session, account_count):
    accounts = [Customer(name=f"Synthetic H3 Scoped {index}") for index in range(account_count)]
    empty = Customer(name="Synthetic H3 No Snapshot")
    no_evidence = Customer(name="Synthetic H3 Snapshot Without Evidence")
    outsider = Customer(name="Synthetic H3 Outsider")
    db_session.add_all([*accounts, empty, no_evidence, outsider])
    db_session.flush()
    add_pipeline_batch(db_session, [
        *((customer, [
            {"opportunity_number": "DATED", "current_contract_end_date": REFERENCE,
             "est_acv_usd": 0.1},
            {"opportunity_number": "DATED", "current_contract_end_date": REFERENCE,
             "est_acv_usd": 0.2},
            {"opportunity_number": "UNKNOWN", "net_new_vs_renewal": "Renewal"},
            {"opportunity_number": "FAR", "current_contract_end_date": REFERENCE + timedelta(days=181),
             "est_acv_usd": 9999},
        ]) for customer in accounts),
        (no_evidence, [{"opportunity_number": "NEW", "net_new_vs_renewal": "New"}]),
        (outsider, [{"est_acv_usd": 999999, "current_contract_end_date": REFERENCE}]),
    ])
    ids = [customer.id for customer in [*accounts, empty, no_evidence]]
    with _statements(db_session) as sql:
        summaries = pipeline.renewal_attention_summaries_for(
            db_session, [*reversed(ids), ids[0]], reference_date=REFERENCE, as_of=AS_OF,
        )
    assert len(sql) <= 3
    assert not any("file_data" in statement for statement in sql)
    assert set(summaries) == set(ids)
    assert {summary["reference_date"] for summary in summaries.values()} == {"2026-10-27"}
    assert {summary["as_of"] for summary in summaries.values()} == {AS_OF}
    with _statements(db_session) as sql:
        rollup = pipeline.portfolio_renewal_rollup(
            db_session, [*ids, ids[0]], reference_date=REFERENCE, as_of=AS_OF,
        )
    assert len(sql) <= 4
    assert not any("file_data" in statement for statement in sql)
    customer_queries = [statement for statement in sql if "FROM customers" in statement]
    assert len(customer_queries) == 1
    assert "customers.name" in customer_queries[0] and "customers.description" not in customer_queries[0]
    assert rollup["accounts_scoped"] == len(ids)
    assert rollup["accounts_no_data"] == 1
    assert rollup["accounts_with_renewal_evidence"] == account_count
    assert rollup["counts"] == {
        key: sum(summary["counts"][key] for summary in summaries.values())
        for key in summaries[ids[0]]["counts"]
    }
    assert rollup["exposure"]["acv"] == {
        "total": float(account_count * 0.3), "coverage": "partial",
        "lines_included": account_count * 2, "lines_excluded": account_count,
    }
    assert rollup["exposure"]["tcv"] == {
        "total": None, "coverage": "all_unknown", "lines_included": 0,
        "lines_excluded": account_count * 3,
    }
    assert rollup["next_renewals"] == [
        {"customer_id": customer.id, "customer_name": customer.name, "opportunity_number": "DATED",
         "renewal_date": "2026-10-27", "days": 0}
        for customer in accounts
    ]
    assert "Outsider" not in str(rollup)
    assert all(summary["snapshot"] is not None for cid, summary in summaries.items() if cid != empty.id)


def test_rollup_next_renewals_are_capped_sorted_and_empty_scope_does_not_query(db_session, account):
    add_pipeline_batch(db_session, [(account, [
        {"opportunity_number": f"OPP-{index:02}", "current_contract_end_date": REFERENCE + timedelta(days=index)}
        for index in reversed(range(12))
    ])])
    result = pipeline.portfolio_renewal_rollup(db_session, [account.id], reference_date=REFERENCE)
    assert [row["opportunity_number"] for row in result["next_renewals"]] == [f"OPP-{i:02}" for i in range(10)]
    with _statements(db_session) as sql:
        assert pipeline.renewal_attention_summaries_for(db_session, []) == {}
        empty = pipeline.portfolio_renewal_rollup(db_session, [], reference_date=REFERENCE, as_of=AS_OF)
    assert sql == []
    assert empty == {
        "calculation_version": "pipeline-renewal/1", "as_of": AS_OF,
        "reference_date": "2026-10-27", "accounts_scoped": 0,
        "accounts_with_renewal_evidence": 0, "accounts_no_data": 0,
        "counts": {key: 0 for key in (*DATED, "beyond_180", "unknown_date")},
        "exposure": {key: {"total": None, "coverage": "no_data", "lines_included": 0, "lines_excluded": 0}
                     for key in ("acv", "tcv")}, "next_renewals": [],
    }


def test_portfolio_route_adds_renewals_once_after_auth_and_preserves_legacy_rows(
    client, db_session, monkeypatch,
):
    from backend.services import sales_access

    mine = Customer(name="Synthetic H3 Mine", vertical="Technology", branch="Synthetic Branch",
                    sales_area="Synthetic Area", primary_subsidiary="Synthetic Subsidiary")
    empty = Customer(name="Synthetic H3 Empty")
    outsider = Customer(name="Synthetic H3 Hidden")
    db_session.add_all([mine, empty, outsider])
    db_session.flush()
    rep = User(username="h3_portfolio_rep", email="h3-portfolio@test.local", hashed_password="unused",
               display_name="Synthetic Rep", sales_role="rep", is_admin=0, approved=1, is_active=1)
    db_session.add(rep)
    db_session.flush()
    db_session.add_all([CustomerUser(customer_id=customer.id, user_id=rep.id, role="member")
                        for customer in (mine, empty)])
    add_pipeline_batch(db_session, [(mine, [{
        "current_contract_end_date": REFERENCE, "est_acv_usd": 5000,
    }]), (outsider, [{"current_contract_end_date": REFERENCE, "est_acv_usd": 999999}])])
    db_session.commit()
    ids = sorted([mine.id, empty.id])
    original = pipeline.portfolio_renewal_rollup
    original_scope = sales_access.customer_scope
    calls = []

    def read(db, scoped):
        with _statements(db) as sql:
            result = original(db, scoped, reference_date=REFERENCE, as_of=AS_OF)
        calls.append((list(scoped), len(sql)))
        return result

    monkeypatch.setattr(pipeline, "portfolio_renewal_rollup", read)
    monkeypatch.setattr(sales_access, "customer_scope", lambda user, db: original_scope(user, db) | {outsider.id})
    headers = {"Authorization": f"Bearer {create_access_token({'sub': rep.username})}"}
    response = client.get("/api/account-impact/portfolio/", headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert calls == [(ids, 4)]
    assert "Hidden" not in response.text
    rows = {row["customer_id"]: row for row in result["customers"]}
    assert {key: value for key, value in rows[mine.id].items() if key != "renewals"} == {
        "customer_id": mine.id, "customer_name": mine.name, "vertical": "Technology",
        "branch": "Synthetic Branch", "sales_area": "Synthetic Area",
        "primary_subsidiary": "Synthetic Subsidiary", "primary_rep": None,
        "can_manage_customer": False, "can_score": True,
        "coverage": "not_quantified", "total_impact": None,
        "pipeline": {"acv": 5000.0, "tcv": None, "coverage": "quantified"},
    }
    assert rows[mine.id]["renewals"] == {
        "counts": {key: int(key == "within_30") for key in (*DATED, "beyond_180", "unknown_date")},
        "acv_exposure": 5000.0, "next_renewal": "2026-10-27",
    }
    assert rows[empty.id]["renewals"] == {
        "counts": {key: 0 for key in (*DATED, "beyond_180", "unknown_date")},
        "acv_exposure": None, "next_renewal": None,
    }
    assert result["renewals"]["counts"] == rows[mine.id]["renewals"]["counts"]
    assert result["renewals"]["exposure"]["acv"]["total"] == 5000.0


def test_added_and_removed_conflicts_are_also_visible():
    result = _compare([
        _line("REMOVED", row_id=1, opp_stage="Discover"),
        _line("REMOVED", row_id=2, opp_stage="Validate"),
    ], [
        _line("ADDED", row_id=3, close_date=date(2026, 11, 1)),
        _line("ADDED", row_id=4, close_date=date(2026, 12, 1)),
    ])
    assert [entry["opportunity_number"] for entry in result["ambiguity"]] == ["ADDED", "REMOVED"]
    assert result["ambiguity"][0]["from_conflicts"] == []
    assert result["ambiguity"][0]["to_conflicts"] == ["close_date: '2026-11-01', '2026-12-01'"]
    assert result["ambiguity"][1]["from_conflicts"] == ["stage: 'Discover', 'Validate'"]
    assert result["ambiguity"][1]["to_conflicts"] == []
    assert result["added"][0]["stage_class"] == "unknown"
    assert result["observed_removed"][0]["stage_class"] == "unknown"


def test_portfolio_money_rounds_raw_lines_only_at_aggregate_boundary(db_session, account):
    add_pipeline_batch(db_session, [(account, [
        {"opportunity_number": "A", "current_contract_end_date": REFERENCE, "est_acv_usd": 0.005},
        {"opportunity_number": "B", "current_contract_end_date": REFERENCE, "est_acv_usd": 0.005},
    ])])
    result = pipeline.portfolio_renewal_rollup(db_session, [account.id], reference_date=REFERENCE)
    assert result["exposure"]["acv"]["total"] == 0.01
    assert result.account_summaries[account.id]["acv_exposure"] == 0.01
