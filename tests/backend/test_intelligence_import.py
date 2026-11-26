"""Intelligence import contract: parsing, isolation, transactions and lifecycle."""

import csv
import hashlib
import io
import json
from datetime import date
from urllib.parse import quote

import pytest
from backend.models.collaboration import AuditLog
from backend.models.customer_knowledge import CustomerKnowledge, CustomerKnowledgeItem
from backend.models.customer_technology import CustomerTechnology
from backend.models.intelligence_import import IntelligenceImport, PartnerPipeline
from backend.models.use_case import Customer, CustomerUser, User
from backend.services import intelligence_import_service as service
from backend.services.customer_knowledge_service import create_customer_knowledge

from tests.backend.common import _headers

BASE = "/api/intelligence-import/"
HEADER = [
    "Customer Account", "Opportunity Name", "Opp Stage", "Est. ACV Line Amount (USD)",
    "Product Offering Group", "Close Date", "Partner Account", "FLAG - Growth / Risk",
    "Opportunity Number", "Est. TCV Line Amount (USD)", "Opportunity Currency Code",
    "Opportunity Forecast Category", "Net New Vs Renewal", "Route to Market",
    "Opportunity Channel", "Partner Tier", "Product SKU", "Product Description",
    "Original Contract Start Date", "Original Contract End Date", "Current Contract Start Date",
    "Current Contract End Date", "Fiscal Quarter", "Deal Registration Approval Status",
    "Opportunity Create Date", "Ignored Extra Column",
]


def _csv(rows, header=HEADER):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def _row(account="ALPHA  CORP", **overrides):
    row = {
        "Customer Account": account, "Opportunity Name": " Platform | expansion ",
        "Opp Stage": " Negotiation ", "Est. ACV Line Amount (USD)": "$1,234.50",
        "Est. TCV Line Amount (USD)": "$3,000", "Product Offering Group": "RHEL",
        "Close Date": "2026-10-30", "Partner Account": " Partner One ",
        "FLAG - Growth / Risk": "growth", "Opportunity Number": " OPP-1 ",
        "Opportunity Currency Code": " USD ", "Opportunity Forecast Category": " Commit ",
        "Net New Vs Renewal": " Net New ", "Route to Market": " Indirect ",
        "Opportunity Channel": " Reseller ", "Partner Tier": " Premier ",
        "Product SKU": " SKU-1 ", "Product Description": " A description ",
        "Original Contract Start Date": "Oct 1, 2025", "Original Contract End Date": "bad date",
        "Current Contract Start Date": "2025-11-01", "Current Contract End Date": "Oct 31, 2026",
        "Fiscal Quarter": " Q1 ", "Deal Registration Approval Status": " Approved ",
        "Opportunity Create Date": "Jan 15, 2025", "Ignored Extra Column": "ignored",
    }
    row.update(overrides)
    return row


@pytest.fixture()
def world(db_session):
    alpha = Customer(name="Alpha Corp")
    beta = Customer(name="Beta, Inc.")
    empty = Customer(name="Empty Customer")
    db_session.add_all([alpha, beta, empty])
    db_session.commit()
    return {"alpha": alpha, "beta": beta, "empty": empty}


@pytest.fixture()
def report():
    return _csv([
        _row(),
        _row("alpha corp", **{
            "Opportunity Name": "Renewal", "Opportunity Number": "OPP-2",
            "Opp Stage": "cLoSeD Won", "Est. ACV Line Amount (USD)": "NaN",
            "Est. TCV Line Amount (USD)": "", "Close Date": "Oct 31, 2026",
            "FLAG - Growth / Risk": "risk", "Product Offering Group": "OPENSHIFT",
            "Net New Vs Renewal": "Renewal",
        }),
        _row("bETA, iNC.", **{"Close Date": "unparseable", "Est. ACV Line Amount (USD)": ""}),
        _row("Unmatched Account"), _row("   "),
    ])


def _user(db, role, *, grants=(), legacy_role="user"):
    user = User(
        username=f"import_{role}", email=f"import_{role}@test.local", hashed_password="unused",
        display_name=role, department="Sales", is_admin=0, approved=1, is_active=1,
        sales_role=role, role=legacy_role,
    )
    db.add(user)
    db.flush()
    for customer in grants:
        db.add(CustomerUser(user_id=user.id, customer_id=customer.id, role="member"))
    db.commit()
    return user


def _upload(client, data, headers=None, filename="pipeline.csv"):
    return client.post(BASE, headers=headers if headers is not None else _headers(),
                       files={"file": (filename, data, "text/csv")})


def _pipeline(client, customer, headers=None):
    return client.get(f"/api/customers/{quote(customer.name, safe='')}/pipeline/",
                      headers=headers if headers is not None else _headers())


