"""Customer Intelligence graph projection (F3) tests.

Verifies build_customer_intelligence_graph (PLAN_FEATURE_ENHANCMENTS.md):
- central Customer node + domain hub nodes (Customer -> Domain -> Entity)
- deterministic top-N per domain with the active limits reported
- technology-dependency edges present for stored TechnologyDependency rows
- cross-domain links from AUTHORITATIVE references only (sales-note
  technology junctions, opportunity evidence refs)
- canonical orientation + deduplication: no mirrored duplicate links,
  stable link ids, unique node ids
- no fabricated entities (every node maps to a real record or the
  deterministic synthesis; sparse customers degrade cleanly)
- route auth: 401 unauthenticated, 403 out-of-scope, 404 missing
  customer, member + admin 200, cross-customer isolation.
"""

from backend.models.customer_technology import CustomerTechnology
from backend.models.sales_note import SalesNote
from backend.models.technology_dependency import TechnologyDependency
from backend.models.use_case import Customer, CustomerUser, User


def _workspace_customer(db_session, customer_id: int = 1,
                        name: str = None) -> Customer:
    c = db_session.query(Customer).filter(Customer.id == customer_id).first()
    if c is None:
        c = Customer(id=customer_id, name=name or f"Graph Co {customer_id}")
        db_session.add(c)
        db_session.commit()
    return c


def _tech(db_session, customer_id: int, name: str, **kw) -> int:
    t = CustomerTechnology(
        customer_id=customer_id, name=name, category=kw.pop("category", "software"), **kw
    )
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t.id


def _note(db_session, customer_id: int, title: str = "Note", **kw) -> int:
    n = SalesNote(
        customer_id=customer_id, title=title, category=kw.pop("category", "discovery"),
        content=kw.pop("content", "body"), verification_state=kw.pop("verification_state", "verified"),
    )
    db_session.add(n)
    db_session.commit()
    db_session.refresh(n)
    return n.id


def _graph(db_session, customer_id: int = 1) -> dict:
    from backend.services.customer_intelligence import build_customer_intelligence_graph

    return build_customer_intelligence_graph(db_session, customer_id)


def _ids(items, key="id"):
    return {i[key] for i in items}


