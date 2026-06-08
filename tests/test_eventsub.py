"""Tests for visema.twitch.eventsub — RedemptionHandler."""

import pytest


# ── RedemptionHandler initialization ──────────────────────────────────────────


class TestRedemptionHandlerInit:
    def test_handler_stores_clients(self, mock_broadcaster_client, mock_bot_client):
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        queue = MediaQueue(max_size=3, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-123",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=MagicMock(allowed_domains=["i.giphy.com"], display_duration_seconds=8),
            audio_settings=MagicMock(volume=1.0),
            command_settings=MagicMock(),
        )

        assert handler.broadcaster_client is mock_broadcaster_client
        assert handler.bot_client is mock_bot_client
        assert handler.target_channel_id == "channel-123"
        assert handler.reward_gif_name == "Show a GIF"
        assert handler.reward_sound_name == "Play a Sound"

    def test_reward_ids_start_empty(self, mock_broadcaster_client, mock_bot_client):
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        queue = MediaQueue(max_size=3, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-123",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=MagicMock(allowed_domains=["i.giphy.com"], display_duration_seconds=8),
            audio_settings=MagicMock(volume=1.0),
            command_settings=MagicMock(),
        )

        assert handler.reward_gif_id is None
        assert handler.reward_sound_id is None


# ── resolve_reward_ids ───────────────────────────────────────────────────────


class TestResolveRewardIds:
    @pytest.mark.asyncio
    async def test_resolves_both_rewards(self, mock_broadcaster_client):
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        queue = MediaQueue(max_size=3, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=MagicMock(),
            queue=queue,
            target_channel_id="channel-123",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=MagicMock(),
            audio_settings=MagicMock(),
            command_settings=MagicMock(),
        )

        await handler.resolve_reward_ids()

        assert handler.reward_gif_id == "gif-reward-id"
        assert handler.reward_sound_id == "sound-reward-id"

    @pytest.mark.asyncio
    async def test_missing_reward_logs_warning(self, mock_broadcaster_client):
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        # Mock returns only one reward
        mock_broadcaster_client.get_channel_points_rewards = AsyncMock(return_value={
            "data": [
                {"id": "gif-reward-id", "title": "Show a GIF"},
            ]
        })

        queue = MediaQueue(max_size=3, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=MagicMock(),
            queue=queue,
            target_channel_id="channel-123",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=MagicMock(),
            audio_settings=MagicMock(),
            command_settings=MagicMock(),
        )

        await handler.resolve_reward_ids()

        assert handler.reward_gif_id == "gif-reward-id"
        assert handler.reward_sound_id is None

    @pytest.mark.asyncio
    async def test_no_rewards_found(self, mock_broadcaster_client):
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        mock_broadcaster_client.get_channel_points_rewards = AsyncMock(return_value={
            "data": []
        })

        queue = MediaQueue(max_size=3, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=MagicMock(),
            queue=queue,
            target_channel_id="channel-123",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=MagicMock(),
            audio_settings=MagicMock(),
            command_settings=MagicMock(),
        )

        await handler.resolve_reward_ids()

        assert handler.reward_gif_id is None
        assert handler.reward_sound_id is None

    @pytest.mark.asyncio
    async def test_api_error_handled(self, mock_broadcaster_client):
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        mock_broadcaster_client.get_channel_points_rewards = AsyncMock(
            side_effect=Exception("API down")
        )

        queue = MediaQueue(max_size=3, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=MagicMock(),
            queue=queue,
            target_channel_id="channel-123",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=MagicMock(),
            audio_settings=MagicMock(),
            command_settings=MagicMock(),
        )

        # Should not raise — error is logged internally
        await handler.resolve_reward_ids()

        assert handler.reward_gif_id is None


# ── _handle_gif ───────────────────────────────────────────────────────────────


