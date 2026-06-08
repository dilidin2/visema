"""Tests for visema.server.ws_manager — WebSocketManager singleton."""

import asyncio
import json

import pytest


# ── Connection management ─────────────────────────────────────────────────────


class TestConnectDisconnect:
    @pytest.mark.asyncio
    async def test_connect_accepts_and_tracks(self):
        from visema.server.ws_manager import get_manager, WebSocketManager

        manager = get_manager()
        ws = FakeSocket()

        await manager.connect(ws)

        assert ws.accepted is True
        assert manager.connection_count == 1

    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(self):
        from visema.server.ws_manager import get_manager

        manager = get_manager()
        ws = FakeSocket()

        await manager.connect(ws)
        assert manager.connection_count == 1

        await manager.disconnect(ws)
        assert manager.connection_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_connection(self):
        from visema.server.ws_manager import get_manager

        manager = get_manager()
        ws1 = FakeSocket()
        ws2 = FakeSocket()

        await manager.connect(ws1)
        assert manager.connection_count == 1

        # Disconnecting a different socket should not raise
        await manager.disconnect(ws2)
        assert manager.connection_count == 1

    @pytest.mark.asyncio
    async def test_multiple_connections(self):
        from visema.server.ws_manager import get_manager

        manager = get_manager()
        sockets = [FakeSocket() for _ in range(5)]

        for ws in sockets:
            await manager.connect(ws)

        assert manager.connection_count == 5

        for ws in sockets[:2]:
            await manager.disconnect(ws)

        assert manager.connection_count == 3


# ── Broadcast ─────────────────────────────────────────────────────────────────


class TestBroadcast:
    @pytest.mark.asyncio
    async def test_broadcast_to_single_client(self):
        from visema.server.ws_manager import get_manager

        manager = get_manager()
        ws = FakeSocket()
        await manager.connect(ws)

        payload = {"type": "gif", "url": "http://example.com/test.gif"}
        await manager.broadcast(payload)

        assert len(ws.messages_sent) == 1
        received = json.loads(ws.messages_sent[0])
        assert received == payload

    @pytest.mark.asyncio
    async def test_broadcast_to_multiple_clients(self):
        from visema.server.ws_manager import get_manager

        manager = get_manager()
        sockets = [FakeSocket() for _ in range(3)]
        for ws in sockets:
            await manager.connect(ws)

        payload = {"type": "audio", "src": "/sounds/test.mp3"}
        await manager.broadcast(payload)

        for ws in sockets:
            assert len(ws.messages_sent) == 1
            received = json.loads(ws.messages_sent[0])
            assert received == payload

    @pytest.mark.asyncio
    async def test_broadcast_no_connections(self, caplog):
        from visema.server.ws_manager import get_manager

        manager = get_manager()

        # No connections — should log warning and not crash
        await manager.broadcast({"type": "gif", "url": "http://example.com/x.gif"})

    @pytest.mark.asyncio
    async def test_broadcast_cleans_up_dead_connections(self):
        from visema.server.ws_manager import get_manager

        manager = get_manager()
        ws_alive = FakeSocket()
        await manager.connect(ws_alive)

        # Create a socket that will fail on send
        class DeadSocket(FakeSocket):
            async def send_text(self, text):
                raise ConnectionError("broken pipe")

        ws_dead = DeadSocket()
        await manager.connect(ws_dead)

        assert manager.connection_count == 2

        payload = {"type": "gif", "url": "http://example.com/test.gif"}
        await manager.broadcast(payload)

        # Dead socket should be cleaned up
        assert manager.connection_count == 1
        assert len(ws_alive.messages_sent) == 1


# ── Ack routing ───────────────────────────────────────────────────────────────


class TestHandleClientAck:
    @pytest.mark.asyncio
    async def test_ack_audio_done(self):
        from visema.server.ws_manager import get_manager

        manager = get_manager()
        ws = FakeSocket()

        ack_received = []

        async def mock_callback(ack_type):
            ack_received.append(ack_type)

        from visema.server import ws_manager as wm_module
        wm_module._ack_callback = mock_callback

        data = {"ack": "audio_done"}
        await manager.handle_client_ack(ws, data)

        assert ack_received == ["audio_done"]

    @pytest.mark.asyncio
    async def test_ack_audio_playing(self):
        from visema.server.ws_manager import get_manager

        manager = get_manager()
        ws = FakeSocket()

        ack_received = []

        async def mock_callback(ack_type):
            ack_received.append(ack_type)

        from visema.server import ws_manager as wm_module
        wm_module._ack_callback = mock_callback

        data = {"ack": "audio_playing"}
        await manager.handle_client_ack(ws, data)

        assert ack_received == ["audio_playing"]

    @pytest.mark.asyncio
    async def test_ack_without_callback(self):
        """If no callback is registered, handle silently."""
        from visema.server.ws_manager import get_manager

        manager = get_manager()
        ws = FakeSocket()

        data = {"ack": "audio_done"}
        # _ack_callback is None by default — should not raise
        await manager.handle_client_ack(ws, data)

    @pytest.mark.asyncio
    async def test_ack_without_ack_key(self):
        """Messages without an 'ack' key are ignored."""
        from visema.server.ws_manager import get_manager

        manager = get_manager()
        ws = FakeSocket()

        data = {"type": "gif", "url": "http://example.com/test.gif"}
        await manager.handle_client_ack(ws, data)  # should not raise

    @pytest.mark.asyncio
    async def test_ack_callback_exception_handled(self, caplog):
        from visema.server.ws_manager import get_manager

        manager = get_manager()
        ws = FakeSocket()

        async def failing_callback(ack_type):
            raise RuntimeError("callback broke")

        from visema.server import ws_manager as wm_module
        wm_module._ack_callback = failing_callback

        data = {"ack": "audio_done"}
        # Should not crash the server — exception is caught and logged
        await manager.handle_client_ack(ws, data)


# ── get_manager() / singleton ─────────────────────────────────────────────────


class TestManagerSingleton:
    def test_singleton_pattern(self):
        from visema.server.ws_manager import get_manager

        m1 = get_manager()
        m2 = get_manager()
        assert m1 is m2

    @pytest.mark.asyncio
    async def test_reset_clears_connections(self, monkeypatch):
        """After reset, connections start fresh."""
        from visema.server.ws_manager import WebSocketManager, get_manager

        manager = get_manager()
        ws = FakeSocket()
        await manager.connect(ws)
        assert manager.connection_count == 1

        # Reset to a new instance
        monkeypatch.setattr(
            "visema.server.ws_manager._manager",
            WebSocketManager(),
        )

        fresh = get_manager()
        assert fresh is not manager
        assert fresh.connection_count == 0


# ── Helpers ───────────────────────────────────────────────────────────────────


class FakeSocket:
    """Minimal fake WebSocket for testing."""

    def __init__(self):
        self.messages_sent = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_text(self, text):
        self.messages_sent.append(text)