class TestGraphProjection:
    def test_central_customer_node_and_domain_hubs(self, db_session):
        _workspace_customer(db_session, 1)
        _tech(db_session, 1, "VMware vSphere", category="virtualization", business_criticality="critical")
        _note(db_session, 1, "Discovery note")
        g = _graph(db_session, 1)

        customer_nodes = [n for n in g["nodes"] if n["type"] == "customer"]
        assert len(customer_nodes) == 1
        assert customer_nodes[0]["id"] == "customer-1"
        assert customer_nodes[0]["label"] == "Graph Co 1"
        assert customer_nodes[0]["importance"] == 1.0

        domains = {n["category"] for n in g["nodes"] if n["type"] == "domain"}
        assert "technology" in domains
        assert "sales_note" in domains
        # Every domain hub is linked from the customer node.
        for d in domains:
            assert (
                "customer-1", f"{d}-domain", f"domain:{d}"
            ) in {(lnk["source"], lnk["target"], lnk["relationshipType"]) for lnk in g["links"]}

    def test_seeded_technology_nodes_appear(self, db_session):
        _workspace_customer(db_session, 1)
        t1 = _tech(db_session, 1, "VMware vSphere", category="virtualization",
                   business_criticality="critical", lifecycle_state="eol",
                   support_state="no_support", verification_state="verified")
        t2 = _tech(db_session, 1, "Dell R720", category="hardware", business_criticality="high")
        g = _graph(db_session, 1)
        tech_nodes = [n for n in g["nodes"] if n["type"] == "technology"]
        assert {n["entityId"] for n in tech_nodes} == {t1, t2}
        # importance encodes business criticality (a legitimate value)
        by_id = {n["entityId"]: n for n in tech_nodes}
        assert by_id[t1]["importance"] > by_id[t2]["importance"]
        assert by_id[t1]["verified"] is True
        assert by_id[t1]["metadata"]["lifecycle_state"] == "eol"

    def test_seeded_dependency_links_appear(self, db_session):
        _workspace_customer(db_session, 1)
        src = _tech(db_session, 1, "vCenter", category="management_tool")
        tgt = _tech(db_session, 1, "vSphere", category="virtualization")
        db_session.add(TechnologyDependency(
            customer_id=1, source_id=src, target_id=tgt, relationship_type="manages",
        ))
        db_session.commit()
        g = _graph(db_session, 1)
        dep_links = [lnk for lnk in g["links"] if lnk["relationshipType"] == "tech_dependency:manages"]
        assert len(dep_links) == 1
        assert dep_links[0]["source"] == f"technology-{src}"
        assert dep_links[0]["target"] == f"technology-{tgt}"
        assert dep_links[0]["verified"] is True
        assert "provenance" in dep_links[0] and dep_links[0]["provenance"]

    def test_note_to_technology_cross_domain_link(self, db_session):
        _workspace_customer(db_session, 1)
        tech_id = _tech(db_session, 1, "vSphere", category="virtualization")
        note_id = _note(db_session, 1, "EOL risk note")
        # Authoritative junction reference (the same data the Sales Notes UI shows).
        n = db_session.query(SalesNote).filter(SalesNote.id == note_id).first()
        t = db_session.query(CustomerTechnology).filter(CustomerTechnology.id == tech_id).first()
        n.related_technologies.append(t)
        db_session.commit()
        g = _graph(db_session, 1)
        x = [lnk for lnk in g["links"] if lnk["relationshipType"] == "note_references_technology"]
        assert len(x) == 1
        assert x[0]["source"] == f"sales_note-{note_id}"
        assert x[0]["target"] == f"technology-{tech_id}"

    def test_no_mirrored_duplicate_links_and_unique_ids(self, db_session):
        _workspace_customer(db_session, 1)
        src = _tech(db_session, 1, "A", category="software")
        tgt = _tech(db_session, 1, "B", category="software")
        db_session.add(TechnologyDependency(
            customer_id=1, source_id=src, target_id=tgt, relationship_type="depends_on",
        ))
        db_session.commit()
        g = _graph(db_session, 1)
        # No link may appear both as (s,t) and (t,s) for the same type.
        seen = set()
        for lnk in g["links"]:
            key = frozenset((lnk["source"], lnk["target"], lnk["relationshipType"]))
            assert key not in seen, f"mirrored duplicate: {lnk}"
            seen.add(key)
        # Node ids unique, link ids unique + stable (derived from ids).
        assert len(_ids(g["nodes"])) == len(g["nodes"])
        assert len(_ids(g["links"])) == len(g["links"])
        for lnk in g["links"]:
            assert lnk["id"] == f"{lnk['source']}|{lnk['target']}|{lnk['relationshipType']}"
        # No dangling link: every endpoint resolves to a real node id.
        node_ids = _ids(g["nodes"])
        for lnk in g["links"]:
            assert lnk["source"] in node_ids, f"dangling source {lnk['source']}"
            assert lnk["target"] in node_ids, f"dangling target {lnk['target']}"

    def test_no_fabricated_entities_sparse_customer(self, db_session):
        """A customer with NOTHING gets the central node + at most the
        deterministic discovery risk cards (evidence-backed) — never
        fabricated domain/entity filler, never an error."""
        _workspace_customer(db_session, 1, name="Empty Co")
        g = _graph(db_session, 1)
        customer_nodes = [n for n in g["nodes"] if n["type"] == "customer"]
        assert len(customer_nodes) == 1
        assert customer_nodes[0]["label"] == "Empty Co"
        # Only discovery cards (the synthesis's honest empty-state output —
        # no technology/notes, so they classify as risk + opportunity
        # types) plus their domain hubs — no tech/note/UC/assessment nodes.
        entity_types = {n["type"] for n in g["nodes"]} - {"customer", "domain"}
        assert entity_types <= {"risk", "opportunity"}
        # The panel's contact-coverage gap ("No contacts recorded") is an
        # honest gap card too, shown under Risks / Gaps.
        assert all(n["status"] in ("discovery_needed", "contact_coverage")
                   for n in g["nodes"] if n["type"] in ("risk", "opportunity"))
        # Links only to existing nodes (no dangling references).
        node_ids = _ids(g["nodes"])
        for lnk in g["links"]:
            assert lnk["source"] in node_ids
            assert lnk["target"] in node_ids
        assert g["limits"]["technology_total"] == 0
        assert g["limits"]["technology_shown"] == 0

    def test_top_n_density_control_reports_limits(self, db_session):
        _workspace_customer(db_session, 1)
        for i in range(15):
            _tech(db_session, 1, f"Tech {i}", category="software",
                  business_criticality="critical" if i < 8 else "low")
        g = _graph(db_session, 1)
        tech_nodes = [n for n in g["nodes"] if n["type"] == "technology"]
        assert len(tech_nodes) == 8  # capped at max_per_domain
        assert g["limits"]["technology_total"] == 15
        assert g["limits"]["technology_shown"] == 8
        # The kept set is the deterministic critical-first top-N.
        assert all(n["metadata"]["business_criticality"] == "critical" for n in tech_nodes)

    def test_dependency_with_endpoint_outside_top_n_is_omitted_not_fabricated(self, db_session):
        _workspace_customer(db_session, 1)
        # 9 low-criticality techs -> only the first 8 are kept.
        ids = [_tech(db_session, 1, f"Low {i}", category="software", business_criticality="low")
               for i in range(9)]
        # A dependency referencing the one tech that did NOT make the top-N:
        # its edge must be omitted (never a fabricated node).
        db_session.add(TechnologyDependency(
            customer_id=1, source_id=ids[0], target_id=ids[8], relationship_type="depends_on",
        ))
        db_session.commit()
        g = _graph(db_session, 1)
        dep_links = [lnk for lnk in g["links"] if lnk["relationshipType"] == "tech_dependency:depends_on"]
        assert dep_links == []  # target outside kept set -> omitted
        assert g["limits"]["dependencies_total"] == 1
        assert g["limits"]["dependencies_shown"] == 0

    def test_deterministic_across_calls(self, db_session):
        _workspace_customer(db_session, 1)
        _tech(db_session, 1, "vSphere", category="virtualization", business_criticality="critical")
        _note(db_session, 1, "Note A")
        a = _graph(db_session, 1)
        b = _graph(db_session, 1)
        # Order + ids are stable (generated_at excluded).
        assert a["nodes"] == b["nodes"]
        assert a["links"] == b["links"]
        assert a["limits"] == b["limits"]

    def test_cross_customer_isolation(self, db_session):
        _workspace_customer(db_session, 1, name="Co A")
        _workspace_customer(db_session, 2, name="Co B")
        t_a = _tech(db_session, 1, "Co A Tech", category="software")
        _note(db_session, 2, "Co B Note")
        g1 = _graph(db_session, 1)
        g2 = _graph(db_session, 2)
        # Co A's tech must not leak into Co B's graph and vice versa.
        assert f"technology-{t_a}" in _ids(g1["nodes"])
        assert f"technology-{t_a}" not in _ids(g2["nodes"])
        assert all(n["label"] != "Co B Note" for n in g1["nodes"])
        assert all(n["label"] != "Co A Tech" for n in g2["nodes"])


