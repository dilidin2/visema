"""Tests for visema.media.queue."""

import asyncio
import pytest

from visema.media.queue import MediaQueue


class TestMediaQueue:
    @pytest.fixture
    def queue(self):
        return MediaQueue(max_size=3, cooldown_seconds=0.1)

    def test_initial_state(self, queue):
        assert queue.size == 0
        assert not queue.is_full

    @pytest.mark.asyncio
    async def test_enqueue_single_item(self, queue):
        result = await queue.enqueue({"type": "gif", "url": "http://example.com/test.gif"})
        assert result is True
        assert queue.size == 1

    @pytest.mark.asyncio
    async def test_enqueue_multiple_items(self, queue):
        await queue.enqueue({"type": "gif", "url": "http://example.com/1.gif"})
        await queue.enqueue({"type": "audio", "src": "/sounds/test.mp3"})
        await queue.enqueue({"type": "gif", "url": "http://example.com/2.gif"})
        assert queue.size == 3
        assert queue.is_full

    @pytest.mark.asyncio
    async def test_queue_full_rejection(self, queue):
        await queue.enqueue({"type": "gif", "url": "http://example.com/1.gif"})
        await queue.enqueue({"type": "gif", "url": "http://example.com/2.gif"})
        await queue.enqueue({"type": "gif", "url": "http://example.com/3.gif"})

        # This should fail — queue is full
        result = await queue.enqueue({"type": "gif", "url": "http://example.com/4.gif"})
        assert result is False
        assert queue.size == 3

    @pytest.mark.asyncio
    async def test_clear_queue(self, queue):
        await queue.enqueue({"type": "gif", "url": "http://example.com/1.gif"})
        await queue.enqueue({"type": "audio", "src": "/sounds/test.mp3"})
        assert queue.size == 2

        cleared = await queue.clear()
        assert cleared == 2
        assert queue.size == 0
        assert not queue.is_full

    @pytest.mark.asyncio
    async def test_clear_empty_queue(self, queue):
        cleared = await queue.clear()
        assert cleared == 0

    @pytest.mark.asyncio
    async def test_start_and_stop(self, queue):
        await queue.start()
        assert queue._running is True
        await asyncio.sleep(0.05)  # Let worker tick
        await queue.stop()
        assert queue._running is False

    @pytest.mark.asyncio
    async def test_worker_processes_items(self, queue):
        """Test that the worker dequeues and processes items."""
        processed = []

        async def mock_broadcast(item):
            processed.append(item)

        queue._broadcast = mock_broadcast

        await queue.enqueue({"type": "gif", "url": "http://example.com/test.gif", "duration": 1})
        await queue.start()

        # Wait for worker to process
        await asyncio.sleep(0.5)

        await queue.stop()

        assert len(processed) == 1
        assert processed[0]["type"] == "gif"
