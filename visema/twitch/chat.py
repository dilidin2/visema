"""
Chat command listener for !gif, !sound, and !soundlist.

Uses the bot account to listen on the broadcaster's channel.
All commands are read-only — they do not trigger overlay or queue actions.
"""

import asyncio
import logging
from typing import Optional

from twitchAPI.twitch import Twitch

from visema.media import validator

logger = logging.getLogger(__name__)


class ChatCommandHandler:
    """Handles chat commands received on the broadcaster's channel."""

    def __init__(
        self,
        bot_client: Twitch,
        target_channel_id: str,
        command_settings,
    ):
        self.bot_client = bot_client
        self.target_channel_id = target_channel_id
        self.commands = command_settings
        self._running = False

    async def on_message(self, message) -> None:
        """Process a chat message for commands."""
        text = message.message.lower().strip()
        sender = message.sender.name

        if text.startswith("!gif"):
            await self._respond(sender, self.commands.gif_response)
        elif text.startswith("!sound"):
            await self._respond(sender, self.commands.sound_response)
        elif text.startswith("!soundlist"):
            await self._handle_soundlist(sender)
        elif text.startswith("!visemaskip"):
            # Placeholder for future skip command
            logger.info("@%s used !visemaskip", sender)

    async def _respond(self, sender: str, response: str) -> None:
        """Send a response to chat, pinging the sender."""
        message = f"@{sender}: {response.strip()}"
        try:
            await self.bot_client.send_chat_message(self.target_channel_id, message)
        except Exception:
            logger.exception("Failed to send chat response")

    async def _handle_soundlist(self, sender: str) -> None:
        """List available sounds."""
        names = validator.get_sound_names()

        if not names:
            await self._respond(sender, "🔊 No sounds available yet.")
            return

        if self.commands.soundlist_response != "auto":
            await self._respond(sender, self.commands.soundlist_response)
            return

        # Auto-generate from sounds index
        sound_list = ", ".join(names)
        await self._respond(sender, f"🔊 Available sounds: {sound_list}")


async def start_chat_listener(
    bot_client: Twitch,
    target_channel_id: str,
    command_settings,
) -> asyncio.Task:
    """Start the chat command listener.

    Returns the asyncio Task running the listener.
    """
    handler = ChatCommandHandler(
        bot_client=bot_client,
        target_channel_id=target_channel_id,
        command_settings=command_settings,
    )

    from twitchAPI.chat import ChatListener

    chat = ChatListener(
        channel=target_channel_id,
        client=bot_client,
    )
    chat.on_message(handler.on_message)

    async def _run_chat():
        try:
            await chat.connect()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Chat listener crashed")
            raise

    task = asyncio.create_task(_run_chat(), name="chat-listener")
    logger.info("Chat listener started for channel %s", target_channel_id)
    return task