class TestGraphRouteAuth:
    def _admin_headers(self, db_session):
        from backend.auth import create_access_token

        admin = db_session.query(User).filter(User.is_admin == 1).first()
        return {"Authorization": f"Bearer {create_access_token({'sub': admin.username, 'is_admin': True})}"}

    def _member_headers(self, db_session, customer_id: int):
        from backend.auth import create_access_token

        username = f"graph_member_{customer_id}"
        user = db_session.query(User).filter(User.username == username).first()
        if not user:
            user = User(username=username, email=f"{username}@t.local",
                        hashed_password="unused", is_admin=0, approved=1, is_active=1)
            db_session.add(user)
            db_session.commit()
        _workspace_customer(db_session, customer_id)
        if not db_session.query(CustomerUser).filter(
            CustomerUser.customer_id == customer_id, CustomerUser.user_id == user.id
        ).first():
            db_session.add(CustomerUser(customer_id=customer_id, user_id=user.id, role="member"))
            db_session.commit()
        return {"Authorization": f"Bearer {create_access_token({'sub': user.username, 'is_admin': False})}"}

    def test_unauthenticated_401(self, client, db_session):
        _workspace_customer(db_session, 1)
        assert client.get("/api/customers/1/intelligence/graph/").status_code == 401

    def test_missing_customer_404(self, client, db_session):
        assert client.get("/api/customers/9999/intelligence/graph/",
                          headers=self._admin_headers(db_session)).status_code == 404

    def test_out_of_scope_404(self, client, db_session):
        _workspace_customer(db_session, 1)
        _workspace_customer(db_session, 2)
        headers = self._member_headers(db_session, 2)
        # 404-first: out-of-scope is the same 404 as a missing customer.
        assert client.get("/api/customers/1/intelligence/graph/", headers=headers).status_code == 404

    def test_member_200_and_admin_200(self, client, db_session):
        _workspace_customer(db_session, 1)
        _tech(db_session, 1, "vSphere", category="virtualization")
        member = client.get("/api/customers/1/intelligence/graph/",
                            headers=self._member_headers(db_session, 1))
        assert member.status_code == 200
        body = member.json()
        assert body["method"] == "deterministic_graph_projection"
        assert any(n["type"] == "customer" for n in body["nodes"])
        admin = client.get("/api/customers/1/intelligence/graph/",
                           headers=self._admin_headers(db_session))
        assert admin.status_code == 200
        # Same projection for the same data (deterministic).
        assert admin.json()["nodes"] == body["nodes"]


