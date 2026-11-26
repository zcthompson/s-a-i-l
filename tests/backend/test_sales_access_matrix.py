"""Sales access matrix — shift to global customer management phase 3b.

The access fixture: two managers, reps in each team, an
inside-sales user assigned to only some customers, a multi-rep support
assignment, scoped + org-wide auditors, a system admin, a service admin
(ps_admin), an unassigned customer, and pending/inactive identities.

Asserts the central resolver (backend/services/sales_access.py) is wired as
the WRITE gate on every customer-data mutation route:

  (a) a rep cannot acquire another team's customer via an id/assignment payload
  (b) inside-sales cannot transfer ownership / delete the customer / elevate
  (c) a manager's scope is only their team's customers
  (d) an auditor is read-only on every mutation path (403 writes, 200 reads)
  (e) ps_admin is confined to the third-party-services surface
  (f) pending / inactive identities are denied
  (g) revocation removes access

Deterministic: no LLM is reached — every denied request is rejected before
any inference call, and the allowed-path assertions use deterministic routes.
"""

import io
from datetime import UTC, datetime

import pytest
from backend.services import sales_access

GATE_DETAIL = "Not authorized to modify this customer"


@pytest.mark.parametrize("context, customer_id, expected", [
    ({"junction_roles": {1: "owner"}}, 1, True),
    ({"membership_roles": {1: ["primary_owner"]}}, 1, True),
    ({"membership_roles": {1: ["co_owner"]}}, 1, True),
    ({"membership_roles": {1: ["sales_ops"]}}, 1, True),
    ({"membership_roles": {1: ["inside_sales"]}}, 1, False),
    ({"membership_roles": {1: ["inside_sales"]},
      "section_grants": {1: {"intel_uploads": "contribute"}}}, 1, True),
    ({"membership_roles": {1: ["inside_sales"]},
      "section_grants": {1: {"intel_uploads": "read", "notes": "contribute"}}}, 1, False),
    ({"junction_roles": {1: "member"}}, 1, False),
    ({"junction_roles": {1: "member"},
      "section_grants": {1: {"intel_uploads": "contribute"}}}, 1, True),
    ({"junction_roles": {1: "auditor"},
      "section_grants": {1: {"intel_uploads": "contribute"}}}, 1, False),
    ({"sales_role": "auditor", "junction_roles": {1: "owner"}}, 1, False),
    ({"sales_role": "sales_admin", "junction_roles": {1: "owner"}}, 1, False),
    ({"role": "ps_admin", "junction_roles": {1: "owner"}}, 1, False),
    ({"is_admin": 1}, 1, True),
    ({"junction_roles": {1: "owner"}}, None, False),
    ({"junction_roles": {2: "owner"}}, 2, False),
])
def test_intel_uploads_capability_requires_owner_or_explicit_section_grant(
    context, customer_id, expected,
):
    user = {"username": "synthetic_policy_user", "customer_ids": [1], "membership_roles": {},
            **context}
    assert sales_access.CAP_INTEL_UPLOADS in sales_access.ALL_CAPS
    assert sales_access.can(user, None, sales_access.CAP_INTEL_UPLOADS, customer_id) is expected


# ── identity helpers ─────────────────────────────────────────────────────────


def _headers(username: str) -> dict:
    from backend.auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token({'sub': username, 'is_admin': False})}"}


def _admin_headers(db_session) -> dict:
    from backend.auth import create_access_token
    from backend.models.use_case import User

    admin = db_session.query(User).filter(User.is_admin == 1).first()
    return {"Authorization": f"Bearer {create_access_token({'sub': admin.username, 'is_admin': True})}"}


def _mk_user(db, username, *, sales_role=None, role=None, is_admin=0, approved=1, is_active=1):
    from backend.auth import hash_password
    from backend.models.use_case import User

    u = User(
        username=username, email=f"{username}@test.local",
        hashed_password=hash_password(username), display_name=username,
        department="Sales", is_admin=is_admin, approved=approved, is_active=is_active,
        sales_role=sales_role, role=role,
    )
    db.add(u)
    db.flush()
    return u


def _grant(db, customer, user, role):
    from backend.models.use_case import CustomerUser

    db.add(CustomerUser(customer_id=customer.id, user_id=user.id, role=role, granted_by=user.id))


def _user_dict(db, username) -> dict:
    """The dict ``get_user_from_request`` builds (minus the request plumbing)."""
    from backend.models.use_case import CustomerUser, User

    u = db.query(User).filter(User.username == username).first()
    rows = db.query(CustomerUser).filter(CustomerUser.user_id == u.id).all()
    return {
        "username": u.username, "user_id": u.id, "is_admin": u.is_admin,
        "role": u.role, "sales_role": u.sales_role,
        "customer_ids": [r.customer_id for r in rows],
        "junction_roles": {r.customer_id: r.role for r in rows},
    }


# ── the access fixture ───────────────────────────────────────────────────────


class _World:
    pass