class TestHandleGif:
    @pytest.mark.asyncio
    async def test_valid_gif_enqueued(self, mock_broadcaster_client, mock_bot_client, mock_ws_manager):
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        queue = MediaQueue(max_size=5, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-123",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=MagicMock(
                allowed_domains=["i.giphy.com"],
                display_duration_seconds=8,
            ),
            audio_settings=MagicMock(),
            command_settings=MagicMock(),
        )
        handler.reward_gif_id = "gif-reward-id"

        await handler._handle_gif(
            redemption_id="red-001",
            user_login="viewer_one",
            url="https://i.giphy.com/media/abc123/giphy.gif",
        )

        assert queue.size == 1
        mock_broadcaster_client.update_channel_points_redemption.assert_called_once_with(
            broadcaster_id="channel-123",
            redemption_id="red-001",
            status="FULFILLED",
        )
        # Chat messages sent (notify + position)
        assert mock_bot_client.send_chat_message.call_count == 2

    @pytest.mark.asyncio
    async def test_invalid_gif_cancelled(self, mock_broadcaster_client, mock_bot_client):
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        queue = MediaQueue(max_size=5, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-123",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=MagicMock(
                allowed_domains=["i.giphy.com"],
                display_duration_seconds=8,
            ),
            audio_settings=MagicMock(),
            command_settings=MagicMock(),
        )
        handler.reward_gif_id = "gif-reward-id"

        await handler._handle_gif(
            redemption_id="red-002",
            user_login="viewer_bad",
            url="https://giphy.com/gifs/not-direct-link",
        )

        assert queue.size == 0
        mock_broadcaster_client.update_channel_points_redemption.assert_called_once_with(
            broadcaster_id="channel-123",
            redemption_id="red-002",
            status="CANCELED",
        )
        # Chat message with reason
        mock_bot_client.send_chat_message.assert_called()

    @pytest.mark.asyncio
    async def test_queue_full_gif_cancelled(self, mock_broadcaster_client, mock_bot_client):
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        queue = MediaQueue(max_size=1, cooldown_seconds=0.1)
        # Fill the queue
        await queue.enqueue({"type": "gif", "url": "http://example.com/1.gif"})

        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-123",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=MagicMock(allowed_domains=["i.giphy.com"], display_duration_seconds=8),
            audio_settings=MagicMock(),
            command_settings=MagicMock(),
        )
        handler.reward_gif_id = "gif-reward-id"

        await handler._handle_gif(
            redemption_id="red-003",
            user_login="viewer_spam",
            url="https://i.giphy.com/media/another.gif",
        )

        assert queue.size == 1  # unchanged
        mock_broadcaster_client.update_channel_points_redemption.assert_called_once_with(
            broadcaster_id="channel-123",
            redemption_id="red-003",
            status="CANCELED",
        )


# ── _handle_audio ─────────────────────────────────────────────────────────────


class TestHandleAudio:
    @pytest.mark.asyncio
    async def test_valid_sound_enqueued(self, mock_broadcaster_client, mock_bot_client, tmp_sounds_dir):
        from visema.media import validator
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        # Build sounds index in the temp directory
        validator.build_sounds_index(tmp_sounds_dir, [".mp3", ".ogg", ".wav"])

        queue = MediaQueue(max_size=5, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-123",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=MagicMock(),
            audio_settings=MagicMock(volume=1.0),
            command_settings=MagicMock(),
        )
        handler.reward_sound_id = "sound-reward-id"

        await handler._handle_audio(
            redemption_id="red-004",
            user_login="viewer_audio",
            name="vine boom",
        )

        assert queue.size == 1
        item = queue._queue.queue[0]
        assert item["type"] == "audio"
        assert item["src"] == "/sounds/vine_boom.mp3"
        assert item["volume"] == 1.0
        mock_broadcaster_client.update_channel_points_redemption.assert_called_once_with(
            broadcaster_id="channel-123",
            redemption_id="red-004",
            status="FULFILLED",
        )

    @pytest.mark.asyncio
    async def test_sound_not_found_cancelled(self, mock_broadcaster_client, mock_bot_client, tmp_sounds_dir):
        from visema.media import validator
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        validator.build_sounds_index(tmp_sounds_dir, [".mp3", ".ogg", ".wav"])

        queue = MediaQueue(max_size=5, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-123",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=MagicMock(),
            audio_settings=MagicMock(volume=1.0),
            command_settings=MagicMock(),
        )
        handler.reward_sound_id = "sound-reward-id"

        await handler._handle_audio(
            redemption_id="red-005",
            user_login="viewer_confused",
            name="nonexistent_sound_xyz",
        )

        assert queue.size == 0
        mock_broadcaster_client.update_channel_points_redemption.assert_called_once_with(
            broadcaster_id="channel-123",
            redemption_id="red-005",
            status="CANCELED",
        )

    @pytest.mark.asyncio
    async def test_audio_queue_full_cancelled(self, mock_broadcaster_client, mock_bot_client, tmp_sounds_dir):
        from visema.media import validator
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        validator.build_sounds_index(tmp_sounds_dir, [".mp3", ".ogg", ".wav"])

        queue = MediaQueue(max_size=1, cooldown_seconds=0.1)
        await queue.enqueue({"type": "audio", "src": "/sounds/other.mp3"})

        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-123",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=MagicMock(),
            audio_settings=MagicMock(volume=1.0),
            command_settings=MagicMock(),
        )
        handler.reward_sound_id = "sound-reward-id"

        await handler._handle_audio(
            redemption_id="red-006",
            user_login="viewer_late",
            name="vine_boom",
        )

        assert queue.size == 1  # unchanged
        mock_broadcaster_client.update_channel_points_redemption.assert_called_once_with(
            broadcaster_id="channel-123",
            redemption_id="red-006",
            status="CANCELED",
        )


# ── on_redemption (dispatch) ─────────────────────────────────────────────────


