"""Regression tests: auth + multi-tenant scoping of collaboration endpoints.

2026-08-22 session (collaboration side-panel audit): the comment and
notification routes had NO authentication — anonymous read/write, the
comment author was a client-supplied field (impersonation), any caller could
read/mark ANY user's notifications, the integrations routes were open, and
the WebSocket endpoint accepted unauthenticated connections while its
producer broadcast into a SECOND ConnectionManager instance (real-time
notifications never reached any client).

All fixed: JWT required everywhere, CustomerUser junction scoping, author
derived from the JWT, notification ownership, single shared ConnectionManager
+ auth handshake (code 4401 on failure).

Run: pytest tests/backend/test_collaboration_auth.py -v
"""

import json
import os
import time

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")


from unittest.mock import patch

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.backend.common import _token

_FAKE_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"

@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
    """Route-level auth tests: make the real JWT auth see the shared
    session's state (same pattern as test_analytics_scoping.py).

    The real get_user_from_request resolves the user AND re-queries the
    CustomerUser junction via its OWN engine/connection to the test DB file,
    seeing only truly-committed rows. The test's seeded users/junctions live
    in the shared session's transaction, so an unpatched lookup misfires the
    admin/junction checks (2026-08-22 collaboration audit). Both the user
    lookup and the junction engine are routed to the shared test engine so
    the checks see the seeded state deterministically.
    """
    from backend.models.use_case import User

    from backend import auth as auth_mod

    bind = db_session.get_bind()
    shared_engine = getattr(bind, "engine", bind)

    if not db_session.query(User).count():
        db_session.add(User(username="admin", email="admin@test.local",
                            hashed_password=_FAKE_HASH,
                            display_name="Administrator", department="IT",
                            is_admin=1, approved=1, is_active=1))
        db_session.commit()

    def _lookup(username):
        user = db_session.query(User).filter(User.username == username).first()
        if not (user and user.is_active):
            return None
        return {
            "username": user.username,
            "email": user.email,
            "display_name": user.display_name,
            "department": user.department,
            "is_admin": user.is_admin,
            "role": user.role,
            "user_id": user.id,
        }

    def _shared_engine(*args, **kwargs):
        return shared_engine

    with patch.object(auth_mod, "_get_user_by_username", _lookup), \
         patch.object(auth_mod, "create_engine", _shared_engine):
        yield





def _seed(db_session):
    """Seed admin + owner/member/auditor/stranger on customer CollabCo,
    plus a customer-linked UC and a customer-less UC. Committed so the
    real auth lookup (separate connection, same test DB file) resolves
    users + junction context."""
    from backend.models.use_case import Customer, CustomerUser, UseCase, User

    users = {}
    for uname, admin in [
        ("cb_admin", 1), ("cb_owner", 0), ("cb_member", 0),
        ("cb_auditor", 0), ("cb_stranger", 0),
    ]:
        u = User(username=uname, email=f"{uname}@test.local",
                 hashed_password=_FAKE_HASH, display_name=uname,
                 is_admin=admin, approved=1, is_active=1)
        db_session.add(u)
        users[uname] = u
    db_session.commit()
    for u in users.values():
        db_session.refresh(u)

    cust = Customer(name="CollabCo", description="C")
    db_session.add(cust)
    db_session.commit()
    db_session.refresh(cust)

    db_session.add(CustomerUser(customer_id=cust.id, user_id=users["cb_owner"].id, role="owner"))
    db_session.add(CustomerUser(customer_id=cust.id, user_id=users["cb_member"].id, role="member"))
    db_session.add(CustomerUser(customer_id=cust.id, user_id=users["cb_auditor"].id, role="auditor"))
    db_session.commit()

    uc1 = UseCase(title="Collab UC", customer_id=cust.id, department="Eng",
                  status="active", created_by="seed")
    uc2 = UseCase(title="NoCustomer UC", customer_id=None, department="Eng",
                  status="active", created_by="seed")
    db_session.add_all([uc1, uc2])
    db_session.commit()
    db_session.refresh(uc1)
    db_session.refresh(uc2)
    # NOTE: the conftest db_session fixture is engine-bound, so every
    # db_session.commit() above is already a real DBAPI COMMIT (the seed is
    # in the file; route sessions see the same rows). Do NOT add a
    # db_session.connection().commit() here: it commits the connection's
    # root transaction out from under the session's still-active logical
    # transaction, and the next session.commit() raises
    # "This transaction is inactive".
    return {"users": users, "customer": cust, "uc1": uc1, "uc2": uc2}


