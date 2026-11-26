"""access-neutral 404-first oracle sweep.

For every remapped legacy route: an out-of-scope caller gets exactly the
same 404 (status AND body) as a request for a missing record, so a probe
cannot reveal existence; an in-scope caller who lacks the write capability
keeps the exact 403. Pattern: test_departments_count.py::
test_department_by_id_is_404_first.

Run: pytest tests/backend/test_404_first_oracle_sweep.py -v
"""

import os

import pytest

from tests.backend.common import _mk_user

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

MISSING = 999999
NOT_AUTHORIZED_TO_MODIFY = "Not authorized to modify this customer"


def _token(username: str) -> dict:
    from backend.auth import create_access_token
    token = create_access_token({"sub": username, "is_admin": False})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def sweep(db_session):
    from backend.models.collaboration import Comment
    from backend.models.customer_technology import CustomerTechnology
    from backend.models.sales_evaluation import SalesEvaluation
    from backend.models.technology_dependency import TechnologyDependency
    from backend.models.third_party_service import ThirdPartyService, ThirdPartyServiceDocument
    from backend.models.use_case import (
        AIPrediction,
        Customer,
        CustomerAssessment,
        CustomerUser,
        UseCase,
    )

    cust = Customer(name="SweepCo", description="S")
    other = Customer(name="SweepOther", description="O")
    db_session.add_all([cust, other])
    db_session.flush()
    owner = _mk_user(db_session, "sweep_owner", sales_role="rep")
    auditor = _mk_user(db_session, "sweep_auditor")  # in scope via an auditor junction, read-only
    outsider = _mk_user(db_session, "sweep_outsider", sales_role="rep")  # no grant on SweepCo
    db_session.add_all([
        CustomerUser(customer_id=cust.id, user_id=owner.id, role="owner"),
        CustomerUser(customer_id=cust.id, user_id=auditor.id, role="auditor"),
        CustomerUser(customer_id=other.id, user_id=outsider.id, role="owner"),
    ])
    assessment = CustomerAssessment(customer_id=cust.id, name="Round one", created_by="sweep_owner")
    db_session.add(assessment)
    db_session.flush()
    uc = UseCase(title="Sweep UC", customer_id=cust.id, department="Eng", status="active",
                 created_by="sweep_owner", assessment_id=assessment.id)
    evaluation = SalesEvaluation(customer_id=cust.id, evaluation_name="Sweep eval")
    tech1 = CustomerTechnology(customer_id=cust.id, name="vSphere", category="software")
    tech2 = CustomerTechnology(customer_id=cust.id, name="R720", category="hardware")
    tps = ThirdPartyService(customer_id=cust.id, vendor_name="V", service_category="technical",
                            description="d")
    db_session.add_all([uc, evaluation, tech1, tech2, tps])
    db_session.flush()
    dep = TechnologyDependency(customer_id=cust.id, source_id=tech1.id, target_id=tech2.id,
                               relationship_type="depends_on")
    doc = ThirdPartyServiceDocument(service_id=tps.id, customer_id=cust.id, document_type="po",
                                    file_name="po.pdf", file_data=b"po")
    prediction = AIPrediction(use_case_id=uc.id, customer_id=cust.id, horizon_days=30,
                              predicted_score=60)
    comment = Comment(use_case_id=uc.id, user_name="sweep_owner", content="c")
    db_session.add_all([dep, doc, prediction, comment])
    db_session.commit()
    return {
        "cust": cust.id, "name": cust.name, "assessment": assessment.id, "uc": uc.id,
        "evaluation": evaluation.id, "tech1": tech1.id, "tech2": tech2.id, "dep": dep.id,
        "tps": tps.id, "doc": doc.id, "prediction": prediction.id, "comment": comment.id,
        "outsider_id": outsider.id,
    }


def _same_404(client, method, url, missing_url, **kwargs):
    """The out-of-scope response is indistinguishable from the missing one."""
    h = _token("sweep_outsider")
    out_of_scope = getattr(client, method)(url, headers=h, **kwargs)
    missing = getattr(client, method)(missing_url, headers=h, **kwargs)
    assert out_of_scope.status_code == 404, f"{method} {url}: {out_of_scope.status_code} {out_of_scope.text[:160]}"
    assert missing.status_code == 404, f"{method} {missing_url}: {missing.status_code} {missing.text[:160]}"
    assert out_of_scope.json() == missing.json(), (url, out_of_scope.json(), missing.json())