@pytest.fixture()
def world(db_session):
    from backend.models.customer_knowledge import CustomerKnowledge
    from backend.models.sales_access import InsideSalesAssignment, SalesReporting
    from backend.models.use_case import Customer, Department, UseCase

    w = _World()
    # customers: A1/A2 on team A, B1 on team B, ORPHAN has no assignment at all.
    for key, name in [("a1", "CustA1"), ("a2", "CustA2"), ("b1", "CustB1"), ("orphan", "CustOrphan")]:
        c = Customer(name=name, description=name)
        db_session.add(c)
        db_session.flush()
        setattr(w, key, c)

    mgr_a = _mk_user(db_session, "mgr_a", sales_role="sales_manager")
    mgr_b = _mk_user(db_session, "mgr_b", sales_role="sales_manager")
    rep_a1 = _mk_user(db_session, "rep_a1", sales_role="rep")
    rep_a2 = _mk_user(db_session, "rep_a2", sales_role="rep")
    rep_b1 = _mk_user(db_session, "rep_b1", sales_role="rep")
    inside = _mk_user(db_session, "inside_1", sales_role="inside_sales")
    aud_scoped = _mk_user(db_session, "aud_scoped", sales_role="auditor")
    aud_org = _mk_user(db_session, "aud_org", sales_role="auditor")
    legacy_owner = _mk_user(db_session, "legacy_owner")      # no sales_role at all
    legacy_member = _mk_user(db_session, "legacy_member")    # no sales_role at all
    ps_admin = _mk_user(db_session, "ps_admin_1", role="ps_admin")
    pending = _mk_user(db_session, "pending_1", sales_role="rep", approved=0)
    inactive = _mk_user(db_session, "inactive_1", sales_role="rep", is_active=0)
    outsider = _mk_user(db_session, "outsider_1")
    for k, u in dict(mgr_a=mgr_a, mgr_b=mgr_b, rep_a1=rep_a1, rep_a2=rep_a2, rep_b1=rep_b1,
                     inside=inside, aud_scoped=aud_scoped, aud_org=aud_org,
                     legacy_owner=legacy_owner, legacy_member=legacy_member,
                     ps_admin=ps_admin, pending=pending, inactive=inactive,
                     outsider=outsider).items():
        setattr(w, k, u)

    # hierarchy
    db_session.add_all([
        SalesReporting(rep_user_id=rep_a1.id, manager_user_id=mgr_a.id),
        SalesReporting(rep_user_id=rep_a2.id, manager_user_id=mgr_a.id),
        SalesReporting(rep_user_id=rep_b1.id, manager_user_id=mgr_b.id),
    ])
    # ownership + support
    _grant(db_session, w.a1, rep_a1, "owner")
    _grant(db_session, w.a2, rep_a2, "owner")
    _grant(db_session, w.b1, rep_b1, "owner")
    _grant(db_session, w.a2, rep_a1, "member")            # multi-rep support: rep_a1 supports A2
    _grant(db_session, w.a1, inside, "member")             # inside-sales supports A1 only
    db_session.add(InsideSalesAssignment(inside_sales_user_id=inside.id, customer_id=w.a1.id, rep_user_id=rep_a1.id))
    _grant(db_session, w.a1, aud_scoped, "auditor")        # scoped auditor: A1 only
    for c in (w.a1, w.a2, w.b1):                            # org-wide auditor
        _grant(db_session, c, aud_org, "auditor")
    _grant(db_session, w.a1, legacy_owner, "owner")
    _grant(db_session, w.a1, legacy_member, "member")
    _grant(db_session, w.a1, pending, "owner")
    _grant(db_session, w.a1, inactive, "owner")

    # records on A1 and B1
    uc_a1 = UseCase(title="UC A1", customer_id=w.a1.id)
    uc_b1 = UseCase(title="UC B1", customer_id=w.b1.id)
    dept = Department(name="Ops", customer_id=w.a1.id)
    db_session.add_all([uc_a1, uc_b1, dept])
    db_session.flush()
    w.uc_a1, w.uc_b1, w.dept_a1 = uc_a1, uc_b1, dept
    k = CustomerKnowledge(
        customer_id=w.a1.id, knowledge_type="markdown", file_name="n.md",
        file_data=b"# notes", uploaded_at=datetime.now(UTC),
        extracted_text="notes",
    )
    db_session.add(k)
    db_session.commit()
    w.knowledge_a1 = k
    return w


@pytest.fixture()
def seeded(client, db_session, world):
    """Admin-seeded dependent records on A1 (note, technologies, dependency,
    engagement, comment, prediction) so per-id mutation routes have targets."""
    from backend.models.use_case import AIPrediction

    w, h = world, _admin_headers(db_session)
    r = client.post(f"/api/customers/{w.a1.id}/sales-notes/", headers=h, json={
        "category": "discovery", "title": "n", "content": "c"})
    assert r.status_code == 201, r.text
    w.note_id = r.json()["id"]
    tech = []
    for nm in ("T1", "T2"):
        r = client.post(f"/api/customers/{w.a1.id}/technology/", headers=h,
                        json={"name": nm, "category": "software"})
        assert r.status_code == 201, r.text
        tech.append(r.json()["id"])
    w.tech_id = tech[0]
    r = client.post(f"/api/customers/{w.a1.id}/technology-dependencies/", headers=h, json={
        "source_id": tech[0], "target_id": tech[1], "relationship_type": "depends_on"})
    assert r.status_code == 201, r.text
    w.dep_id = r.json()["id"]
    r = client.post(f"/api/customers/{w.a1.id}/third-party-services/", headers=h, json={
        "vendor_name": "V", "service_category": "technical", "description": "d"})
    assert r.status_code == 201, r.text
    w.tps_id = r.json()["id"]
    r = client.post(f"/api/use-cases/{w.uc_a1.id}/comments/", headers=h, json={
        "content": "hello", "user_name": "admin"})
    assert r.status_code == 201, r.text
    w.comment_id = r.json()["id"]
    p = AIPrediction(use_case_id=w.uc_a1.id, customer_id=w.a1.id, horizon_days=30, predicted_score=50.0)
    db_session.add(p)
    db_session.commit()
    w.prediction_id = p.id
    return w


