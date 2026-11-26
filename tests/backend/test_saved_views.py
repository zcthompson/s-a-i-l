"""Owner isolation, validation, and disposable migration pins."""
import pytest
from backend.models.saved_view import SavedView
from backend.models.use_case import User
from sqlalchemy import inspect

from tests.backend.test_customer_contacts import headers
from tests.backend.test_migration_downgrade import _alembic


def test_crud(client, db_session):
    db_session.add(User(username="synthetic_other", is_active=1, approved=1))
    db_session.commit()
    payload = {"surface": "portfolio", "name": " My View ", "params": {"q": " hi ", "owner": None}}
    response = client.post("/api/saved-views/", headers=headers(), json=payload)
    assert response.status_code == 201, response.text
    view = response.json()["view"]
    assert response.json()["created"] is True
    assert view["name"] == "My View" and view["schema_version"] == 1
    assert view["params"] == {"q": "hi", "owner": None}
    # Recorded limitation: edits are last-writer-wins; there is no CAS.
    payload.update(name=" my VIEW ", params={"q": "latest"})
    response = client.post("/api/saved-views/", headers=headers(), json=payload)
    assert response.status_code == 200
    assert response.json()["created"] is False
    assert response.json()["view"]["id"] == view["id"]
    assert response.json()["view"]["params"] == {"q": "latest"}
    assert len(client.get("/api/saved-views/", headers=headers()).json()["views"]) == 1
    assert client.get("/api/saved-views/", headers=headers("synthetic_other")).json() == {"views": []}
    path = f'/api/saved-views/{view["id"]}/'
    response = client.delete(path, headers=headers("synthetic_other"))
    assert response.status_code == 404 and response.json()["detail"] == "View not found"
    assert client.delete(path, headers=headers()).status_code == 204
    assert client.delete(path, headers=headers()).status_code == 404
    fk = next(iter(SavedView.__table__.c.user_id.foreign_keys))
    assert fk.target_fullname == "users.id" and fk.ondelete == "CASCADE"


@pytest.mark.parametrize("patch,detail", [
    ({"params": {"bad": "x"}}, "Unknown filter parameter: bad"),
    ({"params": {"q": 2}}, "Filter parameter values must be strings or null"),
    ({"params": []}, "Filter parameters must be a dict"),
    ({"params": {"q": "x" * 201}}, "Filter parameter values are limited to 200 characters"),
    ({"name": " "}, "View name must be 1-100 characters"),
    ({"name": "x" * 101}, "View name must be 1-100 characters"),
    ({"surface": "other"}, "Unknown surface: other"),
])
def test_validation(client, db_session, patch, detail):
    response = client.post("/api/saved-views/", headers=headers(), json={
        "surface": "portfolio", "name": "Synthetic", "params": {}, **patch})
    assert response.status_code == 422 and response.json()["detail"] == detail


def test_auth_surface(client, db_session):
    response = client.get("/api/saved-views/?surface=other", headers=headers())
    assert response.status_code == 422 and response.json()["detail"] == "Unknown surface: other"
    assert client.get("/api/saved-views/").status_code == 401
    assert client.get("/api/worklist/mine/").status_code == 401


def test_migration(tmp_path):
    from sqlalchemy import create_engine
    url = f"sqlite:///{tmp_path / 'saved-views.db'}"
    _alembic(url, "upgrade", "0019_add_import_amount_issues")
    _alembic(url, "upgrade", "head")
    engine = create_engine(url)
    try:
        assert inspect(engine).has_table("saved_views")
        _alembic(url, "stamp", "0019_add_import_amount_issues")
        _alembic(url, "upgrade", "head")
        _alembic(url, "check")
        _alembic(url, "downgrade", "base")
        assert not inspect(engine).has_table("saved_views")
        _alembic(url, "upgrade", "head")
        _alembic(url, "check")
    finally:
        engine.dispose()