def _exact_403(response, detail):
    assert response.status_code == 403, f"{response.status_code} {response.text[:160]}"
    assert response.json()["detail"] == detail


def test_customers_routes_are_404_first(client, sweep):
    base, missing = f"/api/customers/{sweep['name']}/", "/api/customers/NoSuchSweepCo/"
    for suffix in ("", "use-cases/", "assessments/"):
        _same_404(client, "get", base + suffix, missing + suffix)
    _same_404(client, "put", base, missing, json={"description": "x"})
    _same_404(client, "delete", base, missing)
    _same_404(client, "post", base + "assessments/", missing + "assessments/", json={"name": "R2"})
    _same_404(client, "post", base + "assessments/from-template/", missing + "assessments/from-template/",
              json={"template_id": "customer-support"})
    _same_404(client, "post", f"{base}assessments/{sweep['assessment']}/archive/",
              f"{missing}assessments/{sweep['assessment']}/archive/")
    h = _token("sweep_auditor")
    assert client.get(base, headers=h).status_code == 200
    # update = central CAP_METADATA, create round = CAP_EDIT.
    _exact_403(client.put(base, headers=h, json={"description": "x"}), NOT_AUTHORIZED_TO_MODIFY)
    _exact_403(client.post(base + "assessments/", headers=h, json={"name": "R2"}),
               NOT_AUTHORIZED_TO_MODIFY)


def test_customer_users_list_is_404_first(client, sweep):
    _same_404(client, "get", f"/api/customers/{sweep['name']}/users/", "/api/customers/NoSuchSweepCo/users/")
    assert client.get(f"/api/customers/{sweep['name']}/users/", headers=_token("sweep_auditor")).status_code == 200


def test_customer_stats_is_404_first(client, sweep):
    _same_404(client, "get", f"/api/customers/{sweep['name']}/stats/", "/api/customers/NoSuchSweepCo/stats/")
    assert client.get(f"/api/customers/{sweep['name']}/stats/", headers=_token("sweep_auditor")).status_code == 200


def test_customer_intelligence_is_404_first(client, sweep):
    for surface in ("overview", "workspace", "graph"):
        _same_404(client, "get", f"/api/customers/{sweep['cust']}/intelligence/{surface}/",
                  f"/api/customers/{MISSING}/intelligence/{surface}/")
        r = client.get(f"/api/customers/{sweep['cust']}/intelligence/{surface}/", headers=_token("sweep_auditor"))
        assert r.status_code == 200, surface


def test_account_impact_is_404_first(client, sweep):
    _same_404(client, "get", f"/api/customers/{sweep['name']}/account-impact/",
              "/api/customers/NoSuchSweepCo/account-impact/")
    r = client.get(f"/api/customers/{sweep['name']}/account-impact/", headers=_token("sweep_auditor"))
    assert r.status_code == 200


def test_account_memberships_are_404_first(client, sweep):
    base, missing = f"/api/customers/{sweep['name']}/", "/api/customers/NoSuchSweepCo/"
    payload = {"user_id": sweep["outsider_id"], "role": "inside_sales"}
    _same_404(client, "get", base + "memberships/", missing + "memberships/")
    _same_404(client, "post", base + "memberships/", missing + "memberships/", json=payload)
    _same_404(client, "post", base + "transfer-ownership/", missing + "transfer-ownership/",
              json={"user_id": sweep["outsider_id"]})
    h = _token("sweep_auditor")
    assert client.get(base + "memberships/", headers=h).status_code == 200
    _exact_403(client.post(base + "memberships/", headers=h, json=payload),
               "Not permitted to manage the inside_sales role on this account")