# ── Möbius wiring review (2026-11-01): evidence + identity fixes ──────────

def _evaluation(db_session, customer_id, name, risk_factors, created_at):
    from backend.models.sales_evaluation import SalesEvaluation

    ev = SalesEvaluation(customer_id=customer_id, evaluation_name=name,
                         risk_factors=risk_factors, created_at=created_at)
    db_session.add(ev)
    db_session.commit()
    db_session.refresh(ev)
    return ev.id


class TestWiringReview:
    def test_dependency_endpoints_resolve_by_id_not_name(self, db_session):
        # Two technologies share a name; the dependency targets the FIRST.
        # A name-keyed map (last name wins) would attach it to the second.
        _workspace_customer(db_session, 1)
        a = _tech(db_session, 1, "Platform", category="software", business_criticality="critical")
        b = _tech(db_session, 1, "Platform", category="software", business_criticality="high")
        mgr = _tech(db_session, 1, "vCenter", category="management_tool", business_criticality="critical")
        db_session.add(TechnologyDependency(customer_id=1, source_id=mgr, target_id=a,
                                            relationship_type="manages"))
        db_session.commit()
        deps = [lnk for lnk in _graph(db_session, 1)["links"]
                if lnk["relationshipType"].startswith("tech_dependency:")]
        assert [(d["source"], d["target"]) for d in deps] == [
            (f"technology-{mgr}", f"technology-{a}")]
        assert a != b

    def test_dependency_on_technology_outside_top_n_is_omitted(self, db_session):
        _workspace_customer(db_session, 1)
        kept = [_tech(db_session, 1, f"Kept {i}", business_criticality="critical") for i in range(8)]
        # Same NAME as a kept technology but lower priority -> outside top-8.
        dropped = _tech(db_session, 1, "Kept 0", business_criticality="low")
        db_session.add(TechnologyDependency(customer_id=1, source_id=kept[1], target_id=dropped,
                                            relationship_type="depends_on"))
        db_session.commit()
        g = _graph(db_session, 1)
        assert f"technology-{dropped}" not in {n["id"] for n in g["nodes"]}
        assert not [lnk for lnk in g["links"] if lnk["relationshipType"].startswith("tech_dependency:")]
        assert g["limits"]["dependencies_shown"] == 0

    def test_observed_gap_links_to_the_latest_evaluation_node(self, db_session):
        from datetime import datetime

        _workspace_customer(db_session, 1)
        same_second = datetime(2026, 10, 1, 12, 0, 0)
        _evaluation(db_session, 1, "Older twin", [{"category": "stale_finding"}], same_second)
        newest = _evaluation(db_session, 1, "Newest", [{"category": "security_gap", "description": "d"}],
                             same_second)
        g = _graph(db_session, 1)
        ev_nodes = [n for n in g["nodes"] if n["type"] == "sales_evaluation"]
        # Tie on created_at -> the NEWEST id, the same rule the panel uses.
        assert [n["entityId"] for n in ev_nodes] == [newest]
        gap = next(n for n in g["nodes"] if n["type"] == "risk" and n["label"] == "Security Gap")
        links = [lnk for lnk in g["links"] if lnk["relationshipType"] == "gap_from_sales_evaluation"]
        assert [(lnk["source"], lnk["target"]) for lnk in links] == [
            (gap["id"], f"sales_evaluation-{newest}")]

    def test_follow_up_links_to_its_sales_note_node(self, db_session):
        from datetime import date

        _workspace_customer(db_session, 1)
        note_id = _note(db_session, 1, "Champion asked for pricing", category="opportunity")
        n = db_session.query(SalesNote).filter(SalesNote.id == note_id).first()
        n.note_date = date.today()
        db_session.commit()
        g = _graph(db_session, 1)
        follow = next(o for o in g["nodes"] if o["type"] == "opportunity"
                      and o["status"] == "follow_up")
        links = [lnk for lnk in g["links"] if lnk["relationshipType"] == "follow_up_on_sales_note"]
        assert [(lnk["source"], lnk["target"]) for lnk in links] == [
            (follow["id"], f"sales_note-{note_id}")]

    def test_group_limits_total_counts_groups_beyond_the_kept_top_n(self, db_session):
        _workspace_customer(db_session, 1)
        for i in range(8):
            _tech(db_session, 1, f"Critical {i}", category="software", business_criticality="critical")
        _tech(db_session, 1, "Low hardware", category="hardware", business_criticality="low")
        g = _graph(db_session, 1)
        assert g["limits"]["group_limits"]["technology"] == {"total": 2, "shown": 1}