def test_list_order_and_service_query_counts(db_session):
    from backend.services import saved_view_service as service

    from tests.backend.test_customer_contacts import statements

    uid = db_session.query(User.id).filter_by(username="admin").scalar()
    for name in (" Zulu ", "alpha"):
        with statements(db_session) as sql:
            _, created = service.save_view(db_session, uid, "portfolio", name, {"q": " " + "x" * 200 + " "})
        assert created and len(sql) <= 2
    with statements(db_session) as sql:
        _, created = service.save_view(db_session, uid, "portfolio", "ALPHA", {})
    assert not created and len(sql) <= 2
    with statements(db_session) as sql:
        views = service.list_views(db_session, uid, "portfolio")
    assert len(sql) == 1
    assert [v["name"] for v in views] == ["alpha", "Zulu"]


def test_account_views_scope_version_validation_and_owner_isolation(client, db_session):
    from backend.models.use_case import Customer, CustomerUser
    accounts = [Customer(name='Saved account A'), Customer(name='Saved account B')]
    user = User(username='saved_account_owner', is_active=1, approved=1, sales_role='rep')
    db_session.add_all([*accounts, user])
    db_session.flush()
    db_session.add(CustomerUser(customer_id=accounts[0].id, user_id=user.id, role='owner'))
    db_session.commit()
    payload = {'surface': 'account_deals', 'name': 'Closing', 'params': {'customer_id': str(accounts[0].id), 'stage': '99999', 'owner': 'unassigned', 'sort': 'close', 'layout': 'board'}}
    result = client.post('/api/saved-views/', headers=headers(user.username), json=payload)
    assert result.status_code == 201, result.text
    assert result.json()['view']['schema_version'] == 2
    params = {'surface': 'account_deals', 'customer_id': accounts[0].id}
    assert len(client.get('/api/saved-views/', headers=headers(user.username), params=params).json()['views']) == 1
    assert client.get('/api/saved-views/', headers=headers(), params=params).json()['views'] == []
    assert client.post('/api/saved-views/', headers=headers(user.username), json={**payload, 'params': {**payload['params'], 'customer_id': str(accounts[1].id)}}).status_code == 404
    assert client.get('/api/saved-views/', headers=headers(user.username), params={**params, 'customer_id': accounts[1].id}).status_code == 404
    for patch in ({'sort': 'invented'}, {'close_from': 'not-a-date'}, {'stage': 'unassigned'}, {'customer_id': str(2**80)}, {'q': 'wrong surface'}):
        assert client.post('/api/saved-views/', headers=headers(user.username), json={**payload, 'params': {**payload['params'], **patch}}).status_code == 422
    # Same display name on another account does not overwrite the first view.
    other = client.post('/api/saved-views/', headers=headers(), json={**payload, 'params': {**payload['params'], 'customer_id': str(accounts[1].id)}})
    assert other.status_code == 201
    assert client.delete(f"/api/saved-views/{result.json()['view']['id']}/", headers=headers()).status_code == 404


def test_concurrent_saved_view_upsert_preserves_unique_identity(db_session):
    """Concurrent first saves converge on one row for the owner and name."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from backend.services.saved_view_service import save_view
    from sqlalchemy.engine.create import create_engine
    from sqlalchemy.orm import Session

    owner = db_session.query(User).filter_by(username="admin").one()
    owner_id = owner.id
    db_session.commit()
    engine = create_engine(db_session.get_bind().url, pool_size=2, max_overflow=0,
                           connect_args={"timeout": 10} if db_session.bind.dialect.name == "sqlite" else {})
    barrier = Barrier(2, timeout=10)

    def save(value):
        with Session(engine) as session:
            barrier.wait()
            return save_view(session, owner_id, "portfolio", "Concurrent View", {"q": value})

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ("first", "second")))
        assert sorted(created for _, created in results) == [False, True]
        assert len({row["id"] for row, _ in results}) == 1
        db_session.expire_all()
        rows = db_session.query(SavedView).filter_by(user_id=owner_id, name_norm="concurrent view").all()
        assert len(rows) == 1 and rows[0].params["q"] in {"first", "second"}
    finally:
        engine.dispose()