def _mutations(w):
    """Every customer-data mutation route gated in phase 3b, on customer A1.

    (label, method, url, request kwargs). Targets all live on A1 so one
    junction role decides the outcome for the whole list.
    """
    a1 = w.a1
    md = ("n.md", io.BytesIO(b"# hello"), "text/markdown")
    return [
        ("knowledge.upload", "post", "/api/customer-knowledge/",
         dict(files={"file": md}, data={"customer_id": str(a1.id)})),
        ("knowledge.update", "put", f"/api/customer-knowledge/{w.knowledge_a1.id}", dict(json={"category": "x"})),
        ("knowledge.reprocess", "post", f"/api/customer-knowledge/{w.knowledge_a1.id}/reprocess", {}),
        ("knowledge.enrich", "post", f"/api/customer-knowledge/{w.knowledge_a1.id}/enrich", {}),
        ("knowledge.delete", "delete", f"/api/customer-knowledge/{w.knowledge_a1.id}", {}),
        ("analytics.insight", "post", f"/api/analytics/readiness-insight/generate/?customer_id={a1.id}", {}),
        ("analytics.predict", "post", f"/api/analytics/predictions/generate/?use_case_id={w.uc_a1.id}", {}),
        ("analytics.delete_prediction", "delete", f"/api/analytics/predictions/{w.prediction_id}/", {}),
        ("comments.create", "post", f"/api/use-cases/{w.uc_a1.id}/comments/", dict(json={"content": "x"})),
        ("comments.update", "put", f"/api/use-cases/comments/{w.comment_id}/", dict(json={"content": "y"})),
        ("comments.delete", "delete", f"/api/use-cases/comments/{w.comment_id}/", {}),
        ("notes.create", "post", f"/api/customers/{a1.id}/sales-notes/",
         dict(json={"category": "discovery", "title": "t", "content": "c"})),
        ("notes.update", "put", f"/api/sales-notes/{w.note_id}/", dict(json={"title": "z"})),
        ("notes.delete", "delete", f"/api/sales-notes/{w.note_id}/", {}),
        ("use_cases.create", "post", "/api/use-cases/", dict(json={"title": "n", "customer_id": a1.id})),
        ("use_cases.update", "put", f"/api/use-cases/{w.uc_a1.id}/", dict(json={"title": "n"})),
        ("use_cases.delete", "delete", f"/api/use-cases/{w.uc_a1.id}/", {}),
        ("tech.create", "post", f"/api/customers/{a1.id}/technology/", dict(json={"name": "N", "category": "software"})),
        ("tech.update", "put", f"/api/technology/{w.tech_id}/", dict(json={"name": "N2"})),
        ("tech.delete", "delete", f"/api/technology/{w.tech_id}/", {}),
        ("deps.update", "put", f"/api/technology-dependencies/{w.dep_id}/", dict(json={"confidence": 0.5})),
        ("deps.delete", "delete", f"/api/technology-dependencies/{w.dep_id}/", {}),
        ("tps.create", "post", f"/api/customers/{a1.id}/third-party-services/",
         dict(json={"vendor_name": "V", "service_category": "technical", "description": "d"})),
        ("tps.update", "put", f"/api/third-party-services/{w.tps_id}/", dict(json={"description": "e"})),
        ("tps.delete", "delete", f"/api/third-party-services/{w.tps_id}/", {}),
        ("projections.create", "post", f"/api/customers/{a1.name}/projections/", {}),
        ("projections.delete", "delete", f"/api/customers/{a1.name}/projections/", {}),
        ("departments.create", "post", "/api/departments/", dict(json={"name": "New", "customer_name": a1.name})),
        ("departments.update", "put", f"/api/departments/{w.dept_a1.id}/", dict(json={"name": "Renamed"})),
        ("departments.delete", "delete", f"/api/departments/{w.dept_a1.id}/", {}),
        ("assessments.create", "post", f"/api/customers/{a1.name}/assessments/", dict(json={"name": "Round 2"})),
        ("assessments.template", "post", f"/api/customers/{a1.name}/assessments/from-template/",
         dict(json={"template_id": "customer-support"})),
        ("assessments.archive", "post", f"/api/customers/{a1.name}/assessments/1/archive/", {}),
        ("scoring.score", "post", "/api/scoring/", dict(json={"use_case_id": w.uc_a1.id})),
        ("scoring.manual", "post", "/api/scoring/manual/",
         dict(json={"use_case_id": w.uc_a1.id, "scores": {}, "overall_score": 5.0})),
        ("bulk.score", "post", "/api/bulk/score-multiple/", dict(json=[w.uc_a1.id])),
        ("bulk.template", "post", "/api/bulk/create-from-template/",
         dict(json={"template_id": "customer-support", "title": "t", "department": "d", "customer_id": a1.id})),
        ("sharing.add", "post", f"/api/customers/{a1.name}/users/?user_id={w.outsider.id}&role=member", {}),
        ("sharing.role", "put", f"/api/customers/{a1.name}/users/{w.legacy_member.id}/?role=owner", {}),
        ("sharing.remove", "delete", f"/api/customers/{a1.name}/users/{w.legacy_member.id}/", {}),
    ]


def _call(client, headers, spec):
    _label, method, url, kwargs = spec
    kwargs = dict(kwargs)
    if "files" in kwargs:  # a fresh stream per call
        kwargs["files"] = {"file": ("n.md", io.BytesIO(b"# hello"), "text/markdown")}
    return getattr(client, method)(url, headers=headers, **kwargs)


LABELS = [m[0] for m in _mutations(type("W", (), {
    "a1": type("C", (), {"id": 1, "name": "x"}), "knowledge_a1": type("K", (), {"id": 1}),
    "uc_a1": type("U", (), {"id": 1}), "prediction_id": 1, "comment_id": 1, "note_id": 1,
    "tech_id": 1, "dep_id": 1, "tps_id": 1, "dept_a1": type("D", (), {"id": 1}),
    "outsider": type("O", (), {"id": 1}), "legacy_member": type("M", (), {"id": 1}),
})())]


# ── (d) auditor is read-only on every mutation path ──────────────────────────


class TestAuditorReadOnlyEverywhere:
    @pytest.mark.parametrize("who", ["aud_scoped", "aud_org"])
    @pytest.mark.parametrize("label", LABELS)
    def test_every_mutation_403(self, client, seeded, who, label):
        spec = next(m for m in _mutations(seeded) if m[0] == label)
        r = _call(client, _headers(who), spec)
        if label == "bulk.score":
            # RBAC model: the auditor write-block middleware rejects the
            # mutating verb outright (403) before the per-item envelope.
            assert r.status_code == 403
            return
        assert r.status_code == 403, f"{who} {label}: expected 403, got {r.status_code} {r.text[:160]}"

    def test_auditor_state_unchanged_after_denied_writes(self, client, db_session, seeded):
        from backend.models.customer_knowledge import CustomerKnowledge
        from backend.models.sales_note import SalesNote
        from backend.models.use_case import UseCase

        for spec in _mutations(seeded):
            _call(client, _headers("aud_scoped"), spec)
        db_session.expire_all()
        assert db_session.query(CustomerKnowledge).filter_by(id=seeded.knowledge_a1.id).count() == 1
        assert db_session.query(SalesNote).filter_by(id=seeded.note_id).count() == 1
        assert db_session.query(UseCase).filter_by(id=seeded.uc_a1.id).one().title == "UC A1"

    def test_auditor_reads_stay_200(self, client, seeded):
        w, h = seeded, _headers("aud_scoped")
        for url in (
            f"/api/customer-knowledge/?customer_id={w.a1.id}",
            f"/api/customer-knowledge/{w.knowledge_a1.id}",
            f"/api/customers/{w.a1.id}/sales-notes/",
            f"/api/sales-notes/{w.note_id}/",
            f"/api/customers/{w.a1.id}/technology/",
            f"/api/technology/{w.tech_id}/",
            f"/api/customers/{w.a1.id}/technology-dependencies/",
            f"/api/customers/{w.a1.id}/third-party-services/",
            f"/api/use-cases/{w.uc_a1.id}/comments/",
            f"/api/use-cases/{w.uc_a1.id}/",
            f"/api/customers/{w.a1.name}/",
        ):
            r = client.get(url, headers=h)
            assert r.status_code == 200, f"{url}: {r.status_code} {r.text[:160]}"

    def test_auditor_reads_other_customer(self, client, seeded):
        # RBAC model: an in-role auditor reads the entire
        # application (was: limited to junction grants).
        r = client.get(f"/api/customers/{seeded.b1.id}/sales-notes/", headers=_headers("aud_scoped"))
        assert r.status_code == 200


# ── per-surface auditor write gap (mirrors TestAuditorWriteGap) ──────────────


