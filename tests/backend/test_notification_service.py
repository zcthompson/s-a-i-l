"""Tests for ConnectionManager in notification_service.py.

Tests the WebSocket connection manager's connect/disconnect/broadcast
lifecycle, global vs use-case-scoped connections, and cleanup of
disconnected peers.
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

from unittest.mock import AsyncMock, MagicMock

import pytest
from backend.services.notification_service import ConnectionManager


def _make_websocket():
    """Build a mock WebSocket that records send_json calls."""
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.accept = AsyncMock()
    ws.disconnect = AsyncMock()
    return ws


# ── Connection Manager ────────────────────────────────────────────────────

class TestConnectionManagerInit:
    """Tests for ConnectionManager.__init__."""

    def test_empty_state(self):
        """Initial state has no connections."""
        mgr = ConnectionManager()
        assert mgr.active_connections == {}
        assert mgr.connection_count == 0


# ── Connect ───────────────────────────────────────────────────────────────

class TestConnect:
    """Tests for ConnectionManager.connect()."""

    @pytest.mark.asyncio
    async def test_accepts_connection(self):
        """connect() returns the WebSocket."""
        mgr = ConnectionManager()
        ws = _make_websocket()
        result = await mgr.connect(ws)
        assert result is ws

    @pytest.mark.asyncio
    async def test_global_connection(self):
        """No use_case_id → connection tagged as __global__."""
        mgr = ConnectionManager()
        ws = _make_websocket()
        await mgr.connect(ws)
        assert "__global__" in mgr.active_connections
        assert ws in mgr.active_connections["__global__"]
        assert mgr.connection_count == 1

    @pytest.mark.asyncio
    async def test_scoped_connection(self):
        """use_case_id → connection stored under that key."""
        mgr = ConnectionManager()
        ws = _make_websocket()
        await mgr.connect(ws, use_case_id="42")
        assert "42" in mgr.active_connections
        assert ws in mgr.active_connections["42"]
        assert mgr.connection_count == 1

    @pytest.mark.asyncio
    async def test_multiple_scoped_connections(self):
        """Multiple WS to the same use_case_id all stored."""
        mgr = ConnectionManager()
        ws1 = _make_websocket()
        ws2 = _make_websocket()
        await mgr.connect(ws1, use_case_id="1")
        await mgr.connect(ws2, use_case_id="1")
        assert len(mgr.active_connections["1"]) == 2
        assert mgr.connection_count == 2

    @pytest.mark.asyncio
    async def test_global_and_scoped_coexist(self):
        """Global and scoped connections can coexist."""
        mgr = ConnectionManager()
        gw = _make_websocket()
        sw = _make_websocket()
        await mgr.connect(gw)
        await mgr.connect(sw, use_case_id="x")
        assert "__global__" in mgr.active_connections
        assert "x" in mgr.active_connections
        assert mgr.connection_count == 2


# ── Disconnect ────────────────────────────────────────────────────────────

class TestDisconnect:
    """Tests for ConnectionManager.disconnect()."""

    @pytest.mark.asyncio
    async def test_disconnected_ws_removed(self):
        """disconnect() removes the WS from its group."""
        mgr = ConnectionManager()
        ws = _make_websocket()
        await mgr.connect(ws, use_case_id="5")
        mgr.disconnect(ws, use_case_id="5")
        assert "5" not in mgr.active_connections
        assert mgr.connection_count == 0

    @pytest.mark.asyncio
    async def test_global_disconnect(self):
        """Disconnecting global WS cleans up __global__ key."""
        mgr = ConnectionManager()
        ws = _make_websocket()
        await mgr.connect(ws)
        mgr.disconnect(ws)
        assert "__global__" not in mgr.active_connections
        assert mgr.connection_count == 0

    @pytest.mark.asyncio
    async def test_multiple_connections_remaining(self):
        """If 2 WS are scoped, disconnecting one leaves the other."""
        mgr = ConnectionManager()
        ws1 = _make_websocket()
        ws2 = _make_websocket()
        await mgr.connect(ws1, use_case_id="1")
        await mgr.connect(ws2, use_case_id="1")
        mgr.disconnect(ws1, use_case_id="1")
        assert "1" in mgr.active_connections
        assert len(mgr.active_connections["1"]) == 1
        assert ws2 in mgr.active_connections["1"]
        assert mgr.connection_count == 1

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_key(self):
        """Disconnecting from a key that doesn't exist is a no-op."""
        mgr = ConnectionManager()
        ws = _make_websocket()
        # No connect happened
        mgr.disconnect(ws, use_case_id="nonexistent")
        assert "nonexistent" not in mgr.active_connections
        assert mgr.connection_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_unknown_websocket(self):
        """Disconnecting a WS that was never connected is safe."""
        mgr = ConnectionManager()
        ws = _make_websocket()
        mgr.disconnect(ws, use_case_id="1")
        assert "1" not in mgr.active_connections


# ── Broadcast ─────────────────────────────────────────────────────────────