def test_upload_parses_rows_and_creates_ready_account_documents(client, db_session, world, report):
    result = _upload(client, report)
    assert result.status_code == 200, result.text
    body = result.json()
    import_id = body["import_id"]
    assert {key: body[key] for key in (
        "total_rows", "matched_accounts", "matched_rows", "unmatched_accounts",
    )} == {"total_rows": 5, "matched_accounts": 2, "matched_rows": 3, "unmatched_accounts": 2}
    assert body["file_sha256"] == hashlib.sha256(report).hexdigest()
    assert body["created_at"].endswith("+00:00")
    assert body["imported_by"] == "admin"
    assert body["unmatched"] == [
        {"account_name": "(blank)", "row_count": 1, "reason": "unmatched"},
        {"account_name": "Unmatched Account", "row_count": 1, "reason": "unmatched"},
    ]
    assert body["skipped_rows"] == 2 and body["amount_issues"] == []
    assert [(item["customer_name"], item["row_count"]) for item in body["matched"]] == [
        ("Alpha Corp", 2), ("Beta, Inc.", 1),
    ]
    assert body["matched"][0]["est_acv_total"] == 1234.5
    assert body["matched"][0]["est_tcv_total"] == 3000.0
    assert body["matched"][1]["est_acv_total"] is None
    assert body["matched"][0]["amount_coverage"] == {"acv": "partial", "tcv": "partial"}
    assert body["matched"][1]["amount_coverage"] == {"acv": "all_unknown", "tcv": "quantified"}
    # Renewal rows populate the technology inventory; the alpha account renews
    # OPENSHIFT, beta's RHEL row is Net New (no technology record).
    assert body["matched"][0]["technologies"] == ["OPENSHIFT"]
    assert body["matched"][1]["technologies"] == []
    batch = db_session.get(IntelligenceImport, import_id)
    assert batch.file_data == report and batch.file_name == "pipeline.csv"
    assert batch.total_rows == 5 and batch.matched_rows == 3
    assert batch.matched_accounts == 2 and batch.unmatched_accounts == 2
    assert json.loads(batch.unmatched_report) == body["unmatched"]
    rows = db_session.query(PartnerPipeline).order_by(PartnerPipeline.source_row).all()
    assert len(rows) == 3
    first, second, third = rows
    assert first.customer_id == world["alpha"].id and first.source_row == 1
    assert first.customer_account_name == "ALPHA  CORP"
    assert first.opportunity_name == "Platform | expansion" and first.opportunity_number == "OPP-1"
    assert first.est_acv_usd == 1234.5 and first.est_tcv_usd == 3000.0
    assert first.close_date == date(2026, 10, 30)
    assert second.close_date == date(2026, 10, 31) and third.close_date is None
    assert second.est_acv_usd is None and second.est_tcv_usd is None
    assert first.contract_start_date == date(2025, 10, 1) and first.contract_end_date is None
    assert first.current_contract_start_date == date(2025, 11, 1)
    assert first.current_contract_end_date == date(2026, 10, 31)
    assert first.opp_create_date == date(2025, 1, 15)
    assert (first.forecast_category, first.net_new_vs_renewal, first.route_to_market,
            first.opportunity_channel, first.partner_tier, first.product_sku,
            first.product_description, first.currency_code, first.fiscal_quarter,
            first.deal_reg_approval_status) == (
        "Commit", "Net New", "Indirect", "Reseller", "Premier", "SKU-1", "A description", "USD",
        "Q1", "Approved",
    )
    technology = db_session.query(CustomerTechnology).one()
    assert technology.customer_id == world["alpha"].id
    assert technology.name == "OPENSHIFT" and technology.category == "cloud_platform"
    assert technology.verification_state == "verified"
    assert technology.source == f"pipeline import #{import_id} (renewal)"
    assert technology.date_observed == batch.created_at.date()
    assert "Renewal record" in technology.notes and "OPP-2" in technology.notes
    assert technology.vendor is None and technology.quantity is None
    documents = db_session.query(CustomerKnowledge).all()
    assert len(documents) == 2
    for matched in body["matched"]:
        document = db_session.get(CustomerKnowledge, matched["knowledge_id"])
        name = matched["customer_name"]
        assert document.customer_id == matched["customer_id"]
        assert document.knowledge_type == "pipeline_report"
        assert document.file_name == "pipeline.csv" and document.original_content_type == "text/csv"
        assert document.original_storage_path == f"database:customer_knowledge.file_data:{document.id}"
        assert document.knowledge_category == "opportunities"
        assert document.processing_status == "READY" and document.processed == 1
        assert document.processor == "pipeline-import" and document.processed_at is not None
        assert document.ingestion_status == "ready" and document.ingested_at is not None
        assert document.enrichment_status == "NOT_RUN" and document.extracted_text is None
        assert document.classification == f"pipeline_import:{import_id}"
        assert document.normalized_format == "markdown"
        assert document.to_dict()["normalized_content_present"] is True
        assert name in document.normalized_content
        assert f"intelligence import #{import_id}" in document.normalized_content
        subset = csv.DictReader(io.StringIO(document.file_data.decode()))
        assert subset.fieldnames == HEADER
        subset_rows = list(subset)
        assert len(subset_rows) == matched["row_count"]
        assert all(service._norm(row["Customer Account"]) == service._norm(name) for row in subset_rows)
    alpha_doc = next(doc for doc in documents if doc.customer_id == world["alpha"].id)
    beta_doc = next(doc for doc in documents if doc.customer_id == world["beta"].id)
    assert "- Opportunities: 2 · Lines: 2 (unidentified lines: 0)" in alpha_doc.normalized_content
    assert "- Stages: open 0, won 1, lost 0, unknown 1" in alpha_doc.normalized_content
    assert "Est. ACV total: not recorded" in beta_doc.normalized_content
    assert "## Technologies recorded from renewal" in alpha_doc.normalized_content
    assert "- OPENSHIFT" in alpha_doc.normalized_content
    assert "## Technologies recorded from renewal" not in beta_doc.normalized_content
    assert "- Products: OPENSHIFT (1), RHEL (1)" in alpha_doc.normalized_content
    assert "- Growth/Risk: growth 1, risk 1" in alpha_doc.normalized_content
    assert "Platform \\| expansion" in alpha_doc.normalized_content
    detail = client.get(f"{BASE}{import_id}/", headers=_headers()).json()
    assert detail["matched_out_of_scope"] == 0 and len(detail["pipeline_rows"]) == 3
    assert detail["matched"][0]["technologies"] == ["OPENSHIFT"]
    assert detail["pipeline_rows"][0] == first.to_dict()
    assert detail["pipeline_rows"][1]["close_date"] == "2026-10-31"
    assert detail["pipeline_rows"][2]["close_date"] is None
    audit = db_session.query(AuditLog).filter_by(action="intelligence_import.create").one()
    assert audit.username == "admin" and audit.customer_id is None and audit.target_id == import_id
    assert json.loads(audit.details)["matched_rows"] == 3
    assert json.loads(audit.details)["technologies_created"] == 1
    assert db_session.query(Customer).count() == 3
    pipeline = _pipeline(client, world["alpha"])
    assert pipeline.json()["technologies"] == ["OPENSHIFT"]


