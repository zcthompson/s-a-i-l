"""Section H hierarchy contract for the Customer Intelligence graph."""

from backend.models.customer_technology import CustomerTechnology
from backend.models.sales_note import SalesNote
from backend.models.use_case import Customer, CustomerUser, Department, User


def _customer(db_session, customer_id=1, **kw):
    customer = Customer(
        id=customer_id,
        name=kw.pop("name", f"Hierarchy Co {customer_id}"),
        **kw,
    )
    db_session.add(customer)
    db_session.commit()
    return customer


def _tech(db_session, customer_id, name, category):
    technology = CustomerTechnology(
        customer_id=customer_id,
        name=name,
        category=category,
        verification_state="verified",
    )
    db_session.add(technology)
    db_session.commit()
    db_session.refresh(technology)
    return technology


def _note(db_session, customer_id, title="Discovery note", category="discovery"):
    note = SalesNote(
        customer_id=customer_id,
        title=title,
        category=category,
        content="body",
        verification_state="verified",
    )
    db_session.add(note)
    db_session.commit()
    db_session.refresh(note)
    return note


def _graph(db_session, customer_id=1):
    from backend.services.customer_intelligence import (
        build_customer_intelligence_graph,
    )

    return build_customer_intelligence_graph(db_session, customer_id)


def _by_id(graph):
    return {node["id"]: node for node in graph["nodes"]}


def test_hierarchy_fields_and_group_nodes(db_session):
    _customer(db_session)
    software = _tech(db_session, 1, "Platform A", "software")
    hardware = _tech(db_session, 1, "Platform B", "hardware")
    note = _note(db_session, 1)

    graph = _graph(db_session)
    nodes = _by_id(graph)

    assert {
        "level": 0,
        "parentId": None,
        "groupKey": None,
        "empty": False,
    }.items() <= nodes["customer-1"].items()
    for domain in ("technology", "sales_note", "risk", "opportunity"):
        if f"{domain}-domain" in nodes:
            assert nodes[f"{domain}-domain"]["level"] == 1
            assert nodes[f"{domain}-domain"]["parentId"] == "customer-1"
            assert nodes[f"{domain}-domain"]["groupKey"] is None
            assert nodes[f"{domain}-domain"]["empty"] is False

    assert nodes[f"technology-{software.id}"]["parentId"] == (
        "portion-technology-software"
    )
    assert nodes[f"technology-{software.id}"]["groupKey"] == "software"
    assert nodes[f"technology-{hardware.id}"]["parentId"] == (
        "portion-technology-hardware"
    )
    assert nodes[f"sales_note-{note.id}"]["parentId"] == (
        "portion-sales_note-discovery"
    )
    for node in graph["nodes"]:
        assert {"level", "parentId", "groupKey", "empty"} <= node.keys()
        if node["type"] not in {"customer", "domain", "group", "empty"}:
            assert node["level"] == 3
            assert node["parentId"].startswith("portion-")
            assert node["groupKey"] is not None
            assert node["empty"] is False

    groups = {n["id"]: n for n in graph["nodes"] if n["type"] == "group"}
    assert groups["portion-technology-software"]["metadata"] == {
        "member_count": 1,
        "group_key": "software",
    }
    assert groups["portion-technology-hardware"]["level"] == 2
    assert groups["portion-technology-hardware"]["parentId"] == (
        "technology-domain"
    )
    assert groups["portion-technology-hardware"]["entityId"] == 1
    assert groups["portion-technology-hardware"]["entityType"] == "group"


def test_group_membership_counts_and_ids_are_stable(db_session):
    _customer(db_session)
    _tech(db_session, 1, "A", "cloud_platform")
    _tech(db_session, 1, "B", "cloud_platform")
    _tech(db_session, 1, "C", "hardware")

    first = _graph(db_session)
    second = _graph(db_session)
    first_groups = {
        node["id"]: node
        for node in first["nodes"]
        if node["type"] == "group" and node["category"] == "technology"
    }
    second_group_ids = {
        node["id"]
        for node in second["nodes"]
        if node["type"] == "group" and node["category"] == "technology"
    }

    assert set(first_groups) == {
        "portion-technology-cloud-platform",
        "portion-technology-hardware",
    }
    assert set(first_groups) == second_group_ids
    assert first_groups["portion-technology-cloud-platform"]["metadata"][
        "member_count"
    ] == 2
    assert first_groups["portion-technology-cloud-platform"]["importance"] == (
        0.425
    )
    assert first["limits"]["group_limits"]["technology"] == {
        "total": 2,
        "shown": 2,
    }


