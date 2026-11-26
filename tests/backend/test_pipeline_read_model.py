"""Synthetic H1 contracts: snapshots, opportunity grain, money and bounded reads."""

from datetime import date

import pytest
from backend.models.intelligence_import import PartnerPipeline
from backend.models.use_case import Customer
from backend.services import intelligence_import_service as imports
from backend.services import pipeline_read_model as pipeline
from sqlalchemy import event

from tests.backend._shared import add_pipeline_batch


@pytest.fixture()
def account(db_session):
    customer = Customer(name="Synthetic Pipeline Account")
    db_session.add(customer)
    db_session.flush()
    return customer


@pytest.mark.parametrize("raw,expected", [
    ("Discover", "open"), (" Validate ", "open"), ("PROPOSE", "open"),
    ("Negotiate", "open"), ("Closed Lost", "lost"), ("Closed - Won", "won"),
    (None, "unknown"), ("", "unknown"), ("  ", "unknown"),
    ("Cancelled", "unknown"), ("Negotiation", "unknown"), ("won", "unknown"),
])
def test_documented_stage_mapping(raw, expected):
    assert pipeline.stage_class(raw) == expected


def test_two_skus_are_one_opportunity_and_two_decimal_line_amounts(db_session, account):
    batch = add_pipeline_batch(db_session, [(account, [
        {"opportunity_number": " OPP-1 ", "product_sku": "SKU-A", "est_acv_usd": 0.1,
         "est_tcv_usd": 100.01, "forecast_category": "Commit", "fiscal_quarter": "Q4",
         "net_new_vs_renewal": "New"},
        {"product_sku": "SKU-B", "est_acv_usd": 0.2, "est_tcv_usd": 200.02,
         "forecast_category": "Pipeline", "fiscal_quarter": "Q4", "net_new_vs_renewal": "Renewal"},
    ])])
    summary = pipeline.pipeline_summary_for(db_session, account.id)
    assert summary["calculation_version"] == "pipeline-read-model/1"
    assert summary["as_of"].endswith("Z")
    assert summary["source"] == {
        "source_type": "partner_pipeline", "import_id": batch.id,
        "source_file": "synthetic-pipeline.csv", "imported_at": "2026-10-25T22:20:01.123456Z",
        "imported_by": "admin", "note": "imported_at is import time, not a business effective date",
    }
    assert summary["grain"] == {
        "line_count": 2, "opportunity_count": 1, "unidentified_lines": 0,
        "ambiguous_opportunities": [],
    }
    assert summary["amounts"] == {
        "acv": {"total": 0.3, "coverage": "quantified", "lines_included": 2, "lines_excluded": 0},
        "tcv": {"total": 300.03, "coverage": "quantified", "lines_included": 2, "lines_excluded": 0},
    }
    assert summary["stages"] == {
        "open": 1, "won": 0, "lost": 0, "unknown": 0, "unknown_stage_values": [],
    }
    assert summary["forecast_categories"] == {"Commit": 1, "Pipeline": 1}
    assert summary["reporting"] == {
        "fiscal_quarters": {"Q4": 2}, "net_new_vs_renewal": {"New": 1, "Renewal": 1},
    }
    assert summary["precision_note"] == (
        "amounts are stored as float from the source CSV; totals are computed with Decimal "
        "over stored values and rounded at the boundary; the original file is retained "
        "on the import row as evidence"
    )
    result = imports.customer_pipeline(db_session, account.name)
    assert result["totals"] == {
        "line_count": 2, "deal_count": 1, "open_deals": 1, "unknown_deals": 0,
        "growth": 0, "risk": 0, "est_acv_total": 0.3, "est_tcv_total": 300.03,
        "amount_coverage": {"acv": "quantified", "tcv": "quantified"},
    }
    assert len(result["rows"]) == 2
    assert result["summary"]["amounts"] == summary["amounts"]
    assert "total" not in summary and "total" not in summary["amounts"]


def test_unidentified_and_identical_lines_are_never_deduplicated(db_session, account):
    add_pipeline_batch(db_session, [(account, [
        {"est_acv_usd": 10.01}, {"est_acv_usd": 10.01},
        {"opportunity_number": "OPP-2", "est_acv_usd": 20.02, "opp_stage": "Closed Lost"},
        {"opportunity_number": None, "est_acv_usd": 30.03},
        {"opportunity_number": "  ", "est_acv_usd": 40.04},
    ])])
    summary = pipeline.pipeline_summary_for(db_session, account.id)
    assert summary["grain"] == {
        "line_count": 5, "opportunity_count": 2, "unidentified_lines": 2,
        "ambiguous_opportunities": [],
    }
    assert summary["amounts"]["acv"]["total"] == 110.11
    assert summary["stages"]["open"] == 1
    assert summary["stages"]["lost"] == 1