@pytest.mark.parametrize("missing", service.REQUIRED_COLUMNS)
def test_missing_required_column_is_422(client, db_session, world, missing):
    data = _csv([_row()], [column for column in HEADER if column != missing])
    response = _upload(client, data)
    assert response.status_code == 422 and missing in response.json()["detail"]
    assert db_session.query(IntelligenceImport).count() == 0


@pytest.mark.parametrize("data,filename,status,message", [
    (_csv([]), "pipeline.csv", 400, "Pipeline report contains no data rows"),
    (_csv([_row()]), "pipeline.xlsx", 400, "Only .csv pipeline reports are accepted"),
    (b"\xff\xfe", "pipeline.csv", 422, "Invalid pipeline CSV"),
])
def test_invalid_upload_stores_nothing(client, db_session, world, data, filename, status, message):
    response = _upload(client, data, filename=filename)
    assert response.status_code == status and message in response.json()["detail"]
    assert db_session.query(IntelligenceImport).count() == 0
    assert db_session.query(PartnerPipeline).count() == 0
    assert db_session.query(CustomerKnowledge).count() == 0


def test_shared_upload_limit_is_enforced(client, db_session, world, monkeypatch):
    import backend.upload_size as upload_size

    monkeypatch.setattr(upload_size, "MAX_UPLOAD_BYTES", 32)
    assert _upload(client, _csv([_row()])).status_code == 413
    assert db_session.query(IntelligenceImport).count() == 0


@pytest.mark.parametrize("role", ["rep", "auditor", "inside_sales", "sales_ops", "ps_admin"])
def test_manager_surface_denies_other_roles(client, db_session, world, report, role):
    user = _user(db_session, role, legacy_role="ps_admin" if role == "ps_admin" else "user")
    headers = _headers(user.username)
    import_id = _upload(client, report).json()["import_id"]
    assert _upload(client, report, headers).status_code == 403
    assert client.get(BASE, headers=headers).status_code == 403
    assert client.get(f"{BASE}{import_id}/", headers=headers).status_code == 403
    assert client.delete(f"{BASE}{import_id}/", headers=headers).status_code == 403


@pytest.mark.parametrize("role", ["sales_manager", "sales_admin", "admin"])
def test_managers_and_admin_can_upload_list_read_delete(client, db_session, world, report, role):
    username = "admin" if role == "admin" else _user(db_session, role).username
    headers = _headers(username)
    if role == "sales_admin":
        # the sales_admin content block now covers the
        # import surface — mutations 403 at the middleware, reads stay open.
        response = _upload(client, report, headers)
        assert response.status_code == 403
        assert response.json()["detail"] == "Sales admin cannot modify account content"
        assert client.get(BASE, headers=headers).status_code == 200
        assert client.delete(f"{BASE}9999/", headers=headers).status_code == 403
        return
    response = _upload(client, report, headers)
    assert response.status_code == 200
    import_id = response.json()["import_id"]
    assert response.json()["imported_by"] == username
    assert client.get(BASE, headers=headers).status_code == 200
    assert client.get(f"{BASE}{import_id}/", headers=headers).status_code == 200
    assert client.delete(f"{BASE}{import_id}/", headers=headers).status_code == 200


def test_manager_surface_requires_authentication(client, db_session, world, report):
    assert _upload(client, report, {}).status_code == 401
    assert client.get(BASE).status_code == 401
    assert client.get(f"{BASE}1/").status_code == 401
    assert client.delete(f"{BASE}1/").status_code == 401
    assert _pipeline(client, world["alpha"], {}).status_code == 401