def test_sales_evaluation_by_id_is_404_first(client, sweep):
    url, missing = f"/api/sales-evaluations/{sweep['evaluation']}", f"/api/sales-evaluations/{MISSING}"
    _same_404(client, "get", url, missing)
    _same_404(client, "put", url, missing, json={"evaluation_name": "x"})
    _same_404(client, "delete", url, missing)
    h = _token("sweep_auditor")
    assert client.get(url, headers=h).status_code == 200
    _exact_403(client.put(url, headers=h, json={"evaluation_name": "x"}), NOT_AUTHORIZED_TO_MODIFY)
    _exact_403(client.delete(url, headers=h), NOT_AUTHORIZED_TO_MODIFY)


def test_technology_inventory_customer_routes_are_404_first(client, sweep):
    url, missing = f"/api/customers/{sweep['cust']}/technology/", f"/api/customers/{MISSING}/technology/"
    payload = {"name": "X", "category": "software"}
    _same_404(client, "get", url, missing)
    _same_404(client, "post", url, missing, json=payload)
    h = _token("sweep_auditor")
    assert client.get(url, headers=h).status_code == 200
    _exact_403(client.post(url, headers=h, json=payload), NOT_AUTHORIZED_TO_MODIFY)


def test_technology_dependency_customer_routes_are_404_first(client, sweep):
    url = f"/api/customers/{sweep['cust']}/technology-dependencies/"
    missing = f"/api/customers/{MISSING}/technology-dependencies/"
    payload = {"source_id": sweep["tech1"], "target_id": sweep["tech2"], "relationship_type": "depends_on"}
    _same_404(client, "get", url, missing)
    _same_404(client, "post", url, missing, json=payload)
    h = _token("sweep_auditor")
    assert client.get(url, headers=h).status_code == 200
    _exact_403(client.post(url, headers=h, json=payload), NOT_AUTHORIZED_TO_MODIFY)


def test_analytics_routes_are_404_first(client, sweep):
    _same_404(client, "get", f"/api/analytics/readiness-insight/?customer_id={sweep['cust']}",
              f"/api/analytics/readiness-insight/?customer_id={MISSING}")
    _same_404(client, "post", f"/api/analytics/readiness-insight/generate/?customer_id={sweep['cust']}",
              f"/api/analytics/readiness-insight/generate/?customer_id={MISSING}")
    _same_404(client, "get", f"/api/analytics/predictive/{sweep['uc']}/", f"/api/analytics/predictive/{MISSING}/")
    _same_404(client, "post", f"/api/analytics/predictions/generate/?use_case_id={sweep['uc']}",
              f"/api/analytics/predictions/generate/?use_case_id={MISSING}")
    _same_404(client, "delete", f"/api/analytics/predictions/{sweep['prediction']}/",
              f"/api/analytics/predictions/{MISSING}/")
    h = _token("sweep_auditor")
    assert client.get(f"/api/analytics/readiness-insight/?customer_id={sweep['cust']}", headers=h).status_code == 200
    _exact_403(client.post(f"/api/analytics/readiness-insight/generate/?customer_id={sweep['cust']}", headers=h),
               NOT_AUTHORIZED_TO_MODIFY)
    _exact_403(client.delete(f"/api/analytics/predictions/{sweep['prediction']}/", headers=h),
               "Global admin or customer owner role required")


def test_comment_routes_are_404_first(client, sweep):
    uc_url, uc_missing = f"/api/use-cases/{sweep['uc']}/comments/", f"/api/use-cases/{MISSING}/comments/"
    c_url, c_missing = f"/api/use-cases/comments/{sweep['comment']}/", f"/api/use-cases/comments/{MISSING}/"
    _same_404(client, "get", uc_url, uc_missing)
    _same_404(client, "post", uc_url, uc_missing, json={"content": "x"})
    _same_404(client, "put", c_url, c_missing, json={"content": "y"})
    _same_404(client, "delete", c_url, c_missing)
    h = _token("sweep_auditor")
    assert client.get(uc_url, headers=h).status_code == 200
    _exact_403(client.post(uc_url, headers=h, json={"content": "x"}), "commenting requires note access to this customer")
    _exact_403(client.put(c_url, headers=h, json={"content": "y"}), "Only the author or an admin can edit this comment")