def test_unknown_raw_stages_are_visible_and_blank_is_never_open(db_session, account):
    values = [None, " ", "Cancelled", "Cancelled", " Strange ", "Closed - Won", "Closed Lost"]
    add_pipeline_batch(db_session, [(account, [
        {"opportunity_number": f"OPP-{i}", "opp_stage": value}
        for i, value in enumerate(values)
    ])])
    summary = pipeline.pipeline_summary_for(db_session, account.id)
    assert summary["stages"] == {
        "open": 0, "won": 1, "lost": 1, "unknown": 5,
        "unknown_stage_values": [" Strange ", "Cancelled"],
    }
    assert [row["opp_stage"] for row in imports.customer_pipeline(db_session, account.name)["rows"]] == values


@pytest.mark.parametrize("second,conflicts", [
    ({"opp_stage": "Validate"}, ["stage: 'Discover', 'Validate'"]),
    ({"close_date": date(2026, 12, 1)}, ["close_date: '2026-11-01', '2026-12-01'"]),
    ({"opp_stage": "Closed Lost", "close_date": None},
     ["stage: 'Closed Lost', 'Discover'", "close_date: None, '2026-11-01'"]),
])
def test_conflicts_make_one_opportunity_unknown(db_session, account, second, conflicts):
    add_pipeline_batch(db_session, [(account, [
        {"close_date": date(2026, 11, 1), "est_acv_usd": 10},
        {"close_date": date(2026, 11, 1), "est_acv_usd": 20, **second},
    ])])
    summary = pipeline.pipeline_summary_for(db_session, account.id)
    assert summary["grain"]["opportunity_count"] == 1
    assert summary["grain"]["ambiguous_opportunities"] == [
        {"opportunity_number": "OPP-1", "conflicts": conflicts},
    ]
    assert summary["stages"] == {
        "open": 0, "won": 0, "lost": 0, "unknown": 1, "unknown_stage_values": [],
    }
    assert summary["amounts"]["acv"]["total"] == 30.0


@pytest.mark.parametrize("values,coverage,total,included,excluded", [
    ([], "no_data", None, 0, 0),
    ([None, None], "all_unknown", None, 0, 2),
    ([None, 0.1, 0.2], "partial", 0.3, 2, 1),
    ([0.0, 0.0], "recorded_zero", 0.0, 2, 0),
    ([1.25, -1.25], "recorded_zero", 0.0, 2, 0),
    ([0.1, 0.2], "quantified", 0.3, 2, 0),
    ([1.234, 2.344], "quantified", 3.58, 2, 0),
])
def test_amount_coverage(db_session, account, values, coverage, total, included, excluded):
    if values:
        add_pipeline_batch(db_session, [(account, [{"est_acv_usd": value} for value in values])])
    summary = pipeline.pipeline_summary_for(db_session, account.id)
    assert summary["amounts"]["acv"] == {
        "total": total, "coverage": coverage, "lines_included": included, "lines_excluded": excluded,
    }
    assert summary["amounts"]["tcv"]["total"] is None
    if not values:
        assert summary["source"] is None
        assert summary["grain"] == {
            "line_count": 0, "opportunity_count": 0, "unidentified_lines": 0,
            "ambiguous_opportunities": [],
        }
        assert summary["stages"] == {
            "open": 0, "won": 0, "lost": 0, "unknown": 0, "unknown_stage_values": [],
        }
        assert summary["forecast_categories"] == {}
        assert summary["reporting"] == {"fiscal_quarters": {}, "net_new_vs_renewal": {}}
        assert summary["currency_codes"] == [] and summary["currency_note"] is None


