"""Synthetic NetSuite reports; real customer exports are never test fixtures."""

import csv
import io
import json
from datetime import date
from pathlib import Path

import pytest
from backend.models.use_case import Customer
from backend.services import netsuite_import_service as service
from backend.services.customer_match import CustomerMatcher
from fastapi import HTTPException
from openpyxl import Workbook

HEADERS = ["End Customer Name", "Subscription ID", "Subscription Name",
           "Subscription Expiration Date", "Detail Type", "Quantity",
           "CUSTOMER_DETAIL_QTY_UOM", "Contract Period", "Contract Period Type",
           "Invoice Date", "SUBSCRIPTION_STATUS"]
MONEY_HEADERS = ["Price", "Cost", "Total", "Tax", "Discount", "Rate", "Currency", "Recalc",
                 "Custom Account ID", "Customer Account ID", "Description", "Reseller Resource MPN"]


def report(rows, extension="csv", headers=None, preamble=True):
    values = ([["Synthetic report"], []] if preamble else []) + [headers or HEADERS] + rows
    if extension == "csv":
        output = io.StringIO(newline="")
        csv.writer(output).writerows(values)
        return output.getvalue().encode("utf-8-sig")
    book = Workbook()
    for row in values:
        book.active.append(row)
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def line(customer="Synthetic Customer", subscription="sub-1", product="Microsoft 365 Business (NCE Annual)",
         end="2027-09-30", detail="Subscription", quantity=5, uom="License", term="12",
         term_type="Months", invoice="2026-09-30", status="Active"):
    return [customer, subscription, product, end, detail, quantity, uom, term, term_type, invoice, status]


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_parser_allowlist_and_dates(extension, caplog):
    secrets = [f"FORBIDDEN-VALUE-{i}" for i in range(len(MONEY_HEADERS))]
    data = report([line() + secrets + ["Original observation"]], extension,
                  [h + " " for h in HEADERS] + MONEY_HEADERS + ["Notes"])
    rows = service.parse(data, "synthetic." + extension)
    assert len(rows) == 1 and rows[0]["source_row"] == 4
    assert rows[0]["invoice_date"] == "2026-09-30"
    assert rows[0]["notes"] == "Original observation"
    assert rows[0]["customer_name"] == "Synthetic Customer"
    serialized = json.dumps(rows) + caplog.text
    assert all(value not in serialized for value in secrets)
    assert all(header not in rows[0] for header in MONEY_HEADERS)


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_duplicate_headers_rejected_without_echo(extension):
    with pytest.raises(HTTPException) as caught:
        service.parse(report([line() + ["PRIVATE"]], extension, HEADERS + [" Quantity "]),
                      "synthetic." + extension)
    assert caught.value.status_code == 422
    assert "PRIVATE" not in caught.value.detail


@pytest.mark.parametrize("data,filename", [(b"bad", "bad.xlsx"), (b"\xff", "bad.csv"),
                                          (b"", "empty.csv"), (b"bad", "bad.xls")])
def test_invalid_input(data, filename):
    with pytest.raises(HTTPException):
        service.parse(data, filename)


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_bounds(extension, monkeypatch):
    monkeypatch.setattr(service, "MAX_ROWS", 1)
    with pytest.raises(HTTPException) as caught:
        service.parse(report([line(), line(subscription="sub-2")], extension), "test." + extension)
    assert caught.value.status_code == 422


def test_workbook_expansion_limit(monkeypatch):
    monkeypatch.setattr(service, "MAX_UNCOMPRESSED", 1)
    with pytest.raises(HTTPException) as caught:
        service.parse(report([line()], "xlsx"), "test.xlsx")
    assert caught.value.status_code == 413


def test_cells_missing_customers_and_optional_notes():
    rows = service.parse(report([line(customer=""), line(quantity="#REF!") + ["Keep verbatim  "]],
                                headers=HEADERS + ["Memo"]), "test.csv")
    assert rows[0]["customer_name"] is None
    assert rows[1]["quantity"] is None
    assert rows[1]["notes"] == "Keep verbatim  "