class TestBroadcast:
    """Tests for ConnectionManager.broadcast()."""

    @pytest.mark.asyncio
    async def test_sends_to_scoped_connections(self):
        """Message reaches all connections in the targeted use_case group."""
        mgr = ConnectionManager()
        ws1 = _make_websocket()
        ws2 = _make_websocket()
        await mgr.connect(ws1, use_case_id="10")
        await mgr.connect(ws2, use_case_id="10")

        await mgr.broadcast({"type": "test"}, use_case_id="10")
        ws1.send_json.assert_called_once()
        ws2.send_json.assert_called_once()
        assert ws1.send_json.call_args[0][0] == {"type": "test"}
        assert ws2.send_json.call_args[0][0] == {"type": "test"}

    @pytest.mark.asyncio
    async def test_sends_to_global_connections(self):
        """Global connections receive broadcast messages."""
        mgr = ConnectionManager()
        gw1 = _make_websocket()
        gw2 = _make_websocket()
        await mgr.connect(gw1)
        await mgr.connect(gw2)

        await mgr.broadcast({"type": "global"})
        gw1.send_json.assert_called_once()
        gw2.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_sends_to_both_scoped_and_global(self):
        """A scoped broadcast reaches that group + all global."""
        mgr = ConnectionManager()
        sw = _make_websocket()
        gw = _make_websocket()
        await mgr.connect(sw, use_case_id="1")
        await mgr.connect(gw)

        await mgr.broadcast({"type": "scoped"}, use_case_id="1")
        sw.send_json.assert_called_once()
        gw.send_json.assert_called_once()
        assert gw.send_json.call_args[0][0] == {"type": "scoped"}

    @pytest.mark.asyncio
    async def test_no_connections_yields_no_calls(self):
        """Broadcast to an empty connection set does nothing."""
        mgr = ConnectionManager()
        await mgr.broadcast({"type": "orphan"}, use_case_id="999")

    @pytest.mark.asyncio
    async def test_broken_connection_cleaned(self):
        """Failed send_json removes the broken connection."""
        mgr = ConnectionManager()
        bad_ws = _make_websocket()
        good_ws = _make_websocket()
        bad_ws.send_json.side_effect = Exception("broken pipe")
        await mgr.connect(bad_ws, use_case_id="bad")
        await mgr.connect(good_ws, use_case_id="bad")

        await mgr.broadcast({"type": "test"}, use_case_id="bad")

        # Good connection received the message (and the broken one was
        # attempted exactly once before failing), while the broken
        # connection was removed from the channel index during
        # broadcast (dead-socket cleanup covers every index).
        good_ws.send_json.assert_called_once()
        bad_ws.send_json.assert_called_once()
        assert mgr.connection_count == 1
        assert good_ws in mgr.active_connections.get("bad", set())
        assert bad_ws not in mgr.active_connections.get("bad", set())

    @pytest.mark.asyncio
    async def test_send_json_called_with_correct_message(self):
        """broadcast() passes the exact message dict to send_json."""
        mgr = ConnectionManager()
        ws = _make_websocket()
        await mgr.connect(ws)

        expected = {"type": "scoring", "data": {"score": 85}, "ts": "2026-08-01"}
        await mgr.broadcast(expected)
        ws.send_json.assert_called_with(expected)


# ── Connection Count ──────────────────────────────────────────────────────

class TestConnectionCount:
    """Tests for ConnectionManager.connection_count."""

    @pytest.mark.asyncio
    async def test_empty_count(self):
        """Zero connections → count is 0."""
        mgr = ConnectionManager()
        assert mgr.connection_count == 0

    @pytest.mark.asyncio
    async def test_global_only_count(self):
        """One global connection → count is 1."""
        mgr = ConnectionManager()
        await mgr.connect(_make_websocket())
        assert mgr.connection_count == 1

    @pytest.mark.asyncio
    async def test_multiple_groups(self):
        """Scoped + global connections are counted together."""
        mgr = ConnectionManager()
        await mgr.connect(_make_websocket(), use_case_id="a")
        await mgr.connect(_make_websocket(), use_case_id="b")
        await mgr.connect(_make_websocket())
        assert mgr.connection_count == 3

    @pytest.mark.asyncio
    async def test_count_after_disconnect(self):
        """Connection count decrements after disconnect."""
        mgr = ConnectionManager()
        ws1 = _make_websocket()
        ws2 = _make_websocket()
        await mgr.connect(ws1, use_case_id="1")
        await mgr.connect(ws2, use_case_id="1")
        assert mgr.connection_count == 2
        mgr.disconnect(ws1, use_case_id="1")
        assert mgr.connection_count == 1


# ── Send Notification Helper ──────────────────────────────────────────────

class TestSendNotificationHelper:
    """Tests for the send_notification() helper function."""

    @pytest.mark.asyncio
    async def test_formats_message(self):
        """Helper wraps event_type/data in a message dict with timestamp."""
        from backend.services.notification_service import (
            connection_manager,
            send_notification,
        )

        ws = _make_websocket()
        await connection_manager.connect(ws, use_case_id="5")

        await send_notification("scoring", {"score": 75}, use_case_id="5")

        call = ws.send_json.call_args[0][0]
        assert call["type"] == "scoring"
        assert call["data"] == {"score": 75}
        assert "timestamp" in call

    @pytest.mark.asyncio
    async def test_global_broadcast(self):
        """No use_case_id → broadcasts to global connections."""
        from backend.services.notification_service import (
            connection_manager,
            send_notification,
        )

        ws = _make_websocket()
        await connection_manager.connect(ws)

        await send_notification("status_change", {"status": "completed"})

        call = ws.send_json.call_args[0][0]
        assert call["type"] == "status_change"
        assert call["data"] == {"status": "completed"}