def _notification_types(client, username: str, is_admin: bool = False) -> set:
    r = client.get("/api/use-cases/notifications/", headers=_token(username, is_admin))
    assert r.status_code == 200
    return {n["type"] for n in r.json()}


class TestAnonymousDenied:
    """No authentication → 401 on every collaboration endpoint."""

    def test_anonymous_get_comments_401(self, client, db_session):
        s = _seed(db_session)
        assert client.get(f"/api/use-cases/{s['uc1'].id}/comments/").status_code == 401

    def test_anonymous_post_comment_401(self, client, db_session):
        s = _seed(db_session)
        assert client.post(f"/api/use-cases/{s['uc1'].id}/comments/",
                           json={"content": "hi"}).status_code == 401

    def test_anonymous_update_delete_comment_401(self, client, db_session):
        _seed(db_session)
        assert client.put("/api/use-cases/comments/1/", json={"content": "x"}).status_code == 401
        assert client.delete("/api/use-cases/comments/1/").status_code == 401

    def test_anonymous_get_notifications_401(self, client, db_session):
        _seed(db_session)
        assert client.get("/api/use-cases/notifications/").status_code == 401

    def test_anonymous_mark_read_401(self, client, db_session):
        _seed(db_session)
        assert client.post("/api/use-cases/notifications/1/read/").status_code == 401


class TestJunctionScoping:
    """Access follows the CustomerUser junction (admin bypass)."""

    def test_member_reads_comments(self, client, db_session):
        s = _seed(db_session)
        r = client.get(f"/api/use-cases/{s['uc1'].id}/comments/", headers=_token("cb_member"))
        assert r.status_code == 200
        assert r.json() == []

    def test_stranger_without_junction_404(self, client, db_session):
        s = _seed(db_session)
        r = client.get(f"/api/use-cases/{s['uc1'].id}/comments/", headers=_token("cb_stranger"))
        # 404-first (R4/Q7): out-of-scope is the same 404 as a missing use case.
        assert r.status_code == 404
        assert r.json()["detail"] == "Use case not found"

    def test_auditor_cannot_post_comment(self, client, db_session):
        s = _seed(db_session)
        r = client.post(f"/api/use-cases/{s['uc1'].id}/comments/",
                        json={"content": "hi"}, headers=_token("cb_auditor"))
        assert r.status_code == 403

    def test_admin_reads_customerless_use_case(self, client, db_session):
        s = _seed(db_session)
        r = client.get(f"/api/use-cases/{s['uc2'].id}/comments/",
                       headers=_token("cb_admin", is_admin=True))
        assert r.status_code == 200

    def test_non_admin_cannot_post_customerless_use_case(self, client, db_session):
        s = _seed(db_session)
        r = client.post(f"/api/use-cases/{s['uc2'].id}/comments/",
                        json={"content": "hi"}, headers=_token("cb_member"))
        # A customer-less use case is out of every non-admin's scope (R2), so
        # it is the same 404 as a missing one (404-first, R4/Q7).
        assert r.status_code == 404


class TestCommentAuthorAndNotifications:
    """Author comes from the JWT (no impersonation); comments notify the
    customer's junction users (author excluded) plus valid @mentions."""

    def test_post_comment_authored_by_jwt_not_client(self, client, db_session):
        s = _seed(db_session)
        # Impersonation attempt: body claims "cb_admin", token is cb_member
        r = client.post(
            f"/api/use-cases/{s['uc1'].id}/comments/",
            json={"content": "Hello @cb_owner", "user_name": "cb_admin"},
            headers=_token("cb_member"),
        )
        assert r.status_code == 201
        assert r.json()["user_name"] == "cb_member"
        assert r.json()["content"] == "Hello @cb_owner"

        # Customer-level notification: owner + auditor receive comment_added;
        # the poster (member) is excluded; the mention adds a mention row
        assert _notification_types(client, "cb_owner") >= {"comment_added", "mention"}
        assert _notification_types(client, "cb_auditor") == {"comment_added"}
        assert _notification_types(client, "cb_member") == set()

    def test_unknown_mention_creates_no_notification(self, client, db_session):
        s = _seed(db_session)
        r = client.post(f"/api/use-cases/{s['uc1'].id}/comments/",
                        json={"content": "Hello @no_such_user"},
                        headers=_token("cb_member"))
        assert r.status_code == 201
        # Only the customer-level comment_added rows — no mention row
        assert "mention" not in _notification_types(client, "cb_owner")


