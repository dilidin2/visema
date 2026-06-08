"""Tests for visema.twitch.chat — ChatCommandHandler."""

import pytest

from visema.twitch.chat import ChatCommandHandler


# ── Handler initialization ────────────────────────────────────────────────────


class TestChatCommandHandlerInit:
    def test_stores_config(self, mock_bot_client):
        from dataclasses import dataclass

        @dataclass
        class CmdSettings:
            gif_response: str = "GIF help"
            sound_response: str = "Sound help"
            soundlist_response: str = "auto"

        handler = ChatCommandHandler(
            bot_client=mock_bot_client,
            target_channel_name="testchannel",
            target_channel_id="channel-123",
            bot_user_id="bot-user-456",
            command_settings=CmdSettings(),
        )

        assert handler.target_channel_name == "testchannel"
        assert handler.target_channel_id == "channel-123"
        assert handler.bot_user_id == "bot-user-456"
        assert handler.commands.gif_response == "GIF help"


# ── !gif command ──────────────────────────────────────────────────────────────


class TestGifCommand:
    @pytest.mark.asyncio
    async def test_gif_command_sends_help(self, mock_bot_client):
        from dataclasses import dataclass
        from unittest.mock import MagicMock

        @dataclass
        class CmdSettings:
            gif_response: str = "🎬 Use a Giphy direct link!"
            sound_response: str = ""
            soundlist_response: str = "auto"

        handler = ChatCommandHandler(
            bot_client=mock_bot_client,
            target_channel_name="testchannel",
            target_channel_id="channel-123",
            bot_user_id="bot-user-456",
            command_settings=CmdSettings(),
        )

        fake_cmd = MagicMock()
        fake_cmd.user.name = "viewer_one"

        await handler.on_gif(fake_cmd)

        mock_bot_client.send_chat_message.assert_called_once_with(
            "channel-123",
            "bot-user-456",
            "@viewer_one: 🎬 Use a Giphy direct link!",
        )

    @pytest.mark.asyncio
    async def test_gif_command_case_insensitive(self, mock_bot_client):
        from dataclasses import dataclass
        from unittest.mock import MagicMock

        @dataclass
        class CmdSettings:
            gif_response: str = "GIF help"
            sound_response: str = ""
            soundlist_response: str = "auto"

        handler = ChatCommandHandler(
            bot_client=mock_bot_client,
            target_channel_name="testchannel",
            target_channel_id="channel-123",
            bot_user_id="bot-user-456",
            command_settings=CmdSettings(),
        )

        fake_cmd = MagicMock()
        fake_cmd.user.name = "viewer_two"

        await handler.on_gif(fake_cmd)

        assert mock_bot_client.send_chat_message.call_count == 1


# ── !sound command ────────────────────────────────────────────────────────────


class TestSoundCommand:
    @pytest.mark.asyncio
    async def test_sound_command_sends_help(self, mock_bot_client):
        from dataclasses import dataclass
        from unittest.mock import MagicMock

        @dataclass
        class CmdSettings:
            gif_response: str = ""
            sound_response: str = "🔊 Type a sound name!"
            soundlist_response: str = "auto"

        handler = ChatCommandHandler(
            bot_client=mock_bot_client,
            target_channel_name="testchannel",
            target_channel_id="channel-123",
            bot_user_id="bot-user-456",
            command_settings=CmdSettings(),
        )

        fake_cmd = MagicMock()
        fake_cmd.user.name = "viewer_three"

        await handler.on_sound(fake_cmd)

        mock_bot_client.send_chat_message.assert_called_once_with(
            "channel-123",
            "bot-user-456",
            "@viewer_three: 🔊 Type a sound name!",
        )


# ── !soundlist command ────────────────────────────────────────────────────────


class TestSoundlistCommand:
    @pytest.mark.asyncio
    async def test_soundlist_with_sounds(self, mock_bot_client, tmp_sounds_dir):
        from dataclasses import dataclass
        from unittest.mock import MagicMock

        from visema.media import validator

        # Build the sounds index
        validator.build_sounds_index(tmp_sounds_dir, [".mp3", ".ogg", ".wav"])

        @dataclass
        class CmdSettings:
            gif_response: str = ""
            sound_response: str = ""
            soundlist_response: str = "auto"

        handler = ChatCommandHandler(
            bot_client=mock_bot_client,
            target_channel_name="testchannel",
            target_channel_id="channel-123",
            bot_user_id="bot-user-456",
            command_settings=CmdSettings(),
        )

        fake_cmd = MagicMock()
        fake_cmd.user.name = "curious_viewer"

        await handler.on_soundlist(fake_cmd)

        call_args = mock_bot_client.send_chat_message.call_args[0]
        assert call_args[0] == "channel-123"
        assert call_args[1] == "bot-user-456"
        response = call_args[2]
        assert "@curious_viewer:" in response
        assert "vine_boom" in response
        assert "bruh" in response
        assert "airhorn" in response

    @pytest.mark.asyncio
    async def test_soundlist_no_sounds(self, mock_bot_client):
        """When no sounds exist, bot replies with a friendly message."""
        from dataclasses import dataclass
        from unittest.mock import MagicMock

        # Ensure index is empty (conftest resets it)
        from visema.media import validator
        assert len(validator.get_sound_names()) == 0

        @dataclass
        class CmdSettings:
            gif_response: str = ""
            sound_response: str = ""
            soundlist_response: str = "auto"

        handler = ChatCommandHandler(
            bot_client=mock_bot_client,
            target_channel_name="testchannel",
            target_channel_id="channel-123",
            bot_user_id="bot-user-456",
            command_settings=CmdSettings(),
        )

        fake_cmd = MagicMock()
        fake_cmd.user.name = "empty_lot"

        await handler.on_soundlist(fake_cmd)

        call_args = mock_bot_client.send_chat_message.call_args[0]
        assert "No audio files" in call_args[2]

    @pytest.mark.asyncio
    async def test_soundlist_predefined_response(self, mock_bot_client):
        """When soundlist_response is not 'auto', use the predefined string."""
        from dataclasses import dataclass
        from unittest.mock import MagicMock

        @dataclass
        class CmdSettings:
            gif_response: str = ""
            sound_response: str = ""
            soundlist_response: str = "Predefined list here"

        handler = ChatCommandHandler(
            bot_client=mock_bot_client,
            target_channel_name="testchannel",
            target_channel_id="channel-123",
            bot_user_id="bot-user-456",
            command_settings=CmdSettings(),
        )

        fake_cmd = MagicMock()
        fake_cmd.user.name = "test_user"

        await handler.on_soundlist(fake_cmd)

        call_args = mock_bot_client.send_chat_message.call_args[0]
        assert call_args[2] == "@test_user: Predefined list here"


# ── Chat message formatting ───────────────────────────────────────────────────


class TestMessageFormatting:
    @pytest.mark.asyncio
    async def test_response_includes_sender_ping(self, mock_bot_client):
        from dataclasses import dataclass
        from unittest.mock import MagicMock

        @dataclass
        class CmdSettings:
            gif_response: str = "Help text"
            sound_response: str = ""
            soundlist_response: str = "auto"

        handler = ChatCommandHandler(
            bot_client=mock_bot_client,
            target_channel_name="testchannel",
            target_channel_id="channel-123",
            bot_user_id="bot-user-456",
            command_settings=CmdSettings(),
        )

        fake_cmd = MagicMock()
        fake_cmd.user.name = "pinger"

        await handler.on_gif(fake_cmd)

        call_args = mock_bot_client.send_chat_message.call_args[0]
        assert call_args[2].startswith("@pinger:")
