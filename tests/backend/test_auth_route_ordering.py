"""Regression coverage for literal admin user-route ordering (AUTH-01)."""

from backend.auth import create_access_token


def _admin_headers() -> dict[str, str]:
    token = create_access_token({"sub": "admin", "is_admin": True})
    return {"Authorization": f"Bearer {token}"}


def test_literal_admin_user_routes_resolve(client, db_session):
    """Literal list/create paths must reach their admin handlers."""
    headers = _admin_headers()

    pending_response = client.get(
        "/api/auth/users/pending/", headers=headers
    )
    assert pending_response.status_code == 200, pending_response.text
    assert isinstance(pending_response.json(), list)

    all_response = client.get("/api/auth/users/all/", headers=headers)
    assert all_response.status_code == 200, all_response.text
    assert isinstance(all_response.json(), list)

    create_response = client.post(
        "/api/auth/users/",
        json={
            "username": "route_order_user",
            "password": "Route" + "Order123!x",
        },
        headers=headers,
    )
    assert create_response.status_code == 201, create_response.text
    assert create_response.json()["username"] == "route_order_user"


def test_literal_admin_user_routes_precede_parameterized_route(client):
    """Pin the auth router's declaration order in the assembled app."""
    app_routes = []
    for route in client.app.routes:
        included_router = getattr(route, "original_router", None)
        app_routes.extend(included_router.routes if included_router else [route])

    auth_user_paths = [
        route.path.removeprefix("/api/auth")
        for route in app_routes
        if getattr(route, "path", "").startswith("/api/auth/users/")
    ]

    parameterized_index = auth_user_paths.index("/users/{user_id}/")
    assert auth_user_paths.index("/users/pending/") < parameterized_index
    assert auth_user_paths.index("/users/all/") < parameterized_index


def test_deactivated_admin_token_cannot_manage_users(client, db_session):
    from backend.models.use_case import User

    admin = db_session.query(User).filter_by(username="admin").one()
    headers = _admin_headers()
    assert client.get("/api/auth/users/all/", headers=headers).status_code == 200
    admin.is_active = 0
    db_session.commit()

    responses = [
        client.get("/api/auth/users/all/", headers=headers),
        client.post("/api/auth/approve/someuser/", headers=headers),
        client.delete("/api/auth/users/99999/", headers=headers),
    ]
    for response in responses:
        assert response.status_code == 403
        assert response.json()["detail"] == "Admin privileges required"


def test_api_key_requires_explicit_restrictions(client, monkeypatch):
    from unittest.mock import Mock

    import backend.auth as auth

    restrictions = {"customers": {"Acme": ["Sales"]},
                    "all_customers": ["Engineering"], "is_admin": False}
    monkeypatch.setenv("SAIL_DEPT_RESTRICTIONS", "configured")
    monkeypatch.setattr(auth, "_DEPT_RESTRICTIONS", {"known-key": restrictions})

    response = client.get("/api/integrations/status/", headers={"X-API-Key": "unknown-key"})
    assert response.status_code == 401
    response = client.get("/api/integrations/status/", headers={"X-API-Key": "known-key"})
    assert response.status_code == 200
    request = Mock(headers={"X-API-Key": "known-key"})
    user = auth.get_user_from_request(request)
    assert user == {"username": "dept-api-key", "department": None,
                    "allowed_departments": ["Engineering"],
                    "customer_allowed_departments": {"Acme": ["Sales"]}, "is_admin": 0}
    # the raw key must never surface as the identity (created_by leak fix)
    assert "known-key" not in str(user)
    assert auth._user_has_dept_access(user, "Engineering")
    assert auth._user_has_dept_access(user, "Sales", "Acme")
    assert not auth._user_has_dept_access(user, "Sales", "Other")