class TestCommentOwnership:
    """Only the author or an admin may edit/delete a comment."""

    def test_update_own_comment(self, client, db_session):
        s = _seed(db_session)
        c = client.post(f"/api/use-cases/{s['uc1'].id}/comments/",
                        json={"content": "orig"}, headers=_token("cb_member")).json()
        r = client.put(f"/api/use-cases/comments/{c['id']}/",
                       json={"content": "edited"}, headers=_token("cb_member"))
        assert r.status_code == 200
        assert r.json()["content"] == "edited"

    def test_update_foreign_comment_403(self, client, db_session):
        s = _seed(db_session)
        c = client.post(f"/api/use-cases/{s['uc1'].id}/comments/",
                        json={"content": "orig"}, headers=_token("cb_member")).json()
        r = client.put(f"/api/use-cases/comments/{c['id']}/",
                       json={"content": "hijack"}, headers=_token("cb_owner"))
        assert r.status_code == 403

    def test_admin_updates_foreign_comment(self, client, db_session):
        s = _seed(db_session)
        c = client.post(f"/api/use-cases/{s['uc1'].id}/comments/",
                        json={"content": "orig"}, headers=_token("cb_member")).json()
        r = client.put(f"/api/use-cases/comments/{c['id']}/",
                       json={"content": "admin edit"},
                       headers=_token("cb_admin", is_admin=True))
        assert r.status_code == 200
        assert r.json()["content"] == "admin edit"

    def test_delete_own_comment(self, client, db_session):
        s = _seed(db_session)
        c = client.post(f"/api/use-cases/{s['uc1'].id}/comments/",
                        json={"content": "bye"}, headers=_token("cb_member")).json()
        r = client.delete(f"/api/use-cases/comments/{c['id']}/", headers=_token("cb_member"))
        assert r.status_code == 204
        r2 = client.get(f"/api/use-cases/{s['uc1'].id}/comments/", headers=_token("cb_member"))
        assert r2.json() == []

    def test_delete_foreign_comment_403(self, client, db_session):
        s = _seed(db_session)
        c = client.post(f"/api/use-cases/{s['uc1'].id}/comments/",
                        json={"content": "keep"}, headers=_token("cb_member")).json()
        r = client.delete(f"/api/use-cases/comments/{c['id']}/", headers=_token("cb_owner"))
        assert r.status_code == 403

    def test_update_missing_comment_404(self, client, db_session):
        _seed(db_session)
        r = client.put("/api/use-cases/comments/99999/", json={"content": "x"},
                       headers=_token("cb_admin", is_admin=True))
        assert r.status_code == 404