def test_portion_links_are_additive_to_existing_trunks(db_session):
    _customer(db_session)
    technology = _tech(db_session, 1, "Platform A", "software")
    graph = _graph(db_session)
    links = {
        (link["source"], link["target"], link["relationshipType"]): link
        for link in graph["links"]
    }

    assert (
        "customer-1",
        "technology-domain",
        "domain:technology",
    ) in links
    assert (
        "technology-domain",
        f"technology-{technology.id}",
        "domain:technology",
    ) in links
    portion = links[
        (
            "technology-domain",
            "portion-technology-software",
            "portion:technology",
        )
    ]
    support = links[
        (
            f"technology-{technology.id}",
            "portion-technology-software",
            "supports:technology",
        )
    ]
    assert portion["relationship"] == "Software portion of Technology"
    assert support["relationship"] == "Platform A · Software"
    assert portion["provenance"] == support["provenance"] == (
        "portion grouping (derived)"
    )


def test_empty_portion_ring_for_group_culled_by_top_n(db_session):
    _customer(db_session)
    categories = [
        "software",
        "hardware",
        "infrastructure",
        "cloud_platform",
        "virtualization",
        "networking",
        "storage",
        "security",
        "data_platform",
    ]
    for index, category in enumerate(categories):
        _tech(db_session, 1, f"Technology {index}", category)

    graph = _graph(db_session)
    rings = [
        node
        for node in graph["nodes"]
        if node["id"] == "portion-empty-technology"
    ]
    assert len(rings) == 1
    assert rings[0]["type"] == "empty"
    assert rings[0]["empty"] is True
    assert rings[0]["importance"] == 0.1
    assert rings[0]["parentId"] == "technology-domain"
    assert graph["limits"]["empty_portions"] == {"technology": 1}


def test_account_core_metadata_counts_customer_scoped_rows(db_session):
    _customer(
        db_session,
        branch="BR20 - Example Customer H",
        vertical="Financial Services",
    )
    user = User(
        username="hierarchy_member",
        email="hierarchy_member@example.test",
        hashed_password="unused",
        approved=1,
        is_active=1,
    )
    db_session.add_all([
        user,
        Department(name="Engineering", customer_id=1),
    ])
    db_session.flush()
    db_session.add(CustomerUser(customer_id=1, user_id=user.id, role="member"))
    db_session.commit()

    metadata = _by_id(_graph(db_session))["customer-1"]["metadata"]
    assert metadata == {
        "branch": "BR20 - Example Customer H",
        "department_count": 1,
        "member_count": 1,
        "vertical": "Financial Services",
    }


def test_hierarchy_projection_is_deterministic(db_session):
    _customer(db_session)
    _tech(db_session, 1, "Platform A", "software")
    _note(db_session, 1)

    first = _graph(db_session)
    second = _graph(db_session)
    assert first["nodes"] == second["nodes"]
    assert first["links"] == second["links"]
    assert first["limits"] == second["limits"]
    assert first["nodes"] == sorted(
        first["nodes"], key=lambda node: (node["level"], node["id"])
    )


def test_sparse_customer_adds_no_group_or_empty_nodes(db_session):
    _customer(db_session, name="Sparse Co")
    graph = _graph(db_session)

    assert not [
        node for node in graph["nodes"] if node["type"] in {"group", "empty"}
    ]
    assert graph["limits"]["group_limits"] == {}
    assert graph["limits"]["empty_portions"] == {}
    assert all(
        {"level", "parentId", "groupKey", "empty"} <= node.keys()
        for node in graph["nodes"]
    )


def test_graph_carries_panel_renewal_coverage_and_eol_cards(db_session):
    """The graph uses the panel's full synthesis. Renewal attention groups
    under Opportunities; contact coverage and dated EOL under Risks / Gaps; each
    card sits at level 3 under its portion group, and EOL links its technology."""
    from datetime import UTC, date, datetime, timedelta

    from tests.backend._shared import add_pipeline_batch

    customer = _customer(db_session)
    tech = _tech(db_session, 1, "Platform A", "software")
    tech.business_criticality = "critical"
    tech.end_of_support_date = date(2027, 1, 31)
    tech.eol_source = "Synthetic vendor notice"
    db_session.commit()
    soon = datetime.now(UTC).date() + timedelta(days=10)
    add_pipeline_batch(db_session, [(customer, [
        {"opportunity_number": "HIER-1", "current_contract_end_date": soon, "est_acv_usd": None},
    ])])
    graph = _graph(db_session)
    nodes = list(graph["nodes"])
    by_status = {}
    for node in nodes:
        by_status.setdefault(node["status"], []).append(node)

    renewal, = by_status["renewal_attention"]
    assert renewal["type"] == "opportunity" and renewal["level"] == 3
    assert renewal["parentId"] == "portion-opportunity-renewal-attention"
    assert renewal["metadata"]["evidence"]["source"] == "partner_pipeline"

    coverage, = by_status["contact_coverage"]
    assert coverage["type"] == "risk" and coverage["level"] == 3
    assert coverage["parentId"] == "portion-risk-contact-coverage"

    eol, = by_status["eol_attention"]
    assert eol["type"] == "risk" and eol["parentId"] == "portion-risk-eol-attention"
    link_ids = {link["id"] for link in graph["links"]}
    assert f"{eol['id']}|technology-{tech.id}|risk_affects_technology" in link_ids
    assert {n["category"] for n in nodes} <= {"customer", "domain", "technology", "risk", "opportunity"}