class TestPerSurfaceAuditorWriteGap:
    """Each gated surface: auditor 403 + legacy owner/member NOT locked out."""

    def test_knowledge(self, client, seeded):
        w = seeded
        assert _call(client, _headers("aud_scoped"), _mutations(w)[0]).status_code == 403
        r = client.put(f"/api/customer-knowledge/{w.knowledge_a1.id}", headers=_headers("legacy_owner"),
                       json={"category": "x"})
        assert r.status_code == 200, r.text
        r = client.put(f"/api/customer-knowledge/{w.knowledge_a1.id}", headers=_headers("legacy_member"),
                       json={"category": "y"})
        assert r.status_code == 200, r.text
        r = client.put(f"/api/customer-knowledge/{w.knowledge_a1.id}", headers=_headers("aud_scoped"),
                       json={"category": "z"})
        assert r.status_code == 403

    def test_comments(self, client, seeded):
        w = seeded
        for who, code in (("aud_scoped", 403), ("legacy_owner", 201), ("legacy_member", 201)):
            r = client.post(f"/api/use-cases/{w.uc_a1.id}/comments/", headers=_headers(who), json={"content": "c"})
            assert r.status_code == code, f"{who}: {r.status_code} {r.text[:120]}"

    def test_sales_notes(self, client, seeded):
        w = seeded
        body = {"category": "discovery", "title": "t", "content": "c"}
        for who, code in (("aud_scoped", 403), ("legacy_owner", 201), ("legacy_member", 201)):
            r = client.post(f"/api/customers/{w.a1.id}/sales-notes/", headers=_headers(who), json=body)
            assert r.status_code == code, f"{who}: {r.status_code} {r.text[:120]}"
        assert client.put(f"/api/sales-notes/{w.note_id}/", headers=_headers("aud_scoped"),
                          json={"title": "x"}).status_code == 403
        assert client.delete(f"/api/sales-notes/{w.note_id}/", headers=_headers("aud_scoped")).status_code == 403
        assert client.delete(f"/api/sales-notes/{w.note_id}/", headers=_headers("legacy_owner")).status_code == 204

    def test_use_cases(self, client, seeded):
        w = seeded
        assert client.put(f"/api/use-cases/{w.uc_a1.id}/", headers=_headers("aud_scoped"),
                          json={"title": "x"}).status_code == 403
        assert client.put(f"/api/use-cases/{w.uc_a1.id}/", headers=_headers("legacy_member"),
                          json={"title": "m"}).status_code == 200
        assert client.post("/api/use-cases/", headers=_headers("aud_scoped"),
                           json={"title": "n", "customer_id": w.a1.id}).status_code == 403
        assert client.post("/api/use-cases/", headers=_headers("legacy_owner"),
                           json={"title": "n", "customer_id": w.a1.id}).status_code == 201

    def test_technology(self, client, seeded):
        w = seeded
        body = {"name": "X", "category": "software"}
        assert client.post(f"/api/customers/{w.a1.id}/technology/", headers=_headers("aud_scoped"),
                           json=body).status_code == 403
        assert client.post(f"/api/customers/{w.a1.id}/technology/", headers=_headers("legacy_member"),
                           json=body).status_code == 201
        assert client.delete(f"/api/technology/{w.tech_id}/", headers=_headers("aud_scoped")).status_code == 403
        assert client.delete(f"/api/technology-dependencies/{w.dep_id}/",
                             headers=_headers("aud_scoped")).status_code == 403

    def test_third_party_services(self, client, seeded):
        w = seeded
        body = {"vendor_name": "V2", "service_category": "technical", "description": "d"}
        assert client.post(f"/api/customers/{w.a1.id}/third-party-services/", headers=_headers("aud_scoped"),
                           json=body).status_code == 403
        assert client.post(f"/api/customers/{w.a1.id}/third-party-services/", headers=_headers("legacy_owner"),
                           json=body).status_code == 201
        assert client.put(f"/api/third-party-services/{w.tps_id}/", headers=_headers("aud_scoped"),
                          json={"description": "x"}).status_code == 403
        up = client.post(f"/api/third-party-services/{w.tps_id}/documents/", headers=_headers("aud_scoped"),
                         files={"file": ("a.txt", io.BytesIO(b"x"), "text/plain")},
                         data={"document_type": "sow"})
        assert up.status_code == 403

    def test_scoring(self, client, seeded):
        w = seeded
        h = _headers("aud_scoped")
        assert client.post("/api/scoring/", headers=h, json={"use_case_id": w.uc_a1.id}).status_code == 403
        assert client.post("/api/scoring/manual/", headers=h, json={
            "use_case_id": w.uc_a1.id, "scores": {}, "overall_score": 5.0}).status_code == 403
        # a legacy owner is not rejected by the resolver gate
        r = client.post("/api/scoring/manual/", headers=_headers("legacy_owner"), json={
            "use_case_id": w.uc_a1.id, "scores": {}, "overall_score": 5.0})
        assert GATE_DETAIL not in r.text

    def test_bulk(self, client, seeded):
        w = seeded
        # RBAC model: auditor mutating verbs are 403 at the middleware.
        r = client.post("/api/bulk/score-multiple/", headers=_headers("aud_scoped"), json=[w.uc_a1.id])
        assert r.status_code == 403
        r = client.post("/api/bulk/create-from-template/", headers=_headers("aud_scoped"), json={
            "template_id": "customer-support", "title": "t", "department": "d", "customer_id": w.a1.id})
        assert r.status_code == 403
        r = client.post("/api/bulk/create-from-template/", headers=_headers("legacy_owner"), json={
            "template_id": "customer-support", "title": "t", "department": "d", "customer_id": w.a1.id})
        assert r.status_code == 200, r.text

    def test_departments_and_sharing_need_owner(self, client, seeded):
        w = seeded
        assert client.put(f"/api/departments/{w.dept_a1.id}/", headers=_headers("legacy_member"),
                          json={"name": "Nope"}).status_code == 403
        assert client.put(f"/api/departments/{w.dept_a1.id}/", headers=_headers("legacy_owner"),
                          json={"name": "Yes"}).status_code == 200
        # team mutations need owner/admin on the customer; a member is out
        # of scope for that surface -> 404
        assert client.post(f"/api/customers/{w.a1.name}/users/?user_id={w.outsider.id}&role=member",
                           headers=_headers("legacy_member")).status_code == 404
        assert client.post(f"/api/customers/{w.a1.name}/users/?user_id={w.outsider.id}&role=member",
                           headers=_headers("legacy_owner")).status_code == 200

    def test_projections_require_membership(self, client, seeded):
        """projections POST had no access check at all before 3b."""
        # projections generate needs owner/admin or edit on the customer —
        # outsider_1 is out of scope -> the same 404 as a missing customer
        # The scoped auditor is a global write-blocked identity:
        # the app-wide middleware 403 fires before the route (H4 convention).
        r = client.post(f"/api/customers/{seeded.a1.name}/projections/", headers=_headers("outsider_1"))
        assert r.status_code == 404
        assert client.delete(f"/api/customers/{seeded.a1.name}/projections/",
                             headers=_headers("aud_scoped")).status_code == 403