class TestNotificationOwnership:
    """A user only sees and marks their own notifications (admin bypass)."""

    def _seed_notifications(self, db_session):
        from backend.models.collaboration import Notification
        for uname in ("cb_member", "cb_stranger"):
            db_session.add(Notification(
                user_name=uname, type="scoring", message=f"msg for {uname}"
            ))
        db_session.commit()
        # (session.commit() is a real DBAPI COMMIT with the engine-bound
        # conftest fixture session — see _seed note; no
        # connection().commit() needed, and it must not be added.)

    def test_get_notifications_own_only(self, client, db_session):
        _seed(db_session)
        self._seed_notifications(db_session)
        # Passing someone else's user_name must NOT return their rows
        r = client.get("/api/use-cases/notifications/",
                       params={"user_name": "cb_stranger"},
                       headers=_token("cb_member"))
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["user_name"] == "cb_member"

    def test_mark_foreign_notification_404(self, client, db_session):
        _seed(db_session)
        self._seed_notifications(db_session)
        from backend.models.collaboration import Notification
        foreign = db_session.query(Notification).filter(
            Notification.user_name == "cb_stranger").first()
        r = client.post(f"/api/use-cases/notifications/{foreign.id}/read/",
                        headers=_token("cb_member"))
        # 404-first (R4/Q7): someone else's notification is the same 404 as a
        # missing one — no existence oracle.
        assert r.status_code == 404
        assert r.json()["detail"] == "Notification not found"

    def test_mark_own_notification_204(self, client, db_session):
        _seed(db_session)
        self._seed_notifications(db_session)
        from backend.models.collaboration import Notification
        own = db_session.query(Notification).filter(
            Notification.user_name == "cb_member").first()
        r = client.post(f"/api/use-cases/notifications/{own.id}/read/",
                        headers=_token("cb_member"))
        assert r.status_code == 204

    def test_admin_can_mark_any_notification(self, client, db_session):
        _seed(db_session)
        self._seed_notifications(db_session)
        from backend.models.collaboration import Notification
        foreign = db_session.query(Notification).filter(
            Notification.user_name == "cb_stranger").first()
        r = client.post(f"/api/use-cases/notifications/{foreign.id}/read/",
                        headers=_token("cb_admin", is_admin=True))
        assert r.status_code == 204

    def test_customer_filter_foreign_404(self, client, db_session):
        s = _seed(db_session)
        from backend.models.use_case import Customer
        other = Customer(name="OtherCo", description="O")
        db_session.add(other)
        db_session.commit()
        db_session.refresh(other)
        r = client.get("/api/use-cases/notifications/",
                       params={"customer_id": other.id},
                       headers=_token("cb_member"))
        # 404-first (R4/Q7): an out-of-scope filter must not confirm the
        # customer exists.
        assert r.status_code == 404

    def test_admin_customer_filter_200(self, client, db_session):
        s = _seed(db_session)
        from backend.models.use_case import Customer
        other = Customer(name="OtherCo2", description="O")
        db_session.add(other)
        db_session.commit()
        db_session.refresh(other)
        r = client.get("/api/use-cases/notifications/",
                       params={"customer_id": other.id},
                       headers=_token("cb_admin", is_admin=True))
        assert r.status_code == 200


class TestIntegrationsAuth:
    """External integration endpoints require authentication."""

    def test_status_requires_auth(self, client):
        assert client.get("/api/integrations/status/").status_code == 401

    def test_status_authenticated_200(self, client, db_session):
        # The conftest db_session fixture guarantees an active admin user
        r = client.get("/api/integrations/status/", headers=_token("admin", is_admin=True))
        assert r.status_code == 200

    def test_slack_requires_auth(self, client):
        assert client.post("/api/integrations/slack/send/",
                           json={"message": "x"}).status_code == 401

    def test_teams_requires_auth(self, client):
        assert client.post("/api/integrations/teams/send/",
                           json={"message": "x"}).status_code == 401

    def test_jira_requires_auth(self, client):
        assert client.post("/api/integrations/jira/create-ticket/",
                           json={"project_key": "P", "summary": "s",
                                 "description": "d"}).status_code == 401


class TestWebSocketAuth:
    """The WS endpoint requires the JWT as the first message (4401 otherwise)
    and shares its connection pool with the notification producers."""

    def test_ws_rejects_missing_auth(self, client, db_session):
        _seed(db_session)
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect("/api/notifications/ws/notifications") as ws:
                ws.send_text("nonsense")  # not a JSON auth payload
                ws.receive_text()
        assert excinfo.value.code == 4401

    def test_ws_rejects_invalid_token(self, client, db_session):
        _seed(db_session)
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect("/api/notifications/ws/notifications") as ws:
                ws.send_text('{"auth": "not-a-real-jwt"}')
                ws.receive_text()
        assert excinfo.value.code == 4401

    def test_ws_accepts_valid_token_ping_pong(self, client, db_session):
        _seed(db_session)
        token = _token("cb_admin", is_admin=True)["Authorization"].split(" ")[1]
        with client.websocket_connect("/api/notifications/ws/notifications") as ws:
            ws.send_text('{"auth": "%s"}' % token)
            ws.send_text("ping")
            assert ws.receive_text() == "pong"