def test_third_party_service_id_routes_are_404_first(client, sweep):
    svc, doc = sweep["tps"], sweep["doc"]
    _same_404(client, "get", f"/api/third-party-services/{svc}/", f"/api/third-party-services/{MISSING}/")
    _same_404(client, "put", f"/api/third-party-services/{svc}/", f"/api/third-party-services/{MISSING}/",
              json={"notes": "x"})
    _same_404(client, "get", f"/api/third-party-services/{svc}/documents/",
              f"/api/third-party-services/{MISSING}/documents/")
    _same_404(client, "post", f"/api/third-party-services/{svc}/documents/",
              f"/api/third-party-services/{MISSING}/documents/",
              files={"file": ("po.pdf", b"po", "application/pdf")}, data={"document_type": "po"})
    _same_404(client, "get", f"/api/third-party-services/{doc}/download/",
              f"/api/third-party-services/{MISSING}/download/")
    _same_404(client, "delete", f"/api/third-party-services/{svc}/documents/{doc}/",
              f"/api/third-party-services/{svc}/documents/{MISSING}/")
    _same_404(client, "delete", f"/api/third-party-services/{svc}/", f"/api/third-party-services/{MISSING}/")
    h = _token("sweep_auditor")
    assert client.get(f"/api/third-party-services/{svc}/", headers=h).status_code == 200
    _exact_403(client.put(f"/api/third-party-services/{svc}/", headers=h, json={"notes": "x"}),
               NOT_AUTHORIZED_TO_MODIFY)


@pytest.mark.parametrize("path", ["/api/export/pdf/", "/api/stats/export/csv/"])
def test_export_scope_is_404_first(client, sweep, path):
    _same_404(client, "get", f"{path}?customer_name={sweep['name']}", f"{path}?customer_name=NoSuchSweepCo")
    _same_404(client, "get", f"{path}?assessment_id={sweep['assessment']}", f"{path}?assessment_id={MISSING}")
    r = client.get(f"{path}?customer_name={sweep['name']}", headers=_token("sweep_auditor"))
    assert r.status_code == 200, r.text[:160]


# ── primary-side completion (2026-10-29): the filter + legacy write routes ──

def test_sales_notes_are_404_first(client, sweep):
    base, missing = f"/api/customers/{sweep['cust']}/sales-notes/", f"/api/customers/{MISSING}/sales-notes/"
    payload = {"category": "discovery", "title": "t", "content": "c"}
    _same_404(client, "get", base, missing)
    _same_404(client, "post", base, missing, json=payload)
    # in-scope auditor (junction read) without the write grant: exact 403
    r = client.post(base, headers=_token("sweep_auditor"), json=payload)
    _exact_403(r, NOT_AUTHORIZED_TO_MODIFY)


def test_use_case_writes_are_404_first(client, sweep):
    uc, missing = f"/api/use-cases/{sweep['uc']}/", f"/api/use-cases/{MISSING}/"
    _same_404(client, "put", uc, missing, json={"title": "x"})
    _same_404(client, "delete", uc, missing)
    body = {"title": "n", "customer_id": sweep["cust"]}
    # create: out-of-scope customer == missing customer
    out = client.post("/api/use-cases/", headers=_token("sweep_outsider"), json=body)
    assert out.status_code == 404 and out.json()["detail"] == "Customer not found"
    miss = client.post("/api/use-cases/", headers=_token("sweep_outsider"),
                       json={"title": "n", "customer_id": MISSING})
    assert miss.status_code == 404 and miss.json() == out.json()
    # in-scope auditor without edit: exact 403
    r = client.post("/api/use-cases/", headers=_token("sweep_auditor"), json=body)
    _exact_403(r, NOT_AUTHORIZED_TO_MODIFY)


def test_customer_sharing_mutations_are_404_first(client, sweep):
    add = f"/api/customers/{sweep['name']}/users/?user_id={sweep['outsider_id']}&role=member"
    role = f"/api/customers/{sweep['name']}/users/{sweep['outsider_id']}/?role=member"
    miss_add = f"/api/customers/NoSuchSweepCo/users/?user_id={sweep['outsider_id']}&role=member"
    miss_role = f"/api/customers/NoSuchSweepCo/users/{sweep['outsider_id']}/?role=member"
    _same_404(client, "post", add, miss_add)
    _same_404(client, "put", role, miss_role)
    # the owner is in scope for the mutation surface
    assert client.post(add, headers=_token("sweep_owner")).status_code == 200