def test_reupload_creates_batch_and_customer_read_uses_latest_only(client, db_session, world, report):
    first = _upload(client, report).json()
    second = _upload(client, report).json()
    assert first["import_id"] != second["import_id"]
    assert first["file_sha256"] == second["file_sha256"]
    assert db_session.query(PartnerPipeline).filter_by(customer_id=world["alpha"].id).count() == 4
    assert db_session.query(CustomerKnowledge).count() == 4
    response = _pipeline(client, world["alpha"])
    assert response.status_code == 200
    body = response.json()
    assert body["import_id"] == second["import_id"]
    assert body["source_file"] == "pipeline.csv" and body["imported_at"] == second["created_at"]
    assert len(body["rows"]) == 2
    assert all(row["import_id"] == second["import_id"] for row in body["rows"])
    assert body["totals"] == {
        "line_count": 2, "deal_count": 2, "open_deals": 0, "unknown_deals": 1,
        "growth": 1, "risk": 1, "est_acv_total": 1234.5, "est_tcv_total": 3000.0,
        "amount_coverage": {"acv": "partial", "tcv": "partial"},
    }
    assert body["summary"]["source"]["import_id"] == second["import_id"]
    assert body["summary"]["amounts"]["acv"]["total"] == 1234.5
    listing = client.get(BASE, headers=_headers()).json()
    assert [item["import_id"] for item in listing] == [second["import_id"], first["import_id"]]
    assert set(listing[0]) == {"import_id", "file_name", "created_at", "imported_by", "total_rows",
                               "matched_accounts", "matched_rows", "unmatched_accounts",
                               "skipped_rows"}
    client.delete(f"{BASE}{second['import_id']}/", headers=_headers())
    assert _pipeline(client, world["alpha"]).json()["import_id"] == first["import_id"]


@pytest.mark.parametrize("with_grant", [False, True])
def test_import_detail_filters_matched_accounts_and_rows(client, db_session, world, report, with_grant):
    grants = [world["alpha"]] if with_grant else []
    manager = _user(db_session, "sales_manager", grants=grants)
    import_id = _upload(client, report).json()["import_id"]
    response = client.get(f"{BASE}{import_id}/", headers=_headers(manager.username))
    assert response.status_code == 200
    body = response.json()
    assert body["matched_out_of_scope"] == (1 if with_grant else 2)
    assert len(body["matched"]) == (1 if with_grant else 0)
    assert len(body["pipeline_rows"]) == (2 if with_grant else 0)
    assert all(row["customer_id"] == world["alpha"].id for row in body["pipeline_rows"])
    assert "Beta, Inc." not in response.text and "bETA, iNC." not in response.text


def test_customer_scope_empty_state_and_unknown_customer(client, db_session, world, report):
    rep = _user(db_session, "rep", grants=[world["alpha"], world["empty"]])
    headers = _headers(rep.username)
    _upload(client, report)
    assert _pipeline(client, world["alpha"], headers).status_code == 200
    assert _pipeline(client, world["beta"], headers).status_code == 404
    assert client.get("/api/customers/Unknown/pipeline/", headers=headers).status_code == 404
    body = _pipeline(client, world["empty"], headers).json()
    assert body["import_id"] is None and body["rows"] == []
    assert body["source_file"] is None and body["imported_at"] is None
    assert body["totals"] == {
        "line_count": 0, "deal_count": 0, "open_deals": 0, "unknown_deals": 0,
        "growth": 0, "risk": 0, "est_acv_total": None, "est_tcv_total": None,
        "amount_coverage": {"acv": "no_data", "tcv": "no_data"},
    }
    assert body["summary"]["source"] is None


def test_exact_normalization_optional_columns_and_unmatched_order(client, db_session, world):
    data = _csv([
        _row("  aLPHA\t CoRP  "), _row("Alpha Corp LLC"),
        _row("Z Unknown"), _row("Z Unknown"), _row("A Unknown"),
    ], list(service.REQUIRED_COLUMNS))
    response = _upload(client, data)
    assert response.status_code == 200
    body = response.json()
    assert body["matched_rows"] == 1
    assert body["unmatched"] == [
        {"account_name": "Z Unknown", "row_count": 2, "reason": "unmatched"},
        {"account_name": "A Unknown", "row_count": 1, "reason": "unmatched"},
        {"account_name": "Alpha Corp LLC", "row_count": 1, "reason": "unmatched"},
    ]
    row = db_session.query(PartnerPipeline).one()
    assert row.opportunity_number is None and row.est_tcv_usd is None
    assert row.contract_start_date is None and row.fiscal_quarter is None