# ── legacy preservation: system admin ─────────────────────────────────────────


class TestSystemAdminPreserved:
    def test_admin_still_writes_everywhere_it_did(self, client, db_session, seeded):
        h = _admin_headers(db_session)
        w = seeded
        assert client.put(f"/api/use-cases/{w.uc_a1.id}/", headers=h, json={"title": "adm"}).status_code == 200
        assert client.post(f"/api/customers/{w.b1.id}/sales-notes/", headers=h, json={
            "category": "discovery", "title": "t", "content": "c"}).status_code == 201
        assert client.post("/api/departments/", headers=h,
                           json={"name": "AdmDept", "customer_name": w.b1.name}).status_code == 201
        assert client.post("/api/use-cases/", headers=h,
                           json={"title": "n", "customer_id": w.orphan.id}).status_code == 201

    def test_resolver_admin_all_caps(self, db_session, world):
        # is_admin is exclusive: the dict built by auth carries is_admin=1.
        admin = {"username": "admin", "user_id": 1, "is_admin": 1, "customer_ids": [], "junction_roles": {}}
        for cap in sales_access.ALL_CAPS:
            assert sales_access.can(admin, db_session, cap, world.orphan.id)


# ── (a) a rep cannot acquire another team's customer ─────────────────────────


class TestRepCannotAcquireOtherTeamCustomer:
    def test_cannot_add_self_as_owner_to_other_team(self, client, db_session, seeded):
        w = seeded
        r = client.post(f"/api/customers/{w.b1.name}/users/?user_id={w.rep_a1.id}&role=owner",
                        headers=_headers("rep_a1"))
        # 404-first: b1 is out of scope for rep_a1 — same 404 as missing.
        assert r.status_code == 404
        r = client.put(f"/api/customers/{w.b1.name}/users/{w.rep_a1.id}/?role=owner", headers=_headers("rep_a1"))
        assert r.status_code == 404

    def test_cannot_write_other_team_records_by_id(self, client, seeded):
        w, h = seeded, _headers("rep_a1")
        # 404-first: every target below is out of scope for rep_a1 —
        # each is the same 404 as a missing record (no existence oracle).
        assert client.put(f"/api/use-cases/{w.uc_b1.id}/", headers=h, json={"title": "stolen"}).status_code == 404
        # a payload that moves another team's use case into the rep's customer
        # is refused before any scope check (R3), and nothing changes
        moved = client.put(f"/api/use-cases/{w.uc_b1.id}/", headers=h, json={"customer_id": w.a1.id})
        assert moved.status_code == 422
        assert moved.json()["detail"] == "Use case customer cannot be changed."
        assert client.post("/api/use-cases/", headers=h,
                           json={"title": "n", "customer_id": w.b1.id}).status_code == 404
        assert client.post(f"/api/customers/{w.b1.id}/sales-notes/", headers=h, json={
            "category": "discovery", "title": "t", "content": "c"}).status_code == 404
        assert client.post("/api/customer-knowledge/", headers=h,
                           files={"file": ("n.md", io.BytesIO(b"# x"), "text/markdown")},
                           data={"customer_id": str(w.b1.id)}).status_code == 404

    def test_rep_scope_is_own_plus_supported_only(self, db_session, world):
        u = _user_dict(db_session, "rep_a1")
        assert sales_access.customer_scope(u, db_session) == {world.a1.id, world.a2.id}
        assert not sales_access.can(u, db_session, sales_access.CAP_EDIT, world.b1.id)
        assert not sales_access.can(u, db_session, sales_access.CAP_READ, world.orphan.id)

    def test_inside_assignment_is_role_gated_in_scope(self, db_session, world):
        # an InsideSalesAssignment held by a
        # NON-inside_sales user must not widen customer_scope — scope and
        # _access agree, so no listed-but-404 accounts.
        from backend.models.sales_access import InsideSalesAssignment

        db_session.add(InsideSalesAssignment(inside_sales_user_id=world.rep_a1.id,
                                             customer_id=world.b1.id,
                                             rep_user_id=world.rep_b1.id))
        db_session.flush()
        u = _user_dict(db_session, "rep_a1")
        assert world.b1.id not in sales_access.customer_scope(u, db_session)
        assert not sales_access.can(u, db_session, sales_access.CAP_READ, world.b1.id)
        # ...while the inside_sales holder gains the account in BOTH scope and can().
        db_session.add(InsideSalesAssignment(inside_sales_user_id=world.inside.id,
                                             customer_id=world.b1.id,
                                             rep_user_id=world.rep_b1.id))
        db_session.flush()
        u_in = _user_dict(db_session, "inside_1")
        assert world.b1.id in sales_access.customer_scope(u_in, db_session)
        assert sales_access.can(u_in, db_session, sales_access.CAP_READ, world.b1.id)

    def test_multi_rep_support_is_member_not_owner(self, db_session, world):
        u = _user_dict(db_session, "rep_a1")  # owner A1, supporting member on A2
        assert sales_access.can(u, db_session, sales_access.CAP_EDIT, world.a2.id)
        assert not sales_access.can(u, db_session, sales_access.CAP_MANAGE_TEAM, world.a2.id)
        assert not sales_access.can(u, db_session, sales_access.CAP_TRANSFER_OWNERSHIP, world.a2.id)
        assert sales_access.can(u, db_session, sales_access.CAP_MANAGE_TEAM, world.a1.id)


# ── (b) inside-sales ──────────────────────────────────────────────────────────