class TestWebSocketTargeting:
    """Per-recipient targeting (2026-08-23): producers push each
    recipient's own notification row over that user's own sockets
    (notification_created events via the main-loop bridge) — not a
    channel-wide broadcast."""

    def test_targeted_push_reaches_the_recipient(self, client, db_session):
        seeded = _seed(db_session)
        cust = seeded["customer"]
        token = _token("cb_member")["Authorization"].split(" ")[1]
        with client.websocket_connect("/api/notifications/ws/notifications") as ws:
            ws.send_text('{"auth": "%s"}' % token)

            # Sync producer path (same call shape as threadpool route
            # handlers): fan out to every CollabCo junction user.
            from backend.services.collaboration_service import CollaborationService
            CollaborationService.broadcast_to_customer(
                db_session, cust.id, "status_change", "Status changed"
            )

            # cb_member's own socket receives their own row.
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "notification_created"
            assert msg["data"]["user_name"] == "cb_member"
            assert msg["data"]["type"] == "status_change"
            assert msg["data"]["customer_id"] == cust.id

    def test_targeted_push_not_leaked_to_stranger(self, client, db_session):
        seeded = _seed(db_session)
        cust = seeded["customer"]
        token = _token("cb_stranger")["Authorization"].split(" ")[1]
        with client.websocket_connect("/api/notifications/ws/notifications") as ws:
            ws.send_text('{"auth": "%s"}' % token)

            from backend.services.collaboration_service import CollaborationService
            CollaborationService.broadcast_to_customer(
                db_session, cust.id, "status_change", "Status changed"
            )

            # cb_stranger has no junction access to CollabCo: their next
            # frame must be the ping response — a leaked notification
            # would be queued ahead of it.
            ws.send_text("ping")
            assert ws.receive_text() == "pong"

    def test_disconnect_removes_user_from_index(self, client, db_session):
        from backend.services.notification_service import connection_manager
        _seed(db_session)
        token = _token("cb_member")["Authorization"].split(" ")[1]
        with client.websocket_connect("/api/notifications/ws/notifications") as ws:
            ws.send_text('{"auth": "%s"}' % token)
            ws.send_text("ping")
            # Assert the index only AFTER the pong: the handler emits
            # "pong" solely after the auth frame is decoded AND
            # register() has run, so a received pong causally guarantees
            # the per-recipient index entry exists. Asserting it right
            # after send_text (before any pong) races the app's
            # event-loop thread and flaked under CI load (run
            # 33349809997, issue #114).
            assert ws.receive_text() == "pong"
            assert "cb_member" in connection_manager.active_users
        # The route handler's WebSocketDisconnect path removed the socket;
        # bounded wait (in-process event, only scheduling jitter).
        deadline = time.time() + 2.0
        while "cb_member" in connection_manager.active_users and time.time() < deadline:
            time.sleep(0.05)
        assert "cb_member" not in connection_manager.active_users

    def test_schedule_send_without_main_loop_is_noop(self):
        from backend.services.notification_service import connection_manager
        saved = connection_manager._main_loop
        connection_manager.set_main_loop(None)
        try:
            assert connection_manager.schedule_send_to_user(
                "cb_member", {"type": "x", "data": {}}
            ) is None
        finally:
            connection_manager.set_main_loop(saved)


def test_comment_websocket_scope_and_payload(client, db_session):
    from backend.auth import create_access_token
    from backend.services.notification_service import connection_manager
    s = _seed(db_session)
    uc_id = s["uc1"].id
    url = f"/api/notifications/ws/notifications?use_case_id={uc_id}"
    with client.websocket_connect(url) as rejected:
        rejected.send_json({"auth": create_access_token({"sub": "cb_stranger"})})
        with pytest.raises(WebSocketDisconnect) as exc:
            rejected.receive_json()
        assert exc.value.code == 4403
    with client.websocket_connect("/api/notifications/ws/notifications") as global_ws:
        global_ws.send_json({"auth": create_access_token({"sub": "cb_stranger"})})
        global_ws.send_text("ping")
        assert global_ws.receive_text() == "pong"
        with client.websocket_connect(url) as scoped:
            scoped.send_json({"auth": create_access_token({"sub": "cb_owner"})})
            scoped.send_text("ping")
            assert scoped.receive_text() == "pong"
            response = client.post(f"/api/use-cases/{uc_id}/comments/", headers=_token("cb_owner"),
                                   json={"content": "private comment", "user_name": "cb_owner"})
            assert response.status_code == 201
            frame = scoped.receive_json()
            assert frame["type"] == "comment_added" and frame["data"] == {"use_case_id": uc_id}
            global_ws.send_text("ping")
            assert global_ws.receive_text() == "pong"
    assert not connection_manager.active_connections


def test_notification_health_requires_auth(client):
    response = client.get("/api/use-cases/notifications/health/")
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