def test_reduction_latest_line_seats_and_consumption(db_session):
    customer = Customer(name="Synthetic Customer")
    db_session.add(customer)
    db_session.flush()
    data = report([
        line(quantity=99, invoice="2026-08-31"),
        line(quantity=8),
        line(quantity=-3, detail="Refund", invoice="2026-10-01"),
        line(subscription="sub-2", quantity=2),
        line(subscription="azure-1", product="Private tenant Azure plan", quantity=123.4,
             uom="Hours", detail="Resource Overusage"),
        line(subscription="azure-2", product="Azure different tenant", quantity=999,
             detail="Resource Overusage"),
    ])
    result = service.reduce_products(service.parse(data, "test.csv"), CustomerMatcher(db_session),
                                     import_id=42)
    assert len(result["matched_rows"]) == 6 and not result["skipped"]
    products = {product["name"]: product for product in result["products"]}
    licensed = products["Microsoft 365 Business"]
    assert licensed["quantity"] == 10
    assert licensed["category"] == "software" and licensed["deployment_model"] == "saas"
    assert licensed["vendor"] == "Microsoft" and licensed["source"] == "NetSuite import #42"
    assert licensed["date_observed"] == "2026-10-01"
    assert licensed["verification_state"] == "verified"
    assert licensed["support_state"] == "under_support"
    assert "2027-09-30" in licensed["notes"]
    assert "quantity" not in licensed["notes"].lower()
    assert "end_of_support_date" not in licensed
    cloud = products["Microsoft Azure (consumption)"]
    assert cloud["quantity"] is None and cloud["deployment_model"] == "public_cloud"
    assert "tenant" not in json.dumps(result["products"]).lower()


@pytest.mark.parametrize("quantity,uom,status,expected", [
    (3.5, "License", "Active", None), (5, "Hours", "Active", None),
    (5, "License", "Terminated", None), (-5, "License", "Active", None),
    (0, "Seats", "Active", 0), (5, "unknown", "Active", None),
])
def test_conservative_quantity(db_session, quantity, uom, status, expected):
    customer = Customer(name="Synthetic Customer")
    db_session.add(customer)
    db_session.flush()
    rows = service.parse(report([line(quantity=quantity, uom=uom, status=status)]), "test.csv")
    product = service.reduce_products(rows, CustomerMatcher(db_session))["products"][0]
    assert product["quantity"] == expected
    assert product["support_state"] == ("under_support" if status == "Active" else None)


def test_reduction_scope_unknown_and_missing_fields(db_session):
    customer = Customer(name="Synthetic Customer")
    outside = Customer(name="Synthetic Outside")
    db_session.add_all([customer, outside])
    db_session.flush()
    rows = service.parse(report([
        line(product="Unclassified Widget", uom="unknown"), line(customer=outside.name), line(customer="Missing"),
        line(customer=""), line(subscription=""), line(product=""),
        line(subscription="unknown-cloud", product="Private tenant", detail="Resource Overusage"),
    ]), "test.csv")
    result = service.reduce_products(rows, CustomerMatcher(db_session), scope={customer.id})
    assert len(result["products"]) == 1 and len(result["skipped"]) == 6
    assert all(row.get("suggestion") is None for row in result["skipped"])
    product = result["products"][0]
    assert product["vendor"] is None and product["category"] is None
    assert product["deployment_model"] is None


def test_date_conversion_and_invalid_date():
    rows = service.parse(report([line(invoice=date(2026, 9, 30))], "xlsx"), "test.xlsx")
    assert rows[0]["invoice_date"] == "2026-09-30"
    rows = service.parse(report([line(invoice="09/30/2026")]), "test.csv")
    assert rows[0]["invoice_date"] == "2026-09-30"
    with pytest.raises(HTTPException):
        service.parse(report([line(invoice="not a date")]), "test.csv")


def test_latest_ties_adjustments_and_unknown_active_totals(db_session):
    db_session.add(Customer(name="Synthetic Customer"))
    db_session.flush()
    matcher = CustomerMatcher(db_session)
    rows = service.parse(report([line(quantity=2), line(quantity=7),
                                 line(quantity=-1, detail="Resource Downgrade"),
                                 line(subscription="other", quantity=3.5)]), "test.csv")
    result = service.reduce_products(rows, matcher)
    assert result["products"][0]["quantity"] is None
    rows = [row for row in rows if row["subscription_id"] != "other"]
    assert service.reduce_products(rows, matcher)["products"][0]["quantity"] == 7


def test_terminated_subscriptions_do_not_invalidate_active_seat_total(db_session):
    db_session.add(Customer(name="Synthetic Customer"))
    db_session.flush()
    rows = service.parse(report([line(quantity=4),
                                 line(subscription="ended", quantity=12, status="Terminated")]), "test.csv")
    result = service.reduce_products(rows, CustomerMatcher(db_session))
    assert result["products"][0]["quantity"] == 4


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_column_limit_and_missing_headers(extension, monkeypatch):
    data = report([line()], extension)
    monkeypatch.setattr(service, "MAX_COLUMNS", 3)
    with pytest.raises(HTTPException) as caught:
        service.parse(data, "test." + extension)
    assert caught.value.status_code == 422
    monkeypatch.setattr(service, "MAX_COLUMNS", 200)
    with pytest.raises(HTTPException):
        service.parse(report([["value"]], extension, ["Other column"]), "test." + extension)


def test_multiple_workbook_reports_rejected():
    book = Workbook()
    for sheet in (book.active, book.create_sheet("Second")):
        sheet.append(HEADERS)
        sheet.append(line())
    output = io.BytesIO()
    book.save(output)
    book.close()
    with pytest.raises(HTTPException) as caught:
        service.parse(output.getvalue(), "test.xlsx")
    assert caught.value.status_code == 422