class TestInsideSalesLimits:
    def test_can_edit_assigned_customer(self, client, seeded):
        r = client.post(f"/api/customers/{seeded.a1.id}/sales-notes/", headers=_headers("inside_1"),
                        json={"category": "discovery", "title": "t", "content": "c"})
        assert r.status_code == 201, r.text

    def test_cannot_edit_unassigned_customer(self, client, seeded):
        # inside_1 is assigned to a1 only — a2/b1/orphan are out of scope:
        # the same 404 as a missing customer (404-first).
        for cid in (seeded.a2.id, seeded.b1.id, seeded.orphan.id):
            r = client.post(f"/api/customers/{cid}/sales-notes/", headers=_headers("inside_1"),
                            json={"category": "discovery", "title": "t", "content": "c"})
            assert r.status_code == 404, cid

    def test_cannot_transfer_delete_or_elevate(self, client, db_session, seeded):
        w, h = seeded, _headers("inside_1")
        # team mutations require owner/admin on the customer — inside_1 holds
        # neither, so those are out of scope (404-first); the
        # customer-level write denials are in-scope capability 403s.
        assert client.post(f"/api/customers/{w.a1.name}/users/?user_id={w.inside.id}&role=owner",
                           headers=h).status_code == 404
        assert client.put(f"/api/customers/{w.a1.name}/users/{w.inside.id}/?role=owner",
                          headers=h).status_code == 404
        assert client.delete(f"/api/customers/{w.a1.name}/", headers=h).status_code == 403
        assert client.put(f"/api/customers/{w.a1.name}/", headers=h, json={"description": "x"}).status_code == 403
        u = _user_dict(db_session, "inside_1")
        assert not sales_access.can(u, db_session, sales_access.CAP_TRANSFER_OWNERSHIP, w.a1.id)
        assert not sales_access.can(u, db_session, sales_access.CAP_MANAGE_TEAM, w.a1.id)
        assert not sales_access.can(u, db_session, sales_access.CAP_SYSTEM_ADMIN, w.a1.id)


# ── (c) manager scope ─────────────────────────────────────────────────────────


class TestManagerScope:
    def test_manager_sees_only_own_team(self, db_session, world):
        a = sales_access.customer_scope(_user_dict(db_session, "mgr_a"), db_session)
        b = sales_access.customer_scope(_user_dict(db_session, "mgr_b"), db_session)
        assert a == {world.a1.id, world.a2.id}
        assert b == {world.b1.id}
        assert world.orphan.id not in a | b

    def test_manager_capabilities_follow_scope(self, db_session, world):
        u = _user_dict(db_session, "mgr_a")
        assert sales_access.can(u, db_session, sales_access.CAP_EDIT, world.a1.id)
        assert sales_access.can(u, db_session, sales_access.CAP_MANAGE_TEAM, world.a2.id)
        assert not sales_access.can(u, db_session, sales_access.CAP_READ, world.b1.id)
        assert not sales_access.can(u, db_session, sales_access.CAP_EDIT, world.orphan.id)

    def test_manager_is_not_system_admin(self, db_session, world):
        u = _user_dict(db_session, "mgr_a")
        assert not sales_access.can(u, db_session, sales_access.CAP_SYSTEM_ADMIN)
        assert sales_access.effective_role(u) == "sales_manager"

    def test_manager_cannot_write_other_team_via_api(self, client, seeded):
        # 404-first: b1 is out of scope for mgr_a — same 404 as missing.
        r = client.put(f"/api/use-cases/{seeded.uc_b1.id}/", headers=_headers("mgr_a"), json={"title": "x"})
        assert r.status_code == 404

    def test_unassigned_customer_is_invisible_to_everyone_but_admin(self, db_session, world):
        for name in ("rep_a1", "rep_a2", "rep_b1", "mgr_a", "mgr_b", "inside_1", "aud_org", "aud_scoped",
                     "legacy_owner", "outsider_1", "ps_admin_1"):
            u = _user_dict(db_session, name)
            for cap in (sales_access.CAP_READ, sales_access.CAP_EDIT, sales_access.CAP_MANAGE_TEAM):
                if cap == sales_access.CAP_READ and name in ("aud_org", "aud_scoped"):
                    continue  # RBAC model: auditors read every account
                assert not sales_access.can(u, db_session, cap, world.orphan.id), (name, cap)


# ── (e) ps_admin confined to the third-party surface ─────────────────────────


class TestPsAdminConfined:
    def test_no_sales_capabilities(self, db_session, world):
        u = _user_dict(db_session, "ps_admin_1")
        for cap in sales_access.ALL_CAPS:
            assert not sales_access.can(u, db_session, cap, world.a1.id)
            assert not sales_access.can(u, db_session, cap, world.b1.id,
                                        section="notes", is_own_item=True)

    def test_third_party_surface_still_writes_cross_account(self, client, seeded):
        h = _headers("ps_admin_1")
        body = {"vendor_name": "PS", "service_category": "technical", "description": "d"}
        for cid in (seeded.a1.id, seeded.b1.id):
            r = client.post(f"/api/customers/{cid}/third-party-services/", headers=h, json=body)
            assert r.status_code == 201, (cid, r.text)
        assert client.put(f"/api/third-party-services/{seeded.tps_id}/", headers=h,
                          json={"description": "ps"}).status_code == 200
        assert client.delete(f"/api/third-party-services/{seeded.tps_id}/", headers=h).status_code == 204

    @pytest.mark.parametrize("label", [
        "knowledge.upload", "knowledge.update", "knowledge.delete", "notes.create", "notes.update",
        "use_cases.create", "use_cases.update", "use_cases.delete", "tech.create", "comments.create",
        "departments.create", "assessments.create", "scoring.manual", "sharing.add",
        "projections.create",
    ])
    def test_everything_else_denied(self, client, seeded, label):
        spec = next(m for m in _mutations(seeded) if m[0] == label)
        r = _call(client, _headers("ps_admin_1"), spec)
        # per-id routes answer 404 (no existence leak) for out-of-scope callers
        assert r.status_code in (403, 404), f"{label}: {r.status_code} {r.text[:160]}"
        assert r.status_code != 404 or "not found" in r.text.lower()


# ── (f) pending / inactive identities ────────────────────────────────────────


class TestPendingAndInactiveDenied:
    def test_pending_cannot_log_in(self, client):
        r = client.post("/api/auth/login/", json={"username": "pending_1", "password": "pending_1"})
        assert r.status_code in (401, 403)
        assert "token" not in r.json()

    def test_inactive_identity_cannot_write(self, client, seeded):
        h = _headers("inactive_1")
        for label in ("notes.create", "use_cases.update", "knowledge.update", "tech.create", "tps.create"):
            spec = next(m for m in _mutations(seeded) if m[0] == label)
            r = _call(client, h, spec)
            # per-id routes answer 404 (no existence leak) when out of scope
            assert r.status_code in (401, 403, 404), f"{label}: {r.status_code}"

    def test_inactive_resolves_to_no_scope(self, db_session, world):
        from backend.models.use_case import User

        # auth drops an inactive user to a bare {"username": ...} identity
        bare = {"username": "inactive_1"}
        assert sales_access.customer_scope(bare, db_session) == set()
        for cap in (sales_access.CAP_READ, sales_access.CAP_EDIT):
            assert not sales_access.can(bare, db_session, cap, world.a1.id)
        assert db_session.query(User).filter_by(username="inactive_1").one().is_active == 0


# ── (g) revocation ────────────────────────────────────────────────────────────


