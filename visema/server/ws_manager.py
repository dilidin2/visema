"""
Tracks active WebSocket connections (OBS browser sources) and broadcasts messages.
"""

import asyncio
import json
import logging
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections from OBS Browser Sources."""

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info("WebSocket connected (total: %d)", self.connection_count)

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            self._connections.discard(websocket)
        logger.info("WebSocket disconnected (total: %d)", self.connection_count)

    async def broadcast(self, payload: dict) -> None:
        """Send a JSON message to all connected clients.

        Dead connections are cleaned up automatically.
        """
        if not self._connections:
            logger.warning("No WebSocket clients connected, dropping message: %s", payload.get("type"))
            return

        message = json.dumps(payload)
        dead = set()

        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)

        # Clean up dead connections
        if dead:
            async with self._lock:
                self._connections -= dead
            logger.info("Cleaned up %d dead WebSocket connections", len(dead))

    async def handle_client_ack(self, websocket: WebSocket, data: dict) -> None:
        """Handle acknowledgment messages from the overlay.

        Currently handles 'audio_playing' and 'audio_done' acks.
        These are forwarded to the queue worker via the ack callback.
        """
        ack_type = data.get("ack")
        if ack_type:
            logger.debug("Received ack from overlay: %s", ack_type)
            # The queue worker listens for these via on_ack callback
            if _ack_callback:
                try:
                    await _ack_callback(ack_type)
                except Exception:
                    logger.exception("Error in ack callback")


# Module-level ack callback — set by queue.py
_ack_callback = None


def set_ack_callback(callback):
    """Set the callback for overlay ack messages (called by queue.py)."""
    global _ack_callback
    _ack_callback = callback


def get_manager() -> "WebSocketManager":
    """Return the singleton WebSocketManager instance."""
    return _manager


# Singleton
_manager = WebSocketManager()