def test_sales_evaluations_list_and_preview_are_404_first(client, sweep):
    _same_404(client, "get", f"/api/sales-evaluations/?customer_id={sweep['cust']}",
              f"/api/sales-evaluations/?customer_id={MISSING}")
    body = {"customer_id": sweep["cust"], "persona": "security"}
    out = client.post("/api/sales-evaluations/preview/", headers=_token("sweep_outsider"), json=body)
    assert out.status_code == 404 and out.json()["detail"] == "Customer not found"
    miss = client.post("/api/sales-evaluations/preview/", headers=_token("sweep_outsider"),
                       json={"customer_id": MISSING, "persona": "security"})
    assert miss.json() == out.json()


def test_advanced_routes_are_404_first(client, sweep):
    _same_404(client, "get", f"/api/advanced/impact-matrix/?customer_id={sweep['cust']}",
              f"/api/advanced/impact-matrix/?customer_id={MISSING}")
    # the drill-down 404 echoes the requested id (the existing missing pattern)
    # — indistinguishability is against the SAME id, so compare shapes.
    out = client.get(f"/api/advanced/drill-down/{sweep['uc']}/", headers=_token("sweep_outsider"))
    assert out.status_code == 404
    assert out.json() == {"detail": f"Use case {sweep['uc']} not found"}
    miss = client.get(f"/api/advanced/drill-down/{MISSING}/", headers=_token("sweep_outsider"))
    assert miss.json() == {"detail": f"Use case {MISSING} not found"}


def test_scoring_is_404_first(client, sweep):
    # the scoring 404 echoes the requested id (the existing missing pattern) —
    # indistinguishability is against the SAME id.
    body = {"use_case_id": sweep["uc"], "reasoning": "t"}
    out = client.post("/api/scoring/", headers=_token("sweep_outsider"), json=body)
    assert out.status_code == 404
    assert out.json() == {"detail": f"Use case {sweep['uc']} not found"}
    miss = client.post("/api/scoring/", headers=_token("sweep_outsider"),
                       json={"use_case_id": MISSING, "reasoning": "t"})
    assert miss.json() == {"detail": f"Use case {MISSING} not found"}


def test_bulk_template_create_is_404_first(client, sweep):
    body = {"template_id": "customer-support", "title": "t", "department": "d",
            "customer_id": sweep["cust"]}
    out = client.post("/api/bulk/create-from-template/", headers=_token("sweep_outsider"), json=body)
    assert out.status_code == 404 and out.json()["detail"] == "Customer not found"
    miss = client.post("/api/bulk/create-from-template/", headers=_token("sweep_outsider"),
                       json={"template_id": "customer-support", "title": "t", "department": "d",
                             "customer_id": MISSING})
    assert miss.json() == out.json()


def test_notification_customer_filter_is_404_first(client, sweep):
    _same_404(client, "get", f"/api/use-cases/notifications/?customer_id={sweep['cust']}",
              f"/api/use-cases/notifications/?customer_id={MISSING}")


def test_projection_generate_and_clear_are_404_first(client, sweep):
    base, missing = f"/api/customers/{sweep['name']}/projections/", "/api/customers/NoSuchSweepCo/projections/"
    _same_404(client, "post", base, missing)
    _same_404(client, "delete", base, missing)


def test_stats_and_customer_knowledge_filters_are_404_first(client, sweep):
    _same_404(client, "get", f"/api/stats/aggregate/?customer_id={sweep['cust']}",
              f"/api/stats/aggregate/?customer_id={MISSING}")
    _same_404(client, "get", f"/api/customer-knowledge/?customer_id={sweep['cust']}",
              f"/api/customer-knowledge/?customer_id={MISSING}")
    r = client.post("/api/customer-knowledge/",
                    headers=_token("sweep_outsider"),
                    data={"customer_id": str(sweep["cust"])},
                    files={"file": ("n.md", b"# x", "text/markdown")})
    assert r.status_code == 404, r.text[:160]