class TestRevocation:
    def test_removing_junction_revokes_write(self, client, db_session, seeded):
        from backend.models.use_case import CustomerUser

        w = seeded
        url = f"/api/customers/{w.a1.id}/sales-notes/"
        body = {"category": "discovery", "title": "t", "content": "c"}
        assert client.post(url, headers=_headers("legacy_member"), json=body).status_code == 201
        db_session.query(CustomerUser).filter_by(customer_id=w.a1.id, user_id=w.legacy_member.id).delete()
        db_session.commit()
        # revocation = out of scope = the same 404 as a missing customer
        assert client.post(url, headers=_headers("legacy_member"), json=body).status_code == 404

    def test_downgrade_to_auditor_revokes_write_keeps_read(self, client, db_session, seeded):
        from backend.models.use_case import CustomerUser

        w = seeded
        url = f"/api/customers/{w.a1.id}/sales-notes/"
        body = {"category": "discovery", "title": "t", "content": "c"}
        assert client.post(url, headers=_headers("legacy_owner"), json=body).status_code == 201
        db_session.query(CustomerUser).filter_by(
            customer_id=w.a1.id, user_id=w.legacy_owner.id).update({"role": "auditor"})
        db_session.commit()
        assert client.post(url, headers=_headers("legacy_owner"), json=body).status_code == 403
        assert client.get(url, headers=_headers("legacy_owner")).status_code == 200

    def test_removing_inside_sales_assignment_revokes_scope(self, db_session, world):
        from backend.models.sales_access import InsideSalesAssignment
        from backend.models.use_case import CustomerUser

        u = _user_dict(db_session, "inside_1")
        assert sales_access.can(u, db_session, sales_access.CAP_EDIT, world.a1.id)
        db_session.query(InsideSalesAssignment).filter_by(inside_sales_user_id=world.inside.id).delete()
        db_session.query(CustomerUser).filter_by(user_id=world.inside.id).delete()
        db_session.commit()
        u = _user_dict(db_session, "inside_1")
        assert sales_access.customer_scope(u, db_session) == set()
        assert not sales_access.can(u, db_session, sales_access.CAP_EDIT, world.a1.id)

    def test_removing_report_removes_manager_scope(self, db_session, world):
        from backend.models.sales_access import SalesReporting

        db_session.query(SalesReporting).filter_by(rep_user_id=world.rep_a2.id).delete()
        db_session.commit()
        scope = sales_access.customer_scope(_user_dict(db_session, "mgr_a"), db_session)
        assert world.a2.id not in scope and world.a1.id in scope


@pytest.fixture()
def section_member(db_session, world):
    """Inside-sales membership without a legacy junction/assignment bypass."""
    from backend.models.account_membership import AccountMembership
    from backend.models.sales_access import InsideSalesAssignment
    from backend.models.use_case import CustomerUser

    db_session.query(CustomerUser).filter_by(user_id=world.inside.id).delete()
    db_session.query(InsideSalesAssignment).filter_by(inside_sales_user_id=world.inside.id).delete()
    row = AccountMembership(customer_id=world.a1.id, user_id=world.inside.id, role="inside_sales",
                            section_grants={"notes": "contribute"})
    db_session.add(row)
    db_session.commit()
    return row


@pytest.mark.parametrize("grants, expected", [
    ({"notes": "contribute"}, 201),
    ({"intel_uploads": "contribute"}, 403),
    ({"notes": "read"}, 403),
    ({}, 403),
])
def test_notes_requires_its_section_and_knowledge_stays_unsectioned(
    client, db_session, world, section_member, grants, expected,
):
    from backend.services.membership_service import actor_context

    section_member.section_grants = grants
    db_session.commit()
    context = actor_context(db_session, world.inside.id)
    assert not sales_access.can(context, db_session, sales_access.CAP_KNOWLEDGE, world.a1.id)
    headers = _headers("inside_1")
    url = f"/api/customers/{world.a1.id}/sales-notes/"
    assert client.get(url, headers=headers).status_code == 200
    response = client.post(url, headers=headers,
                           json={"category": "discovery", "title": "Synthetic note", "content": "Synthetic"})
    assert response.status_code == expected, response.text
    knowledge = client.post("/api/customer-knowledge/", headers=headers,
                            files={"file": ("synthetic.md", b"# Synthetic", "text/markdown")},
                            data={"customer_id": str(world.a1.id)})
    assert knowledge.status_code == 403


@pytest.mark.parametrize("author", ["inside_1", "rep_a1"])
def test_notes_same_write_rights_for_own_and_other_authors(
    client, db_session, world, section_member, author,
):
    headers = _headers("inside_1")
    response = client.post(f"/api/customers/{world.a1.id}/sales-notes/", headers=headers,
                           json={"category": "discovery", "title": "Synthetic note",
                                 "content": "Synthetic", "author": author})
    assert response.status_code == 201, response.text
    note_url = f"/api/sales-notes/{response.json()['id']}/"
    assert client.put(note_url, headers=headers, json={"content": "Updated"}).status_code == 200
    section_member.section_grants = {"notes": "read"}
    db_session.commit()
    assert client.put(note_url, headers=headers, json={"content": "Forbidden"}).status_code == 403
    assert client.delete(note_url, headers=headers).status_code == 403
    section_member.section_grants = {"notes": "contribute"}
    db_session.commit()
    assert client.delete(note_url, headers=headers).status_code == 204


@pytest.mark.parametrize("revocation", ["removed", "expired"])
def test_notes_grant_revocation_uses_live_db_with_same_token(
    client, db_session, world, section_member, revocation,
):
    from datetime import timedelta

    headers = _headers("inside_1")
    url = f"/api/customers/{world.a1.id}/sales-notes/"
    payload = {"category": "discovery", "title": "Synthetic", "content": "Synthetic"}
    assert client.post(url, headers=headers, json=payload).status_code == 201
    if revocation == "removed":
        section_member.section_grants = {}
    else:
        section_member.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()
    # grant gone (removed) or expired = the notes write capability is revoked.
    # "removed": inside_1 keeps the a1 assignment (in scope) -> exact 403.
    # "expired": the grant row no longer counts at all (out of scope) -> 404
    # (404-first).
    assert client.post(url, headers=headers, json=payload).status_code == (403 if revocation == "removed" else 404)


