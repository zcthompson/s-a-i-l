"""WebSocket route for real-time notifications.

The single authoritative ``ConnectionManager`` lives in
``backend.services.notification_service`` so every producer (comments,
scoring, status changes) broadcasts into the same connection pool that this
endpoint accepts clients into.

Auth: browsers cannot set headers on a WebSocket handshake, and the charter
forbids placing the JWT in a URL — so the client must send
``{"auth": "<JWT>"}`` as the FIRST message after the connection is
established. Connections that do not authenticate (or send an invalid
token) within the handshake window are closed with code 4401 before any
traffic is registered.
"""

import asyncio
import json

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from backend.auth import decode_access_token
from backend.dependencies import get_db
from backend.models.use_case import CustomerUser, UseCase, User
from backend.services import sales_access
from backend.services.notification_service import connection_manager

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

_AUTH_HANDSHAKE_TIMEOUT = 10.0


@router.websocket("/ws/notifications")
async def websocket_notifications(
    websocket: WebSocket,
    use_case_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Connect to receive real-time notifications.

    The client must send ``{"auth": "<JWT>"}`` as the first message after
    connecting. Query param ``use_case_id`` subscribes to notifications for
    a specific use case; omit it to receive all notifications.
    """
    await websocket.accept()
    try:
        first = await asyncio.wait_for(
            websocket.receive_text(), timeout=_AUTH_HANDSHAKE_TIMEOUT
        )
        payload = json.loads(first)
        token = payload.get("auth") if isinstance(payload, dict) else None
        jwt_payload = decode_access_token(token) if token else None
        if jwt_payload is None:
            await websocket.close(code=4401)
            return
    except Exception:
        # Handshake timeout, malformed message, bad token, or disconnect
        # before auth — close without registering the connection.
        try:
            await websocket.close(code=4401)
        except Exception:
            pass
        return

    # Register the authenticated connection (already accepted above —
    # register() does not accept again). Also index by user so producers
    # can push per-recipient notifications directly.
    username = jwt_payload.get("sub") if isinstance(jwt_payload, dict) else None
    if use_case_id is not None:
        user = db.query(User).filter_by(username=username, is_active=1).first()
        use_case = db.get(UseCase, int(use_case_id)) if use_case_id.isdecimal() else None
        if user is None or use_case is None:
            await websocket.close(code=4403, reason="Not authorized")
            return
        grants = db.query(CustomerUser).filter_by(user_id=user.id).all()
        context = {"username": user.username, "user_id": user.id,
                   "is_admin": user.is_admin, "role": user.role,
                   "sales_role": user.sales_role,
                   "customer_ids": [grant.customer_id for grant in grants],
                   "junction_roles": {grant.customer_id: grant.role for grant in grants}}
        if not sales_access.can(context, db, sales_access.CAP_READ, use_case.customer_id):
            await websocket.close(code=4403, reason="Not authorized")
            return
        use_case_id = str(use_case.id)
    connection_manager.register(websocket, use_case_id, username)
    try:
        while True:
            # Keep the connection alive — client sends 'ping', we respond 'pong'
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        connection_manager.disconnect(websocket, use_case_id, username)
