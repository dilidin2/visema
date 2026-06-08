"""End-to-end integration tests for Visema's full redemption workflow.

These tests simulate the complete data flow from a Twitch Channel Points
redemption through to overlay broadcast, using mocked Twitch clients and
real queue/ws_manager plumbing.

Flow:
  EventSub event → RedemptionHandler.on_redemption → validator → queue → ws_manager.broadcast
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Full GIF redemption flow ─────────────────────────────────────────────────


class TestGifRedemptionE2E:
    """Simulate a complete GIF redemption from EventSub to broadcast."""

    @pytest.mark.asyncio
    async def test_full_gif_redemption_flow(
        self, mock_broadcaster_client, mock_bot_client, mock_ws_manager
    ):
        """A valid GIF redemption flows through validation → queue → broadcast."""
        from visema.media import validator
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        # ── Setup ───────────────────────────────────────────────
        gif_settings = MagicMock(
            allowed_domains=["i.giphy.com", "media.giphy.com"],
            display_duration_seconds=10,
        )
        audio_settings = MagicMock(volume=1.0)
        cmd_settings = MagicMock()

        queue = MediaQueue(max_size=5, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-abc",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=gif_settings,
            audio_settings=audio_settings,
            command_settings=cmd_settings,
        )
        handler.reward_gif_id = "gif-reward-id"

        # ── Action: Process redemption event ────────────────────
        event = {
            "event": {
                "id": "red-e2e-001",
                "user": {"id": "u-e2e", "login": "e2e_viewer"},
                "channel_points_custom_reward_id": "gif-reward-id",
                "user_input": "https://i.giphy.com/media/e2etest/gif.gif",
            }
        }

        await handler.on_redemption(event)

        # ── Verify: Queue received item ─────────────────────────
        assert queue.size == 1
        queued_item = queue._queue.queue[0]
        assert queued_item["type"] == "gif"
        assert queued_item["url"] == "https://i.giphy.com/media/e2etest/gif.gif"
        assert queued_item["duration"] == 10

        # ── Verify: Redemption fulfilled ────────────────────────
        mock_broadcaster_client.update_channel_points_redemption.assert_called_once_with(
            broadcaster_id="channel-abc",
            redemption_id="red-e2e-001",
            status="FULFILLED",
        )

        # ── Verify: Chat notifications sent ─────────────────────
        chat_calls = mock_bot_client.send_chat_message.call_args_list
        assert len(chat_calls) == 2  # notify + position message

    @pytest.mark.asyncio
    async def test_invalid_gif_redemption_flow(
        self, mock_broadcaster_client, mock_bot_client
    ):
        """An invalid GIF URL triggers cancellation with refund."""
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        gif_settings = MagicMock(
            allowed_domains=["i.giphy.com"],
            display_duration_seconds=8,
        )

        queue = MediaQueue(max_size=5, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-abc",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=gif_settings,
            audio_settings=MagicMock(),
            command_settings=MagicMock(),
        )
        handler.reward_gif_id = "gif-reward-id"

        # ── Action: Invalid URL (bare giphy.com) ────────────────
        event = {
            "event": {
                "id": "red-e2e-002",
                "user": {"id": "u-bad", "login": "bad_viewer"},
                "channel_points_custom_reward_id": "gif-reward-id",
                "user_input": "https://giphy.com/gifs/page-url",
            }
        }

        await handler.on_redemption(event)

        # ── Verify: Not queued ──────────────────────────────────
        assert queue.size == 0

        # ── Verify: Redemption cancelled (points refunded) ──────
        mock_broadcaster_client.update_channel_points_redemption.assert_called_once_with(
            broadcaster_id="channel-abc",
            redemption_id="red-e2e-002",
            status="CANCELED",
        )

        # ── Verify: Error message posted in chat ────────────────
        mock_bot_client.send_chat_message.assert_called()
        error_msg = mock_bot_client.send_chat_message.call_args[0][1]
        assert "Invalid GIF URL" in error_msg


# ── Full Audio redemption flow ────────────────────────────────────────────────


class TestAudioRedemptionE2E:
    """Simulate a complete audio redemption from EventSub to broadcast."""

    @pytest.mark.asyncio
    async def test_full_audio_redemption_flow(
        self, mock_broadcaster_client, mock_bot_client, tmp_sounds_dir
    ):
        """A valid sound redemption flows through validation → queue → broadcast."""
        from visema.media import validator
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        # Build the sounds index in the temp directory
        validator.build_sounds_index(tmp_sounds_dir, [".mp3", ".ogg", ".wav"])

        gif_settings = MagicMock()
        audio_settings = MagicMock(volume=0.8)

        queue = MediaQueue(max_size=5, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-abc",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=gif_settings,
            audio_settings=audio_settings,
            command_settings=MagicMock(),
        )
        handler.reward_sound_id = "sound-reward-id"

        # ── Action: Redemption with spaced sound name ───────────
        event = {
            "event": {
                "id": "red-e2e-003",
                "user": {"id": "u-audio", "login": "audio_fan"},
                "channel_points_custom_reward_id": "sound-reward-id",
                "user_input": "vine boom",  # spaces → underscores
            }
        }

        await handler.on_redemption(event)

        # ── Verify: Queue received item ─────────────────────────
        assert queue.size == 1
        queued_item = queue._queue.queue[0]
        assert queued_item["type"] == "audio"
        assert queued_item["src"] == "/sounds/vine_boom.mp3"
        assert queued_item["volume"] == 0.8

        # ── Verify: Redemption fulfilled ────────────────────────
        mock_broadcaster_client.update_channel_points_redemption.assert_called_once_with(
            broadcaster_id="channel-abc",
            redemption_id="red-e2e-003",
            status="FULFILLED",
        )

    @pytest.mark.asyncio
    async def test_sound_not_found_flow(
        self, mock_broadcaster_client, mock_bot_client, tmp_sounds_dir
    ):
        """A sound not in the library triggers cancellation."""
        from visema.media import validator
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        validator.build_sounds_index(tmp_sounds_dir, [".mp3", ".ogg", ".wav"])

        queue = MediaQueue(max_size=5, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-abc",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=MagicMock(),
            audio_settings=MagicMock(volume=1.0),
            command_settings=MagicMock(),
        )
        handler.reward_sound_id = "sound-reward-id"

        event = {
            "event": {
                "id": "red-e2e-004",
                "user": {"id": "u-lost", "login": "lost_viewer"},
                "channel_points_custom_reward_id": "sound-reward-id",
                "user_input": "ghost_sound_xyz",  # doesn't exist
            }
        }

        await handler.on_redemption(event)

        assert queue.size == 0
        mock_broadcaster_client.update_channel_points_redemption.assert_called_once_with(
            broadcaster_id="channel-abc",
            redemption_id="red-e2e-004",
            status="CANCELED",
        )


# ── Queue worker processing end-to-end ────────────────────────────────────────


class TestQueueWorkerE2E:
    """Test the queue worker processes items and broadcasts correctly."""

    @pytest.mark.asyncio
    async def test_worker_processes_gif_then_audio(
        self, mock_broadcaster_client, mock_bot_client, tmp_sounds_dir
    ):
        """Multiple items are processed in FIFO order by the worker."""
        from visema.media import validator
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        # Build sounds index
        validator.build_sounds_index(tmp_sounds_dir, [".mp3", ".ogg", ".wav"])

        gif_settings = MagicMock(allowed_domains=["i.giphy.com"], display_duration_seconds=8)
        audio_settings = MagicMock(volume=1.0)

        queue = MediaQueue(max_size=5, cooldown_seconds=0.05)  # short cooldown for speed
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-abc",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=gif_settings,
            audio_settings=audio_settings,
            command_settings=MagicMock(),
        )
        handler.reward_gif_id = "gif-reward-id"
        handler.reward_sound_id = "sound-reward-id"

        # ── Enqueue two items via the handler ───────────────────
        event1 = {
            "event": {
                "id": "red-e2e-010",
                "user": {"id": "u1", "login": "viewer1"},
                "channel_points_custom_reward_id": "gif-reward-id",
                "user_input": "https://i.giphy.com/media/first.gif",
            }
        }
        await handler.on_redemption(event1)

        event2 = {
            "event": {
                "id": "red-e2e-011",
                "user": {"id": "u2", "login": "viewer2"},
                "channel_points_custom_reward_id": "sound-reward-id",
                "user_input": "bruh",
            }
        }
        await handler.on_redemption(event2)

        assert queue.size == 2

        # ── Start the worker and let it process ─────────────────
        await queue.start()
        try:
            # Wait for both items to be processed (2 * cooldown + overhead)
            await asyncio.sleep(0.5)
        finally:
            await queue.stop()

        # ── Verify: Both items were broadcast ───────────────────
        broadcasts = mock_ws_manager.broadcast_calls
        assert len(broadcasts) == 2

        # First should be GIF
        assert broadcasts[0]["type"] == "gif"
        assert broadcasts[0]["url"] == "https://i.giphy.com/media/first.gif"

        # Second should be audio
        assert broadcasts[1]["type"] == "audio"
        assert broadcasts[1]["src"] == "/sounds/bruh.mp3"

    @pytest.mark.asyncio
    async def test_worker_queue_full_rejection_e2e(
        self, mock_broadcaster_client, mock_bot_client
    ):
        """Items beyond max_size are rejected and redemptions cancelled."""
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        gif_settings = MagicMock(allowed_domains=["i.giphy.com"], display_duration_seconds=8)

        queue = MediaQueue(max_size=2, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-abc",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=gif_settings,
            audio_settings=MagicMock(),
            command_settings=MagicMock(),
        )
        handler.reward_gif_id = "gif-reward-id"

        # Fill queue to capacity
        for i in range(2):
            event = {
                "event": {
                    "id": f"red-e2e-fill-{i}",
                    "user": {"id": "u-fill", "login": "filler"},
                    "channel_points_custom_reward_id": "gif-reward-id",
                    "user_input": f"https://i.giphy.com/media/fill{i}.gif",
                }
            }
            await handler.on_redemption(event)

        assert queue.size == 2

        # Third item should be rejected
        overflow_event = {
            "event": {
                "id": "red-e2e-overflow",
                "user": {"id": "u-over", "login": "overflow"},
                "channel_points_custom_reward_id": "gif-reward-id",
                "user_input": "https://i.giphy.com/media/overflow.gif",
            }
        }
        await handler.on_redemption(overflow_event)

        assert queue.size == 2  # unchanged
        # The overflow redemption should be CANCELED
        cancel_calls = [
            c for c in mock_broadcaster_client.update_channel_points_redemption.call_args_list
            if c[1]["redemption_id"] == "red-e2e-overflow"
        ]
        assert len(cancel_calls) == 1
        assert cancel_calls[0][1]["status"] == "CANCELED"


# ── Ack handling end-to-end ───────────────────────────────────────────────────


class TestAckHandlingE2E:
    """Test that audio ack from overlay unblocks the queue worker."""

    @pytest.mark.asyncio
    async def test_audio_ack_unblocks_worker(self, mock_ws_manager):
        """When the overlay sends an audio_done ack, the worker proceeds."""
        from visema.media.queue import MediaQueue

        queue = MediaQueue(max_size=5, cooldown_seconds=0.05)

        # Enqueue an audio item
        await queue.enqueue({
            "type": "audio",
            "src": "/sounds/test.mp3",
            "volume": 1.0,
        })

        broadcast_received = []

        async def mock_broadcast(item):
            broadcast_received.append(item)

        queue._broadcast = mock_broadcast

        # Start worker — it will block on _wait_for_audio_done
        await queue.start()

        try:
            # Wait for the item to be dequeued and broadcast
            await asyncio.sleep(0.2)

            # Now simulate the overlay sending an ack
            from visema.server import ws_manager as wm_module
            if wm_module._ack_callback:
                await wm_module._ack_callback("audio_done")

            # Give the worker time to process the ack and cooldown
            await asyncio.sleep(0.3)
        finally:
            await queue.stop()

        assert len(broadcast_received) == 1
        assert broadcast_received[0]["type"] == "audio"


# ── Mixed GIF + Audio flow ───────────────────────────────────────────────────


class TestMixedRedemptionE2E:
    """Test interleaved GIF and audio redemptions."""

    @pytest.mark.asyncio
    async def test_interleaved_redemptions(
        self, mock_broadcaster_client, mock_bot_client, tmp_sounds_dir
    ):
        """GIF and audio redemptions mix correctly in the queue."""
        from visema.media import validator
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        validator.build_sounds_index(tmp_sounds_dir, [".mp3", ".ogg", ".wav"])

        gif_settings = MagicMock(allowed_domains=["i.giphy.com"], display_duration_seconds=8)
        audio_settings = MagicMock(volume=1.0)

        queue = MediaQueue(max_size=10, cooldown_seconds=0.05)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-abc",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=gif_settings,
            audio_settings=audio_settings,
            command_settings=MagicMock(),
        )
        handler.reward_gif_id = "gif-reward-id"
        handler.reward_sound_id = "sound-reward-id"

        # Enqueue: GIF → Audio → GIF → Audio
        redemptions = [
            {
                "event": {
                    "id": "mix-001",
                    "user": {"id": "u1", "login": "a"},
                    "channel_points_custom_reward_id": "gif-reward-id",
                    "user_input": "https://i.giphy.com/media/a.gif",
                }
            },
            {
                "event": {
                    "id": "mix-002",
                    "user": {"id": "u2", "login": "b"},
                    "channel_points_custom_reward_id": "sound-reward-id",
                    "user_input": "vine_boom",
                }
            },
            {
                "event": {
                    "id": "mix-003",
                    "user": {"id": "u3", "login": "c"},
                    "channel_points_custom_reward_id": "gif-reward-id",
                    "user_input": "https://media.giphy.com/media/b.gif",
                }
            },
            {
                "event": {
                    "id": "mix-004",
                    "user": {"id": "u4", "login": "d"},
                    "channel_points_custom_reward_id": "sound-reward-id",
                    "user_input": "airhorn",
                }
            },
        ]

        for event in redemptions:
            await handler.on_redemption(event)

        assert queue.size == 4

        # Start worker and let it process all items
        await queue.start()
        try:
            await asyncio.sleep(0.5)
        finally:
            await queue.stop()

        broadcasts = mock_ws_manager.broadcast_calls
        assert len(broadcasts) == 4

        # Verify FIFO order
        assert broadcasts[0]["type"] == "gif"
        assert broadcasts[1]["type"] == "audio"
        assert broadcasts[2]["type"] == "gif"
        assert broadcasts[3]["type"] == "audio"


# ── Config-driven behavior ────────────────────────────────────────────────────


class TestConfigDrivenE2E:
    """Verify that config values flow through the entire pipeline."""

    @pytest.mark.asyncio
    async def test_gif_duration_from_config(
        self, mock_broadcaster_client, mock_bot_client
    ):
        """The GIF display duration comes from gif_settings, not hardcoded."""
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        long_duration = 20
        gif_settings = MagicMock(
            allowed_domains=["i.giphy.com"],
            display_duration_seconds=long_duration,
        )

        queue = MediaQueue(max_size=5, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-abc",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=gif_settings,
            audio_settings=MagicMock(),
            command_settings=MagicMock(),
        )
        handler.reward_gif_id = "gif-reward-id"

        event = {
            "event": {
                "id": "red-config-001",
                "user": {"id": "u1", "login": "config_tester"},
                "channel_points_custom_reward_id": "gif-reward-id",
                "user_input": "https://i.giphy.com/media/config.gif",
            }
        }

        await handler.on_redemption(event)

        queued_item = queue._queue.queue[0]
        assert queued_item["duration"] == long_duration


# ── Cross-module integration helpers ──────────────────────────────────────────


class FakeSocket:
    """Minimal fake WebSocket for e2e tests."""

    def __init__(self):
        self.messages_sent = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_text(self, text):
        self.messages_sent.append(text)


class MockWebSocketManager:
    """Minimal mock that replaces the singleton for e2e tests."""

    def __init__(self):
        self.broadcast_calls = []
        self.connections = set()

    async def broadcast(self, payload):
        self.broadcast_calls.append(payload)

    @property
    def connection_count(self):
        return len(self.connections)


# Re-import conftest fixtures that we need here
@pytest.fixture(autouse=True)
def _reset_ws_manager_e2e(monkeypatch):
    """Ensure ws_manager is reset before each e2e test."""
    from visema.server import ws_manager as wm_module
    original = wm_module._manager
    wm_module._manager = MockWebSocketManager()
    wm_module._ack_callback = None
    yield
    wm_module._manager = original
    wm_module._ack_callback = None


@pytest.fixture(autouse=True)
def _reset_validator_e2e():
    """Reset validator state before each e2e test."""
    from visema.media import validator
    validator._sounds_index = {}
    yield
    validator._sounds_index = {}