def test_delete_removes_only_import_documents_and_their_items(client, db_session, world, report):
    other = create_customer_knowledge(db_session, world["alpha"].id, "note", "other.md", b"keep")
    other_id = other.id
    first = _upload(client, report).json()
    second = _upload(client, report).json()
    import_id = first["import_id"]
    document_id = first["matched"][0]["knowledge_id"]
    db_session.add(CustomerKnowledgeItem(
        customer_id=world["alpha"].id, source_knowledge_id=document_id,
        kind="opportunity", name="Later enriched item",
    ))
    db_session.commit()
    response = client.delete(f"{BASE}{import_id}/", headers=_headers())
    assert response.status_code == 200
    # The OPENSHIFT technology was created by the first import but the second
    # re-upload refreshed its provenance to the surviving batch, so deleting
    # the first import must not remove it.
    assert response.json() == {"detail": "Import deleted", "deleted_rows": 3,
                               "deleted_knowledge": 2, "deleted_technologies": 0}
    db_session.expire_all()
    assert db_session.get(IntelligenceImport, import_id) is None
    assert db_session.query(PartnerPipeline).filter_by(import_id=import_id).count() == 0
    assert db_session.query(CustomerKnowledge).filter_by(classification=f"pipeline_import:{import_id}").count() == 0
    assert db_session.query(CustomerKnowledgeItem).count() == 0
    assert db_session.query(CustomerTechnology).count() == 1
    assert db_session.get(CustomerKnowledge, other_id) is not None
    assert db_session.query(CustomerKnowledge).filter_by(
        classification=f"pipeline_import:{second['import_id']}",
    ).count() == 2
    audit = db_session.query(AuditLog).filter_by(action="intelligence_import.delete").one()
    assert audit.username == "admin" and audit.target_id == import_id and audit.customer_id is None
    assert json.loads(audit.details)["file_name"] == "pipeline.csv"
    assert client.get(f"{BASE}{import_id}/", headers=_headers()).status_code == 404
    assert client.delete(f"{BASE}{import_id}/", headers=_headers()).status_code == 404