class TestOnRedemption:
    @pytest.mark.asyncio
    async def test_dispatches_gif(self, mock_broadcaster_client, mock_bot_client):
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        queue = MediaQueue(max_size=5, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-123",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=MagicMock(allowed_domains=["i.giphy.com"], display_duration_seconds=8),
            audio_settings=MagicMock(),
            command_settings=MagicMock(),
        )
        handler.reward_gif_id = "gif-reward-id"

        event = {
            "event": {
                "id": "red-100",
                "user": {"id": "u1", "login": "test_user"},
                "channel_points_custom_reward_id": "gif-reward-id",
                "user_input": "https://i.giphy.com/media/test.gif",
            }
        }

        await handler.on_redemption(event)
        assert queue.size == 1

    @pytest.mark.asyncio
    async def test_dispatches_audio(self, mock_broadcaster_client, mock_bot_client, tmp_sounds_dir):
        from visema.media import validator
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        validator.build_sounds_index(tmp_sounds_dir, [".mp3", ".ogg", ".wav"])

        queue = MediaQueue(max_size=5, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-123",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=MagicMock(),
            audio_settings=MagicMock(volume=1.0),
            command_settings=MagicMock(),
        )
        handler.reward_sound_id = "sound-reward-id"

        event = {
            "event": {
                "id": "red-101",
                "user": {"id": "u2", "login": "audio_user"},
                "channel_points_custom_reward_id": "sound-reward-id",
                "user_input": "bruh",
            }
        }

        await handler.on_redemption(event)
        assert queue.size == 1

    @pytest.mark.asyncio
    async def test_unknown_reward_logged(self, mock_broadcaster_client, mock_bot_client):
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        queue = MediaQueue(max_size=5, cooldown_seconds=0.1)
        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=queue,
            target_channel_id="channel-123",
            reward_gif_name="Show a GIF",
            reward_sound_name="Play a Sound",
            gif_settings=MagicMock(),
            audio_settings=MagicMock(),
            command_settings=MagicMock(),
        )

        event = {
            "event": {
                "id": "red-102",
                "user": {"id": "u3", "login": "stranger"},
                "channel_points_custom_reward_id": "totally_unknown",
                "user_input": "",
            }
        }

        await handler.on_redemption(event)
        # Should not raise, just log a warning
        assert queue.size == 0


# ── Fulfill / Cancel helpers ──────────────────────────────────────────────────


class TestFulfillCancelHelpers:
    @pytest.mark.asyncio
    async def test_fulfill_calls_api(self, mock_broadcaster_client):
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=MagicMock(),
            queue=MediaQueue(max_size=1),
            target_channel_id="channel-123",
            reward_gif_name="",
            reward_sound_name="",
            gif_settings=MagicMock(),
            audio_settings=MagicMock(),
            command_settings=MagicMock(),
        )

        await handler._fulfill_redemption("red-999")

        mock_broadcaster_client.update_channel_points_redemption.assert_called_once_with(
            broadcaster_id="channel-123",
            redemption_id="red-999",
            status="FULFILLED",
        )

    @pytest.mark.asyncio
    async def test_cancel_calls_api_and_chat(self, mock_broadcaster_client, mock_bot_client):
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=MediaQueue(max_size=1),
            target_channel_id="channel-123",
            reward_gif_name="",
            reward_sound_name="",
            gif_settings=MagicMock(),
            audio_settings=MagicMock(),
            command_settings=MagicMock(),
        )

        await handler._cancel_redemption("red-888", "spammer", "You're banned!")

        mock_broadcaster_client.update_channel_points_redemption.assert_called_once_with(
            broadcaster_id="channel-123",
            redemption_id="red-888",
            status="CANCELED",
        )
        # Two chat calls: reason + no ping (cancel sends reason directly)
        assert mock_bot_client.send_chat_message.call_count == 1

    @pytest.mark.asyncio
    async def test_cancel_api_error_logged(self, mock_broadcaster_client, mock_bot_client):
        from visema.media.queue import MediaQueue
        from visema.twitch.eventsub import RedemptionHandler

        mock_broadcaster_client.update_channel_points_redemption = AsyncMock(
            side_effect=Exception("API error")
        )

        handler = RedemptionHandler(
            broadcaster_client=mock_broadcaster_client,
            bot_client=mock_bot_client,
            queue=MediaQueue(max_size=1),
            target_channel_id="channel-123",
            reward_gif_name="",
            reward_sound_name="",
            gif_settings=MagicMock(),
            audio_settings=MagicMock(),
            command_settings=MagicMock(),
        )

        # Should not raise — error is caught and logged
        await handler._cancel_redemption("red-777", "user", "reason")


# ── Helper ────────────────────────────────────────────────────────────────────


def monkeypatch_env_path(env_path, auth_module):
    """Patch the _ENV_PATH on the auth module."""
    auth_module._ENV_PATH = env_path
