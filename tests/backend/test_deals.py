"""E6 deals + pipeline stages: contracts, access matrix, CAS, history, cleanup."""

import pytest
from backend.auth import create_access_token
from backend.models.account_membership import AccountMembership
from backend.models.customer_contact import CustomerContact
from backend.models.customer_technology import CustomerTechnology
from backend.models.deal import (
    Deal,
    DealStageHistory,
    PipelineStage,
    deal_contacts,
    deal_technologies,
)
from backend.models.sales_access import SalesOpsAssignment
from backend.models.use_case import Customer, CustomerUser, User
from backend.services.user_service import UserService


def headers(username="admin"):
    return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}


@pytest.fixture()
def stages(db_session):
    from backend.models.deal import DEFAULT_STAGES
    if not db_session.query(PipelineStage).count():
        db_session.add_all([PipelineStage(key=k, label=label, stage_class=c, position=p, default_probability=prob, active=True)
                            for k, label, c, p, prob in DEFAULT_STAGES])
        db_session.commit()
    return {s.key: s.id for s in db_session.query(PipelineStage)}


@pytest.fixture()
def world(db_session, stages):
    account, other = Customer(name="Synthetic Deal Co"), Customer(name="Synthetic Other Co")
    owner = User(username="deal_owner", display_name="Deal Owner", approved=1, is_active=1, role="user", sales_role="rep")
    db_session.add_all([account, other, owner])
    db_session.flush()
    db_session.add(CustomerUser(customer_id=account.id, user_id=owner.id, role="owner"))
    db_session.commit()
    return account, other, owner


def base(cid):
    return f"/api/customers/{cid}/deals/"


def create(client, cid, user="admin", **payload):
    return client.post(base(cid), headers=headers(user), json={"name": "Synthetic deal", **payload})


# ── stages ──────────────────────────────────────────────────────────────────

def test_stage_list_and_admin_management(client, db_session, world, stages):
    rows = client.get("/api/pipeline-stages/", headers=headers()).json()
    assert [r["key"] for r in rows] == ["qualification", "discovery", "proposal", "negotiation", "closed_won", "closed_lost"]
    assert rows[0]["default_probability"] == 10
    new = {"key": "solution_review", "label": "Solution review", "stage_class": "open", "position": 35}
    assert client.post("/api/admin/pipeline-stages/", headers=headers("deal_owner"), json=new).status_code == 403
    db_session.add(User(username="synthetic_sales_admin", approved=1, is_active=1, role="user", sales_role="sales_admin"))
    db_session.commit()
    r = client.post("/api/admin/pipeline-stages/", headers=headers("synthetic_sales_admin"), json=new)
    assert r.status_code == 201, r.text
    assert client.post("/api/admin/pipeline-stages/", headers=headers(), json=new).status_code == 409
    assert client.post("/api/admin/pipeline-stages/", headers=headers(),
                       json={**new, "key": "odd", "stage_class": "maybe"}).status_code == 422
    r = client.put(f"/api/admin/pipeline-stages/{r.json()['id']}/", headers=headers(), json={"label": "Solution Review", "default_probability": 40})
    assert r.status_code == 200 and r.json()["label"] == "Solution Review" and r.json()["default_probability"] == 40


def test_retiring_a_stage_requires_moving_its_deals(client, db_session, world, stages):
    account, _, _ = world
    deal = create(client, account.id, stage_id=stages["proposal"]).json()
    url = f"/api/admin/pipeline-stages/{stages['proposal']}/"
    assert client.put(url, headers=headers(), json={"active": False}).status_code == 409
    assert client.put(url, headers=headers(), json={"active": False, "remap_to_stage_id": stages["closed_won"]}).status_code == 422
    r = client.put(url, headers=headers(), json={"active": False, "remap_to_stage_id": stages["negotiation"]})
    assert r.status_code == 200 and r.json()["active"] is False
    moved = client.get(f"/api/deals/{deal['id']}/", headers=headers()).json()
    assert moved["stage_id"] == stages["negotiation"] and moved["version"] == 2
    hist = client.get(f"/api/deals/{deal['id']}/history/", headers=headers()).json()
    assert hist[-1]["to_stage"] == "Negotiation" and "retired" in hist[-1]["note"]
    assert "proposal" not in [s["key"] for s in client.get("/api/pipeline-stages/", headers=headers()).json()]
    assert create(client, account.id, stage_id=stages["proposal"]).status_code == 422


# ── deal contract ───────────────────────────────────────────────────────────