def test_upload_failure_rolls_back_knowledge_helper_commits(client, db_session, world, report, monkeypatch):
    real_markdown = service._markdown
    calls = 0

    def fail_on_second_account(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic later-account failure")
        return real_markdown(*args, **kwargs)

    monkeypatch.setattr(service, "_markdown", fail_on_second_account)
    with pytest.raises(RuntimeError, match="later-account failure"):
        _upload(client, report)
    db_session.expire_all()
    assert db_session.query(IntelligenceImport).count() == 0
    assert db_session.query(PartnerPipeline).count() == 0
    assert db_session.query(CustomerKnowledge).count() == 0
    assert db_session.query(CustomerTechnology).count() == 0
    assert db_session.query(AuditLog).filter_by(action="intelligence_import.create").count() == 0


def test_delete_failure_rolls_back_knowledge_helper_commits(client, db_session, world, report, monkeypatch):
    import_id = _upload(client, report).json()["import_id"]

    def fail_audit(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(service, "_audit_import", fail_audit)
    with pytest.raises(RuntimeError, match="audit failure"):
        client.delete(f"{BASE}{import_id}/", headers=_headers())
    db_session.expire_all()
    assert db_session.get(IntelligenceImport, import_id) is not None
    assert db_session.query(PartnerPipeline).filter_by(import_id=import_id).count() == 3
    assert db_session.query(CustomerKnowledge).filter_by(classification=f"pipeline_import:{import_id}").count() == 2
    assert db_session.query(CustomerTechnology).filter_by(
        source=f"pipeline import #{import_id} (renewal)",
    ).count() == 1


def test_renewal_rows_populate_technology_inventory(client, db_session, world):
    manual = CustomerTechnology(
        customer_id=world["alpha"].id, name="RHEL", category="operating_system",
        source="discovery call", verification_state="verified",
    )
    db_session.add(manual)
    db_session.commit()
    data = _csv([
        _row("ALPHA CORP", **{"Net New Vs Renewal": "Renewal",
                              "Product Description": "Red Hat Enterprise Linux for Virtual Datacenters, Standard"}),
        _row("ALPHA CORP", **{"Net New Vs Renewal": "Renewal", "Opportunity Number": "OPP-9"}),
        _row("ALPHA CORP", **{"Net New Vs Renewal": "Renewal", "Product Offering Group": "OPENSHIFT"}),
        _row("ALPHA CORP", **{"Net New Vs Renewal": "Renewal", "Product Offering Group": "",
                              "Product Description": ""}),
        _row("ALPHA CORP", **{"Net New Vs Renewal": "New", "Product Offering Group": "LIGHTWELL NETWORK"}),
        _row("ALPHA CORP", **{"Net New Vs Renewal": "Renewal", "Product Offering Group": "ANSIBLE"}),
        _row("ALPHA CORP", **{"Net New Vs Renewal": "Renewal", "Product Offering Group": "",
                              "Product Description": "Red Hat Runtimes, Premium (16 Cores or 32 vCPUs)"}),
    ])
    response = _upload(client, data)
    assert response.status_code == 200, response.text
    body = response.json()
    import_id = body["import_id"]
    assert body["matched"][0]["technologies"] == ["ANSIBLE", "OPENSHIFT",
                                                  "Red Hat Runtimes, Premium (16 Cores or 32 vCPUs)"]
    techs = {t.name: t for t in db_session.query(CustomerTechnology).filter_by(
        customer_id=world["alpha"].id).all()}
    # RHEL is already recorded (manual) and never duplicated; the two RHEL
    # renewal line items dedupe to the existing record and leave it untouched.
    assert set(techs) == {"RHEL", "ANSIBLE", "OPENSHIFT",
                          "Red Hat Runtimes, Premium (16 Cores or 32 vCPUs)"}
    assert techs["RHEL"].source == "discovery call" and techs["RHEL"].notes is None
    # The net-new LIGHTWELL NETWORK row never populates technologies; the
    # renewal ANSIBLE row records the product exactly as typed (Product
    # Offering Group) and maps to the automation_tool category — not
    # management_tool.
    assert "LIGHTWELL NETWORK" not in techs
    assert techs["ANSIBLE"].name == "ANSIBLE"
    assert techs["ANSIBLE"].category == "automation_tool"
    assert techs["ANSIBLE"].source == f"pipeline import #{import_id} (renewal)"
    assert techs["ANSIBLE"].verification_state == "verified"
    assert techs["OPENSHIFT"].category == "cloud_platform"
    assert techs["OPENSHIFT"].source == f"pipeline import #{import_id} (renewal)"
    assert techs["OPENSHIFT"].verification_state == "verified"
    assert techs["Red Hat Runtimes, Premium (16 Cores or 32 vCPUs)"].category == "other"
    audit = db_session.query(AuditLog).filter_by(action="intelligence_import.create").one()
    assert json.loads(audit.details)["technologies_created"] == 3


def test_reupload_refreshes_import_generated_technology(client, db_session, world, report):
    first = _upload(client, report).json()
    tech = db_session.query(CustomerTechnology).one()
    assert tech.source == f"pipeline import #{first['import_id']} (renewal)"
    second = _upload(client, report).json()
    db_session.expire_all()
    techs = db_session.query(CustomerTechnology).all()
    # One record, provenance refreshed to the latest renewal evidence — no duplicates.
    assert len(techs) == 1
    assert techs[0].name == "OPENSHIFT"
    assert techs[0].source == f"pipeline import #{second['import_id']} (renewal)"
    assert second["matched"][0]["technologies"] == ["OPENSHIFT"]


def test_delete_removes_import_generated_technologies_keeps_manual(client, db_session, world, report):
    manual = CustomerTechnology(
        customer_id=world["beta"].id, name="RHEL", category="operating_system",
        source="discovery call", verification_state="verified",
    )
    db_session.add(manual)
    db_session.commit()
    import_id = _upload(client, report).json()["import_id"]
    response = client.delete(f"{BASE}{import_id}/", headers=_headers())
    assert response.status_code == 200
    assert response.json()["deleted_technologies"] == 1
    db_session.expire_all()
    remaining = db_session.query(CustomerTechnology).all()
    assert len(remaining) == 1
    assert remaining[0].customer_id == world["beta"].id and remaining[0].source == "discovery call"
    audit = db_session.query(AuditLog).filter_by(action="intelligence_import.delete").one()
    assert json.loads(audit.details)["deleted_technologies"] == 1


@pytest.mark.parametrize("role,grant,status", [
    ("rep", None, 404), ("ps_admin", "member", 404),
    ("rep", "owner", 200), ("rep", "member", 200), ("auditor", None, 200),
    ("rep", "primary_owner", 200), ("rep", "co_owner", 200),
])
def test_pipeline_central_account_read_policy(client, db_session, world, report, role, grant, status):
    from backend.models.account_membership import AccountMembership

    user = _user(db_session, role, legacy_role="ps_admin" if role == "ps_admin" else "user")
    if grant in {"owner", "member"}:
        db_session.add(CustomerUser(user_id=user.id, customer_id=world["alpha"].id, role=grant))
    elif grant:
        db_session.add(AccountMembership(
            user_id=user.id, customer_id=world["alpha"].id, role=grant,
        ))
    db_session.commit()
    _upload(client, report)
    headers = _headers(user.username)
    response = _pipeline(client, world["alpha"], headers)
    assert response.status_code == status, response.text
    assert client.get("/api/customers/Unknown/pipeline/", headers=headers).status_code == 404
    if status == 200:
        assert {row["customer_id"] for row in response.json()["rows"]} == {world["alpha"].id}
        assert "Beta, Inc." not in response.text
    else:
        assert response.json() == {"detail": "Customer not found"}


@pytest.mark.parametrize("values,total,coverage", [
    (["", ""], None, "all_unknown"), (["0.00", "0.00"], 0.0, "recorded_zero"),
    (["0.10", ""], 0.1, "partial"), (["0.10", "0.20"], 0.3, "quantified"),
])
def test_import_detail_and_frozen_markdown_use_money_safe_grain(
    client, db_session, world, values, total, coverage,
):
    first = _upload(client, _csv([
        _row(**{"Opp Stage": "Discover", "Est. ACV Line Amount (USD)": value,
                "Est. TCV Line Amount (USD)": "", "Product SKU": f"SKU-{i}"})
        for i, value in enumerate(values)
    ])).json()
    matched = first["matched"][0]
    assert matched["est_acv_total"] == total
    assert matched["est_tcv_total"] is None
    assert matched["amount_coverage"] == {"acv": coverage, "tcv": "all_unknown"}
    document = db_session.get(CustomerKnowledge, matched["knowledge_id"])
    frozen = document.normalized_content
    assert "- Opportunities: 1 · Lines: 2 (unidentified lines: 0)" in frozen
    assert "- Stages: open 1, won 0, lost 0, unknown 0" in frozen
    assert "Est. TCV total: not recorded" in frozen
    assert f"ACV {coverage}, TCV all_unknown" in frozen
    if total is None:
        assert "Est. ACV total: not recorded" in frozen
    else:
        assert f"Est. ACV total: ${total:,.2f}" in frozen
    _upload(client, _csv([_row(**{"Est. ACV Line Amount (USD)": "999.00"})]))
    detail = client.get(f"{BASE}{first['import_id']}/", headers=_headers()).json()
    assert detail["matched"][0] == matched
    db_session.refresh(document)
    assert document.normalized_content == frozen


@pytest.mark.parametrize("role,grant,status", [
    ("rep", None, 404), ("ps_admin", "member", 404),
    ("rep", "owner", 200), ("rep", "member", 200), ("auditor", None, 200),
])
def test_h3_comparison_preserves_read_auth(client, db_session, world, role, grant, status):
    first = _upload(client, _csv([_row()])).json()["import_id"]
    _upload(client, _csv([_row()]))
    user = _user(db_session, role, legacy_role="ps_admin" if role == "ps_admin" else "user")
    if grant:
        db_session.add(CustomerUser(user_id=user.id, customer_id=world["alpha"].id, role=grant))
        db_session.commit()
    url = f"/api/customers/{quote(world['alpha'].name, safe='')}/pipeline/?compare_with={first}"
    assert client.get(url).status_code == 401
    malformed = url.rsplit("=", 1)[0] + "=malformed"
    assert client.get(malformed).status_code == 401
    assert client.get("/api/customers/Unknown/pipeline/?compare_with=malformed",
                      headers=_headers(user.username)).status_code == 404
    if status == 404:
        assert client.get(malformed, headers=_headers(user.username)).status_code == 404
    response = client.get(url, headers=_headers(user.username))
    assert response.status_code == status, response.text
    assert client.get(f"/api/customers/Unknown/pipeline/?compare_with={first}",
                      headers=_headers(user.username)).status_code == 404
    if status == 200:
        body = response.json()
        assert body["comparison"]["unchanged"] == ["OPP-1"]
        assert len(body["history"]) == 2
        assert "renewals" in body
    else:
        assert response.json() == {"detail": "Customer not found"}


def test_h3_comparison_validates_scope_and_keeps_all_legacy_keys(client, db_session, world, monkeypatch):
    from datetime import UTC, datetime

    from backend.services import pipeline_read_model
    from sqlalchemy import event

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 27, 12, tzinfo=UTC)

    monkeypatch.setattr(pipeline_read_model, "datetime", FixedDatetime)
    first = _upload(client, _csv([_row()])).json()["import_id"]
    second = _upload(client, _csv([_row(**{"Opportunity Name": "Renamed"})])).json()["import_id"]
    other = _upload(client, _csv([_row("Beta, Inc.")])).json()["import_id"]
    url = f"/api/customers/{quote(world['alpha'].name, safe='')}/pipeline/"
    plain = client.get(url, headers=_headers()).json()
    assert "comparison" not in plain
    assert plain["import_id"] == second
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", record)
    try:
        response = client.get(url, params={"compare_with": first}, headers=_headers())
    finally:
        event.remove(db_session.bind, "before_cursor_execute", record)
    assert response.status_code == 200, response.text
    compared = response.json()
    assert {key: compared[key] for key in plain} == plain
    assert compared["comparison"]["name_changes"][0]["name_to"] == "Renamed"
    assert len([sql for sql in statements if sql.startswith("SELECT partner_pipeline.id")]) == 1
    assert not any("file_data" in sql for sql in statements)
    for invalid in (999999, other, second, "not-an-int", "1.5"):
        error = client.get(url, params={"compare_with": invalid}, headers=_headers())
        assert error.status_code == 400, error.text
        assert error.json() == {"detail": "Invalid comparison snapshot"}
    empty_url = f"/api/customers/{quote(world['empty'].name, safe='')}/pipeline/"
    empty = client.get(empty_url, headers=_headers()).json()
    assert empty["history"] == [] and empty["renewals"]["snapshot"] is None
    assert all(count == 0 for count in empty["renewals"]["counts"].values())
    assert client.get(empty_url, params={"compare_with": first}, headers=_headers()).status_code == 400


def test_h3_api_delete_falls_back_history_renewals_and_stale_compare_is_400(client, db_session, world, monkeypatch):
    from datetime import UTC, datetime

    from backend.services import pipeline_read_model

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 27, 12, tzinfo=UTC)

    monkeypatch.setattr(pipeline_read_model, "datetime", FixedDatetime)
    first = _upload(client, _csv([_row(**{
        "Current Contract End Date": "2026-10-27",
    })])).json()["import_id"]
    before = _pipeline(client, world["alpha"]).json()
    second = _upload(client, _csv([_row(**{
        "Current Contract End Date": "2026-12-27",
    })])).json()["import_id"]
    selected = _pipeline(client, world["alpha"]).json()
    assert selected["renewals"]["counts"]["within_90"] == 1
    assert [entry["import_id"] for entry in selected["history"]] == [second, first]
    assert client.delete(f"{BASE}{second}/", headers=_headers()).status_code == 200
    fallback = _pipeline(client, world["alpha"]).json()
    assert fallback == before
    assert fallback["renewals"]["snapshot"]["import_id"] == first
    assert fallback["renewals"]["counts"]["within_30"] == 1
    url = f"/api/customers/{quote(world['alpha'].name, safe='')}/pipeline/"
    stale = client.get(url, params={"compare_with": second}, headers=_headers())
    assert stale.status_code == 400 and stale.json() == {"detail": "Invalid comparison snapshot"}


