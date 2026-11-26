"""Synthetic account-report import, matching and isolation checks."""

import io

from backend.models.customer_alias import CustomerAlias
from backend.models.redhat_opportunity_import import RedHatOpportunityImport, RedHatOpportunityRow
from backend.models.use_case import Customer, CustomerUser, User
from backend.services.customers_service import delete_customer_with_use_cases
from openpyxl import Workbook

from tests.backend.test_customer_contacts import headers


def workbook(rows):
    book = Workbook()
    sheet = book.active
    sheet.append(["Report"])
    sheet.append([])
    sheet.append(["Account Info"])
    sheet.append(["ACCOUNT NAME", "ACCOUNT OWNER", "OCPv Play", "VMWARE ESXI", "DUNS"])
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def test_import_scoped_matching_owner_and_customer_delete(client, db_session):
    rep = User(username="rh_import_rep", sales_role="rep", is_active=1, approved=1)
    outsider = User(username="rh_import_outsider", sales_role="rep", is_active=1, approved=1)
    account = Customer(name="Synthetic Account")
    db_session.add_all([rep, outsider, account])
    db_session.flush()
    db_session.add(CustomerUser(customer_id=account.id, user_id=rep.id, role="owner"))
    db_session.add(CustomerAlias(customer_id=account.id, alias="Synthetic Alias", alias_norm="synthetic alias"))
    db_session.commit()
    cid = account.id
    payload = workbook([["Synthetic Account", "Red Hat Person", True, "Y", "unrelated-data"],
                        ["  synthetic   ALIAS  ", "Another Red Hat Person", False, "N"],
                        ["Unmatched Account", "Other Person", True, "Y"],
                        ["Synthetic Account Inc", "RH Person", True, "Y"]])
    before = db_session.query(Customer).count()
    r = client.post('/api/redhat-opportunity-import/', headers=headers(),
                    files={"file": ("synthetic.xlsx", payload, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    assert (r.json()["total_rows"], r.json()["matched_rows"], r.json()["matched_accounts"]) == (4, 2, 1)
    assert r.json()["skipped"][0]["source_row"] == 7
    assert r.json()["skipped"][1]["suggestion"] == {"customer_id": cid, "customer_name": "Synthetic Account"}
    history = client.get(f'/api/redhat-opportunity-import/{r.json()["import_id"]}/unmatched/', headers=headers())
    assert history.status_code == 200 and history.json() == r.json()["skipped"]
    assert db_session.query(Customer).count() == before
    assert db_session.query(CustomerUser).filter_by(customer_id=cid, user_id=rep.id, role="owner").count() == 1
    result = client.get(f'/api/customers/{cid}/redhat-opportunities/', headers=headers(rep.username))
    assert result.status_code == 200
    assert result.json()["matched_account"] == "Synthetic Account"
    assert result.json()["opportunities"] == [{"type": "openshift_virtualization", "title": "OpenShift Virtualization",
        "vendors": ["VMware"], "redhat_representatives": ["Red Hat Person"]}]
    stored = db_session.query(RedHatOpportunityRow).filter_by(customer_id=cid).first()
    assert "DUNS" not in stored.fields_json and "unrelated-data" not in stored.fields_json
    assert [row.matched_by for row in db_session.query(RedHatOpportunityRow).filter_by(customer_id=cid)
            .order_by(RedHatOpportunityRow.source_row).all()] == ["name", "alias"]
    assert client.get(f'/api/customers/{cid}/redhat-opportunities/', headers=headers(outsider.username)).status_code == 404
    assert client.post('/api/redhat-opportunity-import/', headers=headers(rep.username),
                       files={"file": ("synthetic.xlsx", payload)}).status_code == 403
    delete_customer_with_use_cases(db_session, db_session.get(Customer, cid))
    assert db_session.query(RedHatOpportunityRow).filter_by(customer_id=cid).count() == 0


def test_invalid_workbooks_are_rejected(client):
    response = client.post('/api/redhat-opportunity-import/', headers=headers(), files={"file": ("bad.xlsx", b"bad")})
    assert response.status_code == 422


def test_sales_admin_blocked_from_import_surface(client, db_session):
    user = User(username="rh_import_sales_admin", sales_role="sales_admin", is_active=1, approved=1)
    db_session.add(user)
    db_session.commit()
    auth_headers = headers(user.username)
    payload = workbook([["Synthetic Account", "RH owner", True, "Y"]])
    for body in (payload, b"bad"):
        response = client.post('/api/redhat-opportunity-import/', headers=auth_headers,
                               files={"file": ("synthetic.xlsx", body)})
        assert response.status_code == 403, response.text
        assert response.json()["detail"] == "Sales admin cannot modify account content"
    for path in ('/api/redhat-opportunity-import/', '/api/redhat-opportunity-import/99999/unmatched/'):
        response = client.get(path, headers=auth_headers)
        assert response.status_code == 403, response.text
        assert response.json()["detail"] == "Manager access required"
    assert db_session.query(RedHatOpportunityRow).count() == 0
    assert db_session.query(RedHatOpportunityImport).count() == 0


def test_opportunity_cards_positive_vendor_flags_only():
    from backend.services.redhat_opportunity_service import opportunity_cards
    row = RedHatOpportunityRow(redhat_owner="RH rep", fields_json='{"RHEL CLONE?": true, "ROCKY LINUX": "Y", '
        '"UBUNTU": "N", "OCPV PLAY": true, "NUTANIX ANY": "Y", "EOL F5 BIGIP ANY": "Y", '
        '"EOL PAN PA3200": "N", "EOL MERAKI ANY": "Y"}')
    cards = opportunity_cards([row])
    assert [(item["title"], item["vendors"]) for item in cards] == [
        ("RHEL Clone Replace", ["Rocky Linux"]), ("OpenShift Virtualization", ["Nutanix"]),
        ("Ansible Network Automation", ["Cisco", "F5"])]
    assert all(item["redhat_representatives"] == ["RH rep"] for item in cards)
    empty = RedHatOpportunityRow(fields_json='{"RHEL CLONE?": false, "OCPV PLAY": "N", "NETWORKING PLAY": null}')
    assert opportunity_cards([empty]) == []


def test_manager_upload_does_not_link_outside_scope(client, db_session):
    manager = User(username="rh_manager", sales_role="sales_manager", is_active=1, approved=1)
    rep = User(username="rh_report", sales_role="rep", is_active=1, approved=1)
    allowed = Customer(name="Synthetic allowed")
    outside = Customer(name="Synthetic outside")
    db_session.add_all([manager, rep, allowed, outside])
    db_session.flush()
    from backend.models.sales_access import SalesReporting
    db_session.add(SalesReporting(manager_user_id=manager.id, rep_user_id=rep.id))
    db_session.add(CustomerUser(customer_id=allowed.id, user_id=rep.id, role="owner"))
    db_session.commit()
    data = workbook([["Synthetic allowed", "RH owner", True, "Y"],
                     ["Synthetic outside", "RH owner", True, "Y"],
                     ["Missing account", "RH owner", False, "N"]])
    result = client.post('/api/redhat-opportunity-import/', headers=headers(manager.username),
                         files={"file": ("synthetic.xlsx", data)})
    assert result.status_code == 200
    assert result.json()["matched_rows"] == 1
    assert [row["reason"] for row in result.json()["skipped"]] == [
        "No unambiguous accessible customer name or alias"] * 2
    assert db_session.query(RedHatOpportunityRow).filter_by(customer_id=outside.id).count() == 0
