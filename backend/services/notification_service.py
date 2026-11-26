"""WebSocket connection manager for real-time notifications.

Supports customer-scoped notifications via the ``customer_users`` junction
table, plus per-recipient (per-user) targeting: each authenticated client is
indexed by username so producers can push a recipient's own notification row
directly instead of broadcasting it to a whole channel.

Sync producers (service code running in threadpool route handlers) schedule
sends onto the captured main event loop via
``asyncio.run_coroutine_threadsafe`` — the loop is captured at app startup
(see ``ConnectionManager.set_main_loop`` and the main.py lifespan hook).
"""
import asyncio
import logging
from datetime import UTC, datetime

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for real-time notifications."""

    def __init__(self):
        self.active_connections: dict[str, set[WebSocket]] = {}
        # Per-recipient index: username -> that user's sockets. A socket
        # lives in exactly ONE channel (UC key or "__global__") and, when
        # the client authenticated, in its user's set as well.
        self.active_users: dict[str, set[WebSocket]] = {}
        self._main_loop: asyncio.AbstractEventLoop | None = None

    def set_main_loop(self, loop: asyncio.AbstractEventLoop | None):
        """Capture the app's main event loop (called from the startup hook)."""
        self._main_loop = loop

    def register(self, websocket: WebSocket, use_case_id: str | None = None, user_name: str | None = None):
        """Register an ALREADY-accepted connection (no accept).

        Routes that authenticate before accepting (WS auth handshake) call
        this; ``connect()`` (accept + register) remains for simple callers.
        ``user_name`` additionally adds the socket to the per-recipient index.
        """
        if use_case_id:
            if use_case_id not in self.active_connections:
                self.active_connections[use_case_id] = set()
            self.active_connections[use_case_id].add(websocket)
        else:
            # Global connections get tagged with a unique key
            if "__global__" not in self.active_connections:
                self.active_connections["__global__"] = set()
            self.active_connections["__global__"].add(websocket)
        if user_name:
            if user_name not in self.active_users:
                self.active_users[user_name] = set()
            self.active_users[user_name].add(websocket)
        return websocket

    async def connect(self, websocket: WebSocket, use_case_id: str | None = None, user_name: str | None = None):
        """Accept a WebSocket connection and register it."""
        await websocket.accept()
        return self.register(websocket, use_case_id, user_name)

    def disconnect(self, websocket: WebSocket, use_case_id: str | None = None, user_name: str | None = None):
        """Remove a WebSocket connection from the channel and user indexes."""
        if use_case_id and use_case_id in self.active_connections:
            self.active_connections[use_case_id].discard(websocket)
            if not self.active_connections[use_case_id]:
                del self.active_connections[use_case_id]
        elif "__global__" in self.active_connections:
            self.active_connections["__global__"].discard(websocket)
            if not self.active_connections["__global__"]:
                del self.active_connections["__global__"]
        if user_name and user_name in self.active_users:
            self.active_users[user_name].discard(websocket)
            if not self.active_users[user_name]:
                del self.active_users[user_name]

    def _drop_everywhere(self, connection: WebSocket):
        """Drop a (dead) connection from every channel and user index."""
        for key in list(self.active_connections):
            self.active_connections[key].discard(connection)
            if not self.active_connections[key]:
                del self.active_connections[key]
        for key in list(self.active_users):
            self.active_users[key].discard(connection)
            if not self.active_users[key]:
                del self.active_users[key]

    async def broadcast(self, message: dict, use_case_id: str | None = None, *, include_global: bool = True):
        """Send a message to specific use case connections or all."""
        targets = []
        
        if use_case_id:
            targets.extend(self.active_connections.get(use_case_id, set()))
        if include_global:
            targets.extend(self.active_connections.get("__global__", set()))
        
        disconnected = set()
        for connection in targets:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)
        
        # Clean up disconnected connections
        for conn in disconnected:
            self._drop_everywhere(conn)

    async def send_to_user(self, user_name: str, message: dict):
        """Send a message to every socket registered for one user."""
        for connection in list(self.active_users.get(user_name, set())):
            try:
                await connection.send_json(message)
            except Exception:
                self._drop_everywhere(connection)

    def schedule_send_to_user(self, user_name: str, message: dict):
        """Schedule ``send_to_user`` on the captured main event loop.

        Intended for sync producer code (threadpool route handlers), where no
        event loop is running. No-op when the loop was not captured (bare
        scripts, or contexts that never hit the startup hook).
        """
        loop = self._main_loop
        if loop is None or loop.is_closed():
            logger.debug("send_to_user(%s): no main loop captured — skipped", user_name)
            return None
        return asyncio.run_coroutine_threadsafe(
            self.send_to_user(user_name, message), loop
        )

    @property
    def connection_count(self) -> int:
        """Total number of active connections (channel index; a socket may
        also appear in the per-user index and is counted once here)."""
        total = 0
        for connections in self.active_connections.values():
            total += len(connections)
        return total


# Module-level manager (matches existing pattern in monitoring.py, auth.py)
connection_manager = ConnectionManager()


def notify_user(user_name: str, notification: dict):
    """Push one recipient's notification row over their own sockets.

    Sync-safe: schedules the send on the main loop when called from sync
    service code; no-op when the loop is not captured. The event type is
    ``notification_created`` and ``data`` is the recipient's own
    notification row (including its ``user_name``).
    """
    message = {
        "type": "notification_created",
        "data": notification,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    connection_manager.schedule_send_to_user(user_name, message)


async def send_notification(event_type: str, data: dict, use_case_id: str | None = None):
    """Helper to broadcast a notification from business logic."""
    message = {
        "type": event_type,
        "data": data,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    await connection_manager.broadcast(message, use_case_id, include_global=event_type != "comment_added")