@pytest.mark.asyncio
async def test_upload_reader_is_bounded(monkeypatch):
    from starlette.datastructures import UploadFile

    from backend import upload_size

    monkeypatch.setattr(upload_size, "MAX_UPLOAD_BYTES", 10)
    upload = UploadFile(filename="test.csv", file=io.BytesIO(report([line()])))
    with pytest.raises(HTTPException) as caught:
        await service.parse_upload(upload)
    assert caught.value.status_code == 413


def test_reduction_never_writes_customer_or_alias(db_session):
    from backend.models.customer_alias import CustomerAlias

    db_session.add(Customer(name="Synthetic Customer"))
    db_session.flush()
    before = (db_session.query(Customer).count(), db_session.query(CustomerAlias).count())
    rows = service.parse(report([line(customer="Synthetic Customer Inc"), line(customer="No Match")]), "test.csv")
    result = service.reduce_products(rows, CustomerMatcher(db_session))
    assert not result["products"]
    assert result["skipped"][0]["suggestion"]["customer_name"] == "Synthetic Customer"
    assert before == (db_session.query(Customer).count(), db_session.query(CustomerAlias).count())


@pytest.mark.parametrize("layout", ["csv", "xlsx"])
@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_full_layout_every_ignored_column_is_discarded(layout, extension, db_session, caplog):
    # Only public column names were taken from the source layouts; all values
    # below are invented. No source export is read at test runtime.
    layouts = json.loads((Path(__file__).parent / "fixtures" / "netsuite_headers.json").read_text())
    headers = layouts[layout]
    allowed = dict(zip(HEADERS, line(), strict=True))
    sentinels = []
    values = []
    for index, header in enumerate(headers):
        if header.strip() in allowed:
            values.append(allowed[header.strip()])
        else:
            sentinel = f"DO-NOT-RETAIN-{index}-987654321"
            sentinels.append(sentinel)
            values.append(sentinel)
    db_session.add(Customer(name="Synthetic Customer"))
    db_session.flush()
    rows = service.parse(report([values], extension, headers), "synthetic." + extension)
    result = service.reduce_products(rows, CustomerMatcher(db_session), import_id=7)
    serialized = json.dumps({"parsed": rows, "reduced": result}) + caplog.text
    assert all(value not in serialized for value in sentinels)
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    assert len(result["products"]) == 1


def test_unknown_vendor_can_still_have_evidenced_licensed_seats(db_session):
    db_session.add(Customer(name="Synthetic Customer"))
    db_session.flush()
    rows = service.parse(report([line(product="Unfamiliar Software", quantity=6)]), "test.csv")
    product = service.reduce_products(rows, CustomerMatcher(db_session))["products"][0]
    assert product["vendor"] is None
    assert product["quantity"] == 6 and product["category"] == "software"


def test_reduction_alias_and_customer_subscription_isolation(db_session):
    from backend.models.customer_alias import CustomerAlias

    first, second = Customer(name="Synthetic Customer"), Customer(name="Synthetic Second")
    db_session.add_all([first, second])
    db_session.flush()
    db_session.add(CustomerAlias(customer_id=first.id, alias="Synthetic Alias", alias_norm="synthetic alias"))
    db_session.flush()
    rows = service.parse(report([line(customer="SYNTHETIC ALIAS", quantity=2),
                                 line(customer=second.name, quantity=8)]), "test.csv")
    result = service.reduce_products(rows, CustomerMatcher(db_session))
    assert {p["customer_id"]: p["quantity"] for p in result["products"]} == {first.id: 2, second.id: 8}
    assert result["matched_rows"][0]["matched_by"] == "alias"


def test_aws_consumption_and_missing_date_order(db_session):
    db_session.add(Customer(name="Synthetic Customer"))
    db_session.flush()
    rows = service.parse(report([line(product="AWS private tenant plan", detail="Resource Overusage"),
                                 line(product="Microsoft 365 - Annual", subscription="licensed", quantity=4),
                                 line(product="Microsoft 365 - Monthly", subscription="licensed", quantity=88,
                                      invoice="")]), "test.csv")
    products = service.reduce_products(rows, CustomerMatcher(db_session))["products"]
    assert products[0]["name"] == "AWS (consumption)" and products[0]["vendor"] == "AWS"
    assert products[0]["quantity"] is None
    assert products[1]["name"] == "Microsoft 365" and products[1]["quantity"] == 4


def test_zero_and_thousands_quantity_and_cell_errors():
    rows = service.parse(report([line(quantity="1,234"), line(quantity="NaN"),
                                 line(quantity="1,5"), line(quantity=0), line(end="#N/A")]), "test.csv")
    assert [r["quantity"] for r in rows] == ["1234", None, None, "0", "5"]
    assert rows[-1]["term_end"] is None