def test_manager_upload_and_detail_are_scoped(client, db_session, world, report):
    manager = _user(db_session, "sales_manager", grants=[world["alpha"]])
    response = _upload(client, report, headers=_headers(manager.username))
    assert response.status_code == 200, response.text
    upload = response.json()
    assert upload["matched_accounts"] == 2 and upload["visible_customer_count"] == 1
    assert [row["customer_id"] for row in upload["matched"]] == [world["alpha"].id]
    scoped = client.get(f"{BASE}{upload['import_id']}/", headers=_headers(manager.username)).json()
    admin = client.get(f"{BASE}{upload['import_id']}/", headers=_headers()).json()
    assert scoped["visible_customer_count"] == 1 and scoped["matched_accounts"] == 2
    assert admin["visible_customer_count"] == len(admin["matched"]) == 2
    assert upload["unmatched"] == admin["unmatched"]


# a dollar amount the parser
# cannot read never rejects the file — the amount is recorded as unknown and
# the cell is reported as an amount warning; common export formats parse.
@pytest.mark.parametrize("cell,expected", [
    ("$1,234.50", 1234.5), ("USD 1,234", 1234.0), ("1 234", 1234.0), ("1\u00a0234.5", 1234.5),
    ("-1,234", -1234.0), ("(1,234.00)", -1234.0), ("$(250)", -250.0), ("0", 0.0),
    ("", None), ("-", None), ("N/A", None), ("\u2014", None), ("NaN", None), ("inf", None),
    ("call me", None), ("12abc", None),
])
def test_amount_formats(cell, expected):
    amount, readable = service._money(cell)
    if cell in ("call me", "12abc"):
        assert amount is None and readable is False
    else:
        assert amount == expected and readable is True