def test_create_defaults_suggestion_and_history(client, db_session, world, stages):
    account, _, owner = world
    r = create(client, account.id, owner_user_id=owner.id, amount_minor=1250000, currency="usd", amount_basis="acv",
               close_date="2026-12-31", deal_type="new", next_step="Send proposal", next_step_date="2026-11-20")
    assert r.status_code == 201, r.text
    deal = r.json()
    assert deal["stage"]["key"] == "qualification"            # first active open stage
    assert deal["probability"] is None and deal["suggested_probability"] == 10   # D5: suggestion only
    assert deal["amount"] == {"minor": 1250000, "currency": "USD"} and deal["amount_basis"] == "acv"
    assert deal["owner_name"] == "Deal Owner" and deal["version"] == 1
    assert create(client, account.id).json()["owner_name"] in ("Administrator", "admin")  # defaults to creator
    hist = client.get(f"/api/deals/{deal['id']}/history/", headers=headers()).json()
    assert hist == [{"from_stage": None, "to_stage": "Qualification", "actor": "admin", "at": hist[0]["at"],
                     "amount": {"minor": 1250000, "currency": "USD"}, "amount_basis": "acv",
                     "close_date": "2026-12-31", "note": "created"}]


@pytest.mark.parametrize("payload, message", [
    ({"amount_minor": 100}, "basis"),
    ({"amount_minor": 100, "amount_basis": "weekly"}, "basis"),
    ({"currency": "US"}, None),
    ({"currency": "U$D"}, "currency"),
    ({"deal_type": "upsell"}, "deal type"),
    ({"probability": 101}, None),
    ({"amount_minor": -1, "amount_basis": "acv"}, None),
    ({"name": "   "}, "name"),
])
def test_validation(client, world, payload, message):
    account, _, _ = world
    r = create(client, account.id, **payload)
    assert r.status_code == 422, r.text
    if message:
        assert message in r.text.lower()


def test_links_must_belong_to_the_account(client, db_session, world):
    account, other, owner = world
    mine = CustomerContact(customer_id=account.id, display_name="Synthetic contact")
    theirs = CustomerTechnology(customer_id=other.id, name="Foreign tech", category="software")
    inactive = User(username="gone_owner", approved=1, is_active=0, role="user")
    db_session.add_all([mine, theirs, inactive])
    db_session.commit()
    assert create(client, account.id, technology_ids=[theirs.id]).status_code == 422
    assert create(client, account.id, owner_user_id=inactive.id).status_code == 422
    assert create(client, account.id, contacts=[{"contact_id": mine.id, "role": "boss"}]).status_code == 422
    assert create(client, account.id, contacts=[{"contact_id": mine.id}, {"contact_id": mine.id}]).status_code == 422
    r = create(client, account.id, contacts=[{"contact_id": mine.id, "role": "champion"}])
    assert r.status_code == 201 and r.json()["contacts"] == [{"contact_id": mine.id, "role": "champion"}]


def test_update_cas_stage_history_and_closing(client, db_session, world, stages):
    account, _, _ = world
    deal = create(client, account.id, amount_minor=500, amount_basis="one_time").json()
    url = f"/api/deals/{deal['id']}/"
    assert client.put(url, headers=headers(), json={"expected_version": 9, "name": "x"}).status_code == 409
    r = client.put(url, headers=headers(), json={"expected_version": 1, "stage_id": stages["proposal"], "probability": 40})
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["probability"] == 40
    assert r.json()["suggested_probability"] == 50
    assert client.put(url, headers=headers(), json={"expected_version": 2, "stage_id": stages["closed_lost"]}).status_code == 422
    r = client.put(url, headers=headers(), json={"expected_version": 2, "stage_id": stages["closed_lost"],
                                                 "closed_reason": "Budget withdrawn"})
    assert r.status_code == 200 and r.json()["closed_at"] and r.json()["closed_reason"] == "Budget withdrawn"
    r = client.put(url, headers=headers(), json={"expected_version": 3, "stage_id": stages["discovery"]})
    assert r.status_code == 200 and r.json()["closed_at"] is None and r.json()["closed_reason"] is None
    hist = client.get(f"{url}history/", headers=headers()).json()
    assert [(h["from_stage"], h["to_stage"]) for h in hist] == [
        (None, "Qualification"), ("Qualification", "Proposal"), ("Proposal", "Closed Lost"), ("Closed Lost", "Discovery")]
    assert client.get(base(account.id) + "?include_closed=false", headers=headers()).json()[0]["id"] == deal["id"]


