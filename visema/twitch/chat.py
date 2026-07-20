"""
Chat command listener for !gif, !sound, and !soundlist.

Uses the same Twitch client for chat (single-account design).
All commands are read-only — they do not trigger overlay or queue actions.
"""

import asyncio
import logging

from twitchAPI.chat import Chat, ChatCommand
from twitchAPI.twitch import Twitch

from visema.media import validator

logger = logging.getLogger(__name__)


class ChatCommandHandler:
    """Handles chat commands received on the broadcaster's channel."""

    def __init__(
        self,
        twitch_client: Twitch,
        target_channel_name: str,
        target_channel_id: str,
        bot_user_id: str,
        command_settings,
    ):
        self.twitch_client = twitch_client
        self.target_channel_name = target_channel_name
        self.target_channel_id = target_channel_id
        self.bot_user_id = bot_user_id
        self.commands = command_settings

    async def _respond(self, sender: str, response: str) -> None:
        """Send a response to chat, pinging the sender."""
        message = f"@{sender}: {response.strip()}"
        try:
            await self.twitch_client.send_chat_message(
                self.target_channel_id, self.bot_user_id, message
            )
        except Exception:
            logger.warning("Failed to send chat response")

    async def on_gif(self, cmd: ChatCommand) -> None:
        """Handle !gif command."""
        await self._respond(cmd.user.name, self.commands.gif_response)

    async def on_sound(self, cmd: ChatCommand) -> None:
        """Handle !sound command."""
        await self._respond(cmd.user.name, self.commands.sound_response)

    async def on_soundlist(self, cmd: ChatCommand) -> None:
        """Handle !soundlist command."""
        names = validator.get_sound_names()

        if not names:
            await self._respond(cmd.user.name, "🔊 No audio files in the list!")
            return

        if self.commands.soundlist_response != "auto":
            await self._respond(cmd.user.name, self.commands.soundlist_response)
            return

        sound_list = ", ".join(names)
        await self._respond(cmd.user.name, f"🔊 Available sounds: {sound_list}")


async def start_chat_listener(
    twitch_client: Twitch,
    target_channel_name: str,
    target_channel_id: str,
    bot_user_id: str,
    command_settings,
) -> asyncio.Task:
    """Start the chat command listener.

    Uses the same Twitch client for chat (single-account design).
    Returns the asyncio Task running the listener.
    """
    handler = ChatCommandHandler(
        twitch_client=twitch_client,
        target_channel_name=target_channel_name,
        target_channel_id=target_channel_id,
        bot_user_id=bot_user_id,
        command_settings=command_settings,
    )

    async def _run_chat():
        chat = Chat(twitch_client)
        await chat
        chat.register_command("gif", handler.on_gif)
        chat.register_command("sound", handler.on_sound)
        chat.register_command("soundlist", handler.on_soundlist)
        try:
            chat.start()
            await chat.join_room(target_channel_name)
            while chat.is_connected:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Chat listener crashed")
            raise
        finally:
            chat.stop()

    task = asyncio.create_task(_run_chat(), name="chat-listener")
    logger.info("Chat listener started for channel %s", target_channel_name)
    return task