def test_unreadable_amount_imports_row_and_warns(client, db_session, world):
    data = _csv([
        _row(**{"Est. ACV Line Amount (USD)": "call me"}),
        _row("Beta, Inc.", **{"Est. TCV Line Amount (USD)": "12abc"}),
        _row("Nobody Ltd", **{"Est. ACV Line Amount (USD)": "garbage"}),
    ])
    response = _upload(client, data)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["matched_rows"] == 2 and body["skipped_rows"] == 1
    # The unmatched row is skipped, never a new customer.
    assert db_session.query(Customer).count() == 3
    # Only imported rows are parsed; the unmatched row's cell is not reported.
    assert body["amount_issues"] == [
        {"source_row": 1, "column": "Est. ACV Line Amount (USD)", "value": "call me"},
        {"source_row": 2, "column": "Est. TCV Line Amount (USD)", "value": "12abc"},
    ]
    rows = db_session.query(PartnerPipeline).order_by(PartnerPipeline.source_row).all()
    assert rows[0].est_acv_usd is None and rows[0].est_tcv_usd == 3000.0
    assert rows[1].est_tcv_usd is None and rows[1].est_acv_usd == 1234.5
    detail = client.get(f"{BASE}{body['import_id']}/", headers=_headers()).json()
    assert detail["amount_issues"] == body["amount_issues"]


def test_amount_issues_are_scoped_like_matched_rows(client, db_session, world):
    body = _upload(client, _csv([
        _row(**{"Est. ACV Line Amount (USD)": "bad"}),
        _row("Beta, Inc.", **{"Est. ACV Line Amount (USD)": "bad"}),
    ])).json()
    batch = db_session.get(IntelligenceImport, body["import_id"])
    detail = service.get_import(db_session, batch.id, customer_ids=[world["beta"].id])
    assert [issue["source_row"] for issue in detail["amount_issues"]] == [2]


def test_legacy_batch_reads_without_reason_or_amount_issues(client, db_session, world):
    body = _upload(client, _csv([_row(), _row("Nobody")])).json()
    batch = db_session.get(IntelligenceImport, body["import_id"])
    batch.unmatched_report = json.dumps([{"account_name": "Nobody", "row_count": 1}])
    batch.amount_issues = None
    db_session.commit()
    detail = client.get(f"{BASE}{batch.id}/", headers=_headers()).json()
    assert detail["unmatched"] == [{"account_name": "Nobody", "row_count": 1, "reason": "unmatched"}]
    assert detail["amount_issues"] == []