def test_delete_cas_and_cleanup(client, db_session, world):
    account, _, _ = world
    contact = CustomerContact(customer_id=account.id, display_name="Synthetic contact")
    db_session.add(contact)
    db_session.commit()
    deal = create(client, account.id, contacts=[{"contact_id": contact.id}]).json()
    url = f"/api/deals/{deal['id']}/"
    assert client.request("DELETE", url, headers=headers(), json={"expected_version": 5}).status_code == 409
    assert client.request("DELETE", url, headers=headers(), json={"expected_version": 1}).status_code == 204
    db_session.expire_all()
    assert db_session.get(Deal, deal["id"]) is None
    assert db_session.query(DealStageHistory).filter_by(deal_id=deal["id"]).count() == 0
    assert db_session.query(deal_contacts).filter(deal_contacts.c.deal_id == deal["id"]).count() == 0
    assert client.get(url, headers=headers()).status_code == 404


def test_account_and_user_deletion(client, db_session, world):
    account, _, owner = world
    tech = CustomerTechnology(customer_id=account.id, name="Synthetic tech", category="software")
    db_session.add(tech)
    db_session.commit()
    deal = create(client, account.id, owner_user_id=owner.id, technology_ids=[tech.id]).json()
    admin = db_session.query(User).filter_by(username="admin").one()
    UserService.delete_user(db_session, owner.id, admin.id)
    db_session.expire_all()
    kept = db_session.get(Deal, deal["id"])
    assert kept.owner_user_id is None and kept.owner_name == "Deal Owner"   # D4 snapshot kept
    assert client.delete(f"/api/customers/{account.name}/", headers=headers()).status_code == 204
    db_session.expire_all()
    assert db_session.get(Deal, deal["id"]) is None
    assert db_session.query(deal_technologies).count() == 0
    assert db_session.query(DealStageHistory).count() == 0


# ── access matrix ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind, read, write", [
    ("owner", 200, 201), ("member", 200, 201), ("auditor", 200, 403), ("sales_ops", 200, 403),
    ("inside_none", 200, 403), ("inside_read", 200, 403), ("inside_contribute", 200, 201), ("outsider", 404, 404),
])
def test_access_matrix(client, db_session, world, kind, read, write):
    account, _, _ = world
    user = User(username=f"matrix_{kind}", approved=1, is_active=1, role="user",
                sales_role="auditor" if kind == "auditor" else "sales_ops" if kind == "sales_ops"
                else "inside_sales" if kind.startswith("inside") else "rep")
    db_session.add(user)
    db_session.flush()
    if kind in ("owner", "member", "auditor"):
        db_session.add(CustomerUser(customer_id=account.id, user_id=user.id, role=kind))
    if kind == "sales_ops":
        db_session.add(SalesOpsAssignment(customer_id=account.id, user_id=user.id))
    if kind.startswith("inside_"):
        grants = None if kind == "inside_none" else {"opportunities": "contribute" if kind == "inside_contribute" else "read"}
        db_session.add(AccountMembership(customer_id=account.id, user_id=user.id, role="inside_sales", section_grants=grants))
    db_session.commit()
    existing = create(client, account.id).json()
    auth = headers(user.username)
    assert client.get(base(account.id), headers=auth).status_code == read
    assert client.get(f"/api/deals/{existing['id']}/", headers=auth).status_code == read
    assert client.post(base(account.id), headers=auth, json={"name": "Matrix deal"}).status_code == write
    expected_put = 200 if write == 201 else write
    assert client.put(f"/api/deals/{existing['id']}/", headers=auth,
                      json={"expected_version": 1, "next_step": "x"}).status_code == expected_put


def test_vendor_promotion_is_idempotent_scoped_and_never_copies_money(client, db_session, world):
    from backend.models.deal import deal_vendor_evidence
    from backend.models.intelligence_import import IntelligenceImport, PartnerPipeline
    account, other, _ = world
    batch = IntelligenceImport(file_name='synthetic.csv', file_sha256='0' * 64, file_data=b'', total_rows=2, matched_accounts=2, matched_rows=2, unmatched_accounts=0, unmatched_report='[]', imported_by='admin')
    db_session.add(batch)
    db_session.flush()
    db_session.add_all([PartnerPipeline(customer_id=account.id, import_id=batch.id, customer_account_name=account.name, opportunity_number='SYN-1', opportunity_name='Vendor evidence', est_acv_usd=9999), PartnerPipeline(customer_id=other.id, import_id=batch.id, customer_account_name=other.name, opportunity_number='FOREIGN')])
    db_session.commit()
    path = f'/api/customers/{account.id}/deals/promote/'
    payload = {'vendor': {'import_id': batch.id, 'opportunity_number': 'SYN-1'}}
    first = client.post(path, headers=headers('deal_owner'), json=payload)
    assert first.status_code == 200, first.text
    deal = first.json()['deal']
    assert first.json()['created'] is True and deal['amount'] is None
    assert deal['vendor_evidence'] == [payload['vendor']]
    second = client.post(path, headers=headers('deal_owner'), json=payload).json()
    assert second['created'] is False and second['deal']['id'] == deal['id']
    # A manually linked deal has evidence but no promotion source key.
    db_session.get(Deal, deal['id']).source_key = None
    db_session.commit()
    assert client.post(path, headers=headers('deal_owner'), json=payload).json()['deal']['id'] == deal['id']
    assert client.post(path, headers=headers('deal_owner'), json={'vendor': {'import_id': batch.id, 'opportunity_number': 'FOREIGN'}}).status_code == 404
    db_session.query(PartnerPipeline).delete()
    db_session.commit()
    # Retained evidence survives source removal; retries still return the deal.
    assert client.post(path, headers=headers('deal_owner'), json=payload).json()['deal']['id'] == deal['id']
    updated = client.put(f"/api/deals/{deal['id']}/", headers=headers('deal_owner'), json={'expected_version': deal['version'], 'vendor_evidence': [payload['vendor']]} )
    assert updated.status_code == 200, updated.text
    assert client.request('DELETE', f"/api/deals/{deal['id']}/", headers=headers('deal_owner'), json={'expected_version': updated.json()['version']}).status_code == 204
    assert db_session.query(deal_vendor_evidence).count() == 0


