"""Verify authorized dashboard account sets and counts."""
import pytest

from tests.backend.test_part13_dv_wave2 import _token
from tests.backend.test_part13_dv_wave2 import world as _world_fixture


@pytest.fixture
def scope_world(db_session):
    return _world_fixture.__wrapped__(db_session)


@pytest.mark.parametrize(
    ("username", "legacy_keys", "central_keys"),
    [
        ("w2_rep", {"team"}, {"team"}),
        ("w2_sm", set(), {"team"}),
        ("w2_is", set(), {"inside"}),
        ("w2_ops", set(), {"team"}),
        ("w2_aud", set(), {"team", "inside", "other"}),
        ("w2_sad", set(), {"team", "inside", "other"}),
        ("w2_sm2", set(), set()),
    ],
)
def test_dashboard_sources_have_distinct_role_scopes(client, scope_world, username, legacy_keys, central_keys):
    headers = _token(username)
    ids = set(scope_world[k] for k in ("team", "inside", "other"))
    expected_legacy = {scope_world[k] for k in legacy_keys}
    expected_central = {scope_world[k] for k in central_keys}
    legacy = client.get('/api/customers/me/customers/', headers=headers)
    customers = client.get('/api/customers/', headers=headers)
    stats = client.get('/api/customers/stats/', headers=headers)
    impact = client.get('/api/account-impact/portfolio/', headers=headers)
    for response in (legacy, customers, stats, impact):
        assert response.status_code == 200, response.text
    assert {row['customer_id'] for row in legacy.json()} & ids == expected_legacy
    assert {row['id'] for row in customers.json()} & ids == expected_central
    assert {row['customer_id'] for row in stats.json()['customers']} & ids == expected_central
    assert stats.json()['total_customers'] == len(expected_central)
    assert {row['customer_id'] for row in impact.json()['customers']} & ids == expected_central


def test_admin_my_view_stats_and_impact_share_account_sets(client, db_session, scope_world):
    from backend.models.account_membership import AccountMembership
    from backend.models.use_case import CustomerUser, UseCase, User

    admin = db_session.query(User).filter(User.is_admin == 1).one()
    db_session.add(CustomerUser(customer_id=scope_world['team'], user_id=admin.id, role='member'))
    db_session.add(AccountMembership(customer_id=scope_world['inside'], user_id=admin.id, role='co_owner'))
    db_session.add(UseCase(title='Inside account use case', customer_id=scope_world['inside'], status='active'))
    db_session.commit()
    headers = _token('admin')
    stats = client.get('/api/customers/stats/?my_view=true', headers=headers)
    impact = client.get('/api/account-impact/portfolio/?my_view=true', headers=headers)
    assert stats.status_code == 200 and impact.status_code == 200
    ids = {scope_world['team'], scope_world['inside'], scope_world['other']}
    assert {row['customer_id'] for row in stats.json()['customers']} & ids == {scope_world['team'], scope_world['inside']}
    assert {row['customer_id'] for row in impact.json()['customers']} & ids == {scope_world['team'], scope_world['inside']}


def test_membership_only_customer_appears_in_portfolio_but_not_legacy_my_list(client, db_session, scope_world):
    from backend.models.account_membership import AccountMembership
    from backend.models.use_case import User

    rep = db_session.query(User).filter_by(username='w2_rep').one()
    db_session.add(AccountMembership(customer_id=scope_world['other'], user_id=rep.id, role='co_owner'))
    db_session.commit()
    headers = _token('w2_rep')
    legacy = client.get('/api/customers/me/customers/', headers=headers)
    impact = client.get('/api/account-impact/portfolio/', headers=headers)
    assert legacy.status_code == impact.status_code == 200
    assert scope_world['other'] not in {row['customer_id'] for row in legacy.json()}
    assert scope_world['other'] in {row['customer_id'] for row in impact.json()['customers']}


def test_ps_admin_does_not_gain_sales_portfolio_access_from_junction(client, db_session, scope_world):
    from backend.models.use_case import CustomerUser

    from tests.backend.common import _mk_user

    user = _mk_user(db_session, 'scope_ps_admin')
    user.role = 'ps_admin'
    db_session.add(CustomerUser(customer_id=scope_world['team'], user_id=user.id, role='member'))
    db_session.commit()
    headers = _token('scope_ps_admin')
    response = client.get('/api/account-impact/portfolio/', headers=headers)
    assert response.status_code == 200
    assert response.json()['customers'] == []
    legacy = client.get('/api/customers/me/customers/', headers=headers)
    customers = client.get('/api/customers/', headers=headers)
    stats = client.get('/api/customers/stats/', headers=headers)
    assert legacy.status_code == customers.status_code == stats.status_code == 200
    assert scope_world['team'] not in {row['customer_id'] for row in legacy.json()}
    assert scope_world['team'] not in {row['id'] for row in customers.json()}
    assert scope_world['team'] not in {row['customer_id'] for row in stats.json()['customers']}


@pytest.mark.parametrize(
    ("username", "customer_key", "can_score", "can_manage"),
    [
        ("admin", "team", True, True),
        ("w2_rep", "team", True, True),
        ("w2_sm", "team", True, False),
        ("w2_aud", "team", False, False),
        ("w2_sad", "team", False, False),
        ("w2_is", "inside", True, False),
        ("w2_ops", "team", False, False),
    ],
)
def test_portfolio_action_hints_follow_account_permissions(client, scope_world, username, customer_key, can_score, can_manage):
    response = client.get('/api/account-impact/portfolio/', headers=_token(username))
    assert response.status_code == 200
    row = next(r for r in response.json()['customers'] if r['customer_id'] == scope_world[customer_key])
    assert row['can_score'] is can_score
    assert row['can_manage_customer'] is can_manage