def test_section_grant_updates_do_not_create_legacy_membership(client, db_session, world):
    from backend.models.account_membership import AccountMembership
    from backend.models.use_case import CustomerUser

    # The grant path may create its inside_sales grant row, but must not
    # create a CustomerUser junction or any owner/co-owner membership.
    target = world.outsider.id
    url = f"/api/customers/{world.a1.name}/memberships/{target}/grants/"
    before_junctions = [(r.id, r.customer_id, r.user_id, r.role) for r in db_session.query(CustomerUser)]
    headers = _admin_headers(db_session)
    assert client.put(url, headers=headers, json={"section_grants": {"notes": "read"}}).status_code == 200
    db_session.expire_all()
    before_memberships = [(r.id, r.customer_id, r.user_id, r.role) for r in db_session.query(AccountMembership)]
    assert [(r.customer_id, r.role) for r in db_session.query(AccountMembership).filter_by(user_id=target)] == [
        (world.a1.id, "inside_sales")]
    assert client.put(url, headers=headers,
                      json={"section_grants": {"notes": "contribute"}}).status_code == 200
    db_session.expire_all()
    assert [(r.id, r.customer_id, r.user_id, r.role) for r in db_session.query(CustomerUser)] == before_junctions
    assert [(r.id, r.customer_id, r.user_id, r.role) for r in db_session.query(AccountMembership)] == before_memberships
    assert db_session.query(CustomerUser).filter_by(user_id=target).count() == 0


@pytest.mark.parametrize("who", ["aud_scoped", "aud_org"])
def test_auditor_cannot_write_notes_knowledge_or_intel_upload(client, db_session, world, who):
    from backend.routes.customer_knowledge import _require_write as knowledge_gate
    from backend.routes.sales_notes import _require_write as notes_gate
    from backend.services.membership_service import actor_context
    from fastapi import HTTPException

    context = actor_context(db_session, getattr(world, who).id)
    # Route gates also deny writes if the middleware is not involved.
    for gate in (knowledge_gate, notes_gate):
        with pytest.raises(HTTPException) as exc:
            gate(context, db_session, world.a1.id)
        assert exc.value.status_code == 403
    response = client.post("/api/rep-intelligence/", headers=_headers(who),
                           files={"file": ("synthetic.csv",
                                           b"customer_name,technology_name\nCustA1,Platform\n", "text/csv")})
    assert response.status_code == 403


@pytest.mark.parametrize("context, expected", [
    ({"junction_roles": {1: "owner"}}, True),
    ({"junction_roles": {1: "member"}}, True),
    ({"membership_roles": {1: ["sales_ops"]}}, True),
    ({"membership_roles": {1: ["inside_sales"]}}, False),
    ({"membership_roles": {1: ["inside_sales"]}, "section_grants": {1: {"contacts": "read"}}}, False),
    ({"membership_roles": {1: ["inside_sales"]}, "section_grants": {1: {"contacts": "contribute"}}}, True),
    ({"sales_role": "auditor", "junction_roles": {1: "owner"}}, False),
    ({"role": "ps_admin", "junction_roles": {1: "owner"}}, False),
    ({"is_admin": 1}, True),
])
def test_contacts_capability(context, expected):
    user = {"username": "synthetic_contact_actor", "customer_ids": [1], "membership_roles": {}, **context}
    assert sales_access.CAP_CONTACTS in sales_access.ALL_CAPS
    assert sales_access.can(user, None, sales_access.CAP_CONTACTS, 1, section="contacts") is expected


@pytest.mark.parametrize("context, expected", [
    ({"junction_roles": {1: "owner"}}, True),
    ({"junction_roles": {1: "member"}}, True),
    ({"junction_roles": {1: "auditor"}}, False),
    ({"membership_roles": {1: ["primary_owner"]}}, True),
    ({"membership_roles": {1: ["co_owner"]}}, True),
    ({"membership_roles": {1: ["sales_ops"]}}, True),
    ({"membership_roles": {1: ["inside_sales"]}}, False),
    ({"membership_roles": {1: ["inside_sales"]}, "section_grants": {1: {"activities": "read", "tasks": "read"}}}, False),
    ({"membership_roles": {1: ["inside_sales"]}, "section_grants": {1: {"activities": "contribute", "tasks": "contribute"}}}, True),
    ({"sales_role": "auditor", "junction_roles": {1: "owner"}}, False),
    ({"role": "ps_admin", "junction_roles": {1: "owner"}}, False),
    ({"is_admin": 1}, True),
])
@pytest.mark.parametrize("capability", (sales_access.CAP_ACTIVITIES, sales_access.CAP_TASKS))
def test_engagement_capability_matrix(context, expected, capability):
    user = {"username": "synthetic_engagement_actor", "customer_ids": [1], "membership_roles": {}, **context}
    assert capability in sales_access.ALL_CAPS
    assert sales_access.can(user, None, capability, 1, section=capability) is expected


def test_h5_capability_summary_and_sections():
    from backend.models.account_membership import ACCOUNT_SECTIONS

    assert ACCOUNT_SECTIONS == ("overview", "contacts", "opportunities", "notes", "intel_uploads",
                                "activities", "competitors", "forecasts", "tasks", "strategy")
    assert sales_access.ALL_CAPS[-3:] == ("opportunities", "forecasts", "competitors")  # reserved sections
    assert set(sales_access.summary({"is_admin": 1}, None)["capabilities"]) == set(sales_access.ALL_CAPS)


def test_sql_read_policy_matches_central_resolver(db_session, world):
    from backend.models.use_case import Customer, User

    # All existing matrix identities include manager/team, legacy assignments,
    # auditor, ps_admin, and explicit memberships. Both paths must agree.
    for user in db_session.query(User).all():
        context = _user_dict(db_session, user.username)
        sql_ids = {cid for (cid,) in db_session.query(Customer.id).join(User, User.id == user.id).filter(
            sales_access.account_read_predicate(User, Customer.id))}
        policy_ids = {cid for (cid,) in db_session.query(Customer.id) if sales_access.can(
            context, db_session, sales_access.CAP_READ, cid)}
        assert sql_ids == policy_ids, user.username


@pytest.mark.parametrize("role", ("primary_owner", "co_owner", "sales_ops", "inside_sales"))
@pytest.mark.parametrize("expired", (False, True))
def test_sql_read_policy_membership_aliases_and_expiration(db_session, world, role, expired):
    from datetime import timedelta

    from backend.models.account_membership import AccountMembership
    from backend.models.use_case import Customer, User

    target = world.outsider
    db_session.add(AccountMembership(user_id=target.id, customer_id=world.a1.id, role=role,
        expires_at=datetime.now(UTC) + timedelta(days=-1 if expired else 1)))
    db_session.commit()
    sql_ids = {cid for (cid,) in db_session.query(Customer.id).join(User, User.id == target.id).filter(
        sales_access.account_read_predicate(User, Customer.id))}
    context = _user_dict(db_session, target.username)
    assert (world.a1.id in sql_ids) == sales_access.can(context, db_session, sales_access.CAP_READ, world.a1.id) == (not expired)