@pytest.mark.parametrize("code,note_count,codes", [
    ("USD", 0, ["USD"]), ("EUR", 1, ["EUR", "USD"]),
    (None, 1, ["USD"]), ("  ", 1, ["USD"]),
])
def test_currency_codes_never_convert_or_relabel_usd(db_session, account, code, note_count, codes):
    add_pipeline_batch(db_session, [(account, [
        {"est_acv_usd": 10, "est_tcv_usd": 100},
        {"est_acv_usd": 20, "est_tcv_usd": 200, "currency_code": code},
    ])])
    summary = pipeline.pipeline_summary_for(db_session, account.id)
    assert summary["amounts"]["acv"]["total"] == 30.0
    assert summary["amounts"]["tcv"]["total"] == 300.0
    assert summary["currency_codes"] == codes
    assert summary["currency_basis"] == "USD (source-labelled line estimates; never converted)"
    expected_note = (
        f"{note_count} line(s) carry a non-USD/blank opportunity currency code; "
        "amounts remain source-labelled USD"
    ) if note_count else None
    assert summary["currency_note"] == expected_note


def test_latest_applicable_batch_and_delete_fallback(db_session, account):
    first = add_pipeline_batch(db_session, [(account, [{"est_acv_usd": 10}])])
    second = add_pipeline_batch(db_session, [(account, [{"est_acv_usd": 20}])])
    other = Customer(name="Synthetic Other Snapshot")
    db_session.add(other)
    db_session.flush()
    add_pipeline_batch(db_session, [(other, [{"est_acv_usd": 999}])])
    db_session.commit()
    summary = pipeline.pipeline_summary_for(db_session, account.id)
    assert summary["source"]["import_id"] == second.id
    assert summary["amounts"]["acv"]["total"] == 20.0
    imports.delete_import(db_session, second.id, {"username": "admin"})
    summary = pipeline.pipeline_summary_for(db_session, account.id)
    assert summary["source"]["import_id"] == first.id
    assert summary["amounts"]["acv"]["total"] == 10.0


@pytest.mark.parametrize("account_count", [1, 8])
def test_batched_scope_has_at_most_three_queries(db_session, account_count):
    customers = [Customer(name=f"Synthetic Batch Account {i}") for i in range(account_count + 1)]
    db_session.add_all(customers)
    db_session.flush()
    add_pipeline_batch(db_session, [(customer, [{"est_acv_usd": i + 0.1}])
                                    for i, customer in enumerate(customers)])
    ids = [customer.id for customer in customers[:-1]]
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", record)
    try:
        summaries = pipeline.pipeline_summaries_for(db_session, [*reversed(ids), ids[0]])
        assert list(summaries) == ids
        assert len(statements) == 3
        assert "file_data" not in statements[-1]
        assert summaries[ids[0]]["grain"]["opportunity_count"] == 1
        statements.clear()
        assert pipeline.pipeline_summaries_for(db_session, []) == {}
        assert statements == []
    finally:
        event.remove(db_session.bind, "before_cursor_execute", record)


def test_single_account_delegates_to_batched_core(db_session, account, monkeypatch):
    calls = []

    def summaries(db, ids):
        calls.append((db, ids))
        return {account.id: {"sentinel": True}}

    monkeypatch.setattr(pipeline, "pipeline_summaries_for", summaries)
    assert pipeline.pipeline_summary_for(db_session, account.id) == {"sentinel": True}
    assert calls == [(db_session, [account.id])]


def test_selected_batch_is_stable_if_a_new_snapshot_arrives_between_reads(db_session, account):
    first = add_pipeline_batch(db_session, [(account, [{"est_acv_usd": 10}])])
    incoming = add_pipeline_batch(db_session, [(account, [])])
    incoming.total_rows = incoming.matched_rows = 1
    db_session.flush()
    # A source batch is published after batch selection but before line loading.
    published = False

    def publish(conn, cursor, statement, parameters, context, executemany):
        nonlocal published
        if statement.startswith("SELECT partner_pipeline.id") and not published:
            published = True
            conn.execute(PartnerPipeline.__table__.insert().values(
                import_id=incoming.id, customer_id=account.id,
                customer_account_name=account.name, opportunity_number="OPP-1",
                opp_stage="Discover", est_acv_usd=999, currency_code="USD", source_row=1,
            ))

    event.listen(db_session.bind, "before_cursor_execute", publish)
    try:
        summary = pipeline.pipeline_summary_for(db_session, account.id)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", publish)
    assert published
    assert summary["source"]["import_id"] == first.id
    assert summary["amounts"]["acv"]["total"] == 10.0
    subsequent = pipeline.pipeline_summary_for(db_session, account.id)
    assert subsequent["source"]["import_id"] == incoming.id
    assert subsequent["amounts"]["acv"]["total"] == 999.0