def test_attention_promotion_evidence_timeline_and_closing_worklist(client, db_session, world):
    from datetime import date, timedelta

    from backend.models.sales_note import SalesNote
    account, _, owner = world
    note = SalesNote(customer_id=account.id, title='Synthetic follow-up', content='Discuss next steps', category='follow_up', note_date=date.today())
    db_session.add(note)
    db_session.commit()
    promoted = client.post(f'/api/customers/{account.id}/deals/promote/', headers=headers('deal_owner'), json={'attention_id': f'follow-up-note-{note.id}'})
    assert promoted.status_code == 200, promoted.text
    deal = promoted.json()['deal']
    assert deal['note_ids'] == [note.id]
    update = client.put(f"/api/deals/{deal['id']}/", headers=headers('deal_owner'), json={'expected_version': deal['version'], 'close_date': (date.today() + timedelta(days=10)).isoformat()})
    assert update.status_code == 200
    timeline = client.get(f'/api/customers/{account.id}/timeline/', headers=headers('deal_owner')).json()
    events = [item for item in timeline['items'] if item['kind'] == 'deal']
    assert events and events[0]['source_ref'] == f"module=deal&id={deal['id']}"
    closing = client.get('/api/worklist/mine/', headers=headers('deal_owner')).json()['closing_deals']
    assert [item['id'] for item in closing] == [deal['id']]
    db_session.query(CustomerUser).filter_by(user_id=owner.id).delete()
    db_session.commit()
    assert client.get('/api/worklist/mine/', headers=headers('deal_owner')).json()['closing_deals'] == []


def test_deal_graph_brief_and_team_amounts_remain_distinct(db_session, world):
    from backend.models.sales_access import SalesReporting
    from backend.services.account_brief import build_account_brief
    from backend.services.customer_intelligence import build_customer_intelligence_graph
    from backend.services.deal_service import create_deal
    from backend.services.team_rollup_service import team_rollup_for
    account, _, owner = world
    manager = User(username='deal_manager', sales_role='sales_manager', approved=1, is_active=1)
    db_session.add(manager)
    db_session.flush()
    db_session.add(SalesReporting(manager_user_id=manager.id, rep_user_id=owner.id))
    db_session.commit()
    first = create_deal(db_session, account.id, {'name': 'USD deal', 'currency': 'USD', 'amount_minor': 100, 'amount_basis': 'acv'}, owner.username)
    create_deal(db_session, account.id, {'name': 'EUR deal', 'currency': 'EUR', 'amount_minor': 200, 'amount_basis': 'acv'}, owner.username)
    create_deal(db_session, account.id, {'name': 'Unknown deal'}, owner.username)
    graph = build_customer_intelligence_graph(db_session, account.id)
    nodes = {node['id']: node for node in graph['nodes']}
    assert nodes[f"deal-{first['id']}"]['metadata']['source'] == 'rep_deal'
    assert all(link['source'] in nodes and link['target'] in nodes for link in graph['links'])
    brief = build_account_brief(db_session, {'is_admin': 1, 'username': 'admin'}, account.id)
    assert 'Rep-maintained deals (separate commercial records)' in brief['markdown']
    totals = team_rollup_for(db_session, {'username': manager.username, 'sales_role': 'sales_manager'})['team']['rep_deals']
    assert totals['counts']['open'] == 3
    assert {(row['currency'], row['basis'], row['minor'], row['unknown_amounts']) for row in totals['open_amounts']} == {('USD', 'acv', 100, 0), ('EUR', 'acv', 200, 0), ('USD', None, None, 1)}
