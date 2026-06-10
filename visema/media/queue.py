"""
Unified FIFO queue for GIF + audio events with cooldown.

The queue worker dequeues items, broadcasts them via WebSocket,
and waits for completion (audio ack or timeout) before starting cooldown.
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from visema.server.ws_manager import get_manager, set_ack_callback

logger = logging.getLogger(__name__)

# Callback type: async function that receives a payload dict
BroadcastFn = Callable[[Dict[str, Any]], Awaitable[None]]


class MediaQueue:
    """Async FIFO queue for media events (GIF + audio)."""

    def __init__(
        self,
        max_size: int = 5,
        cooldown_seconds: float = 3.0,
        broadcast: Optional[BroadcastFn] = None,
    ):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self._cooldown = cooldown_seconds
        self._broadcast = broadcast or self._default_broadcast
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        # Pre-created events; cleared before broadcast so acks arriving early are never lost
        self._audio_done_event: asyncio.Event = asyncio.Event()
        self._gif_done_event: asyncio.Event = asyncio.Event()

        # Register ack callback so overlay can signal completion
        set_ack_callback(self._on_ack)

    @staticmethod
    def _default_broadcast(payload: dict) -> None:
        """Default broadcast using the WebSocket manager."""
        manager = get_manager()
        return asyncio.create_task(manager.broadcast(payload))

    async def _on_ack(self, ack_type: str) -> None:
        """Handle ack messages from the overlay."""
        if ack_type == "audio_done":
            self._audio_done_event.set()
        elif ack_type == "gif_done":
            self._gif_done_event.set()
        elif ack_type == "audio_playing":
            pass  # informational only, no action needed

    async def enqueue(self, item: dict) -> bool:
        """Add an item to the queue. Returns True if successful, False if full."""
        try:
            self._queue.put_nowait(item)
            logger.info(
                "Enqueued %s (queue: %d/%d)",
                item.get("type"),
                self._queue.qsize(),
                self._queue.maxsize,
            )
            return True
        except asyncio.QueueFull:
            logger.warning("Queue full, rejecting %s", item.get("type"))
            return False

    @property
    def is_full(self) -> bool:
        return self._queue.full()

    @property
    def size(self) -> int:
        return self._queue.qsize()

    async def start(self) -> None:
        """Start the queue worker coroutine."""
        if self._running:
            logger.warning("Queue worker already running")
            return

        self._running = True
        self._worker_task = asyncio.create_task(self._worker(), name="media-queue-worker")
        logger.info("Queue worker started (max_size=%d, cooldown=%ss)", self._queue.maxsize, self._cooldown)

    async def stop(self) -> None:
        """Stop the queue worker."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        logger.info("Queue worker stopped")

    async def _worker(self) -> None:
        """Main worker loop: dequeue → broadcast → wait for completion → cooldown."""
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            item_type = item.get("type", "unknown")
            logger.info("Processing %s: %s", item_type, item)

            # Arm the completion event BEFORE broadcasting so any ack that
            # arrives before we enter the wait is not lost.
            if item_type == "audio":
                self._audio_done_event.clear()
            elif item_type == "gif":
                self._gif_done_event.clear()

            # Broadcast to overlay
            try:
                await self._broadcast(item)
            except Exception:
                logger.exception("Failed to broadcast %s", item_type)

            # Wait for completion
            if item_type == "audio":
                await self._wait_for_audio_done()
            elif item_type == "gif":
                await self._wait_for_gif_done(
                    timeout=item.get("duration", 8) + 1.0
                )

            # Cooldown before next item
            if self._cooldown > 0:
                logger.debug("Cooldown %.1fs before next item", self._cooldown)
                await asyncio.sleep(self._cooldown)

    async def _wait_for_audio_done(self, timeout: float = 30.0) -> None:
        """Wait for the overlay to signal audio playback completion."""
        try:
            await asyncio.wait_for(self._audio_done_event.wait(), timeout=timeout)
            logger.debug("Audio completion received from overlay")
        except asyncio.TimeoutError:
            logger.warning("Audio completion timeout (%.0fs), continuing", timeout)

    async def _wait_for_gif_done(self, timeout: float = 9.0) -> None:
        """Wait for the overlay to signal GIF removal completion."""
        try:
            await asyncio.wait_for(self._gif_done_event.wait(), timeout=timeout)
            logger.debug("GIF completion received from overlay")
        except asyncio.TimeoutError:
            logger.warning("GIF completion timeout (%.0fs), continuing", timeout)

    async def clear(self) -> int:
        """Clear all pending items from the queue. Returns number of items cleared."""
        count = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                count += 1
            except asyncio.QueueEmpty:
                break
        if count:
            logger.info("Cleared %d items from queue", count)
        return count
