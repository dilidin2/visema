"""
Chat command listener for !gif, !sound, and !soundlist.

Receives chat messages via EventSub (channel.chat.message) and responds
using the Send Chat Message API. No IRC dependency — unified under EventSub
just like redemption handling in eventsub.py.

Supports both single-account (broadcaster handles everything) and dual-account
(bot account handles chat) modes.
"""

import asyncio
import logging
import re
from typing import Optional

from twitchAPI.eventsub.websocket import EventSubWebsocket
from twitchAPI.twitch import Twitch, TwitchAPIException

from visema.media import validator

logger = logging.getLogger(__name__)


class ChatCommandHandler:
    """Handles chat commands received via EventSub."""

    def __init__(
        self,
        twitch_client: Twitch,
        target_channel_id: str,
        bot_user_id: str,
        command_settings,
    ):
        self.twitch_client = twitch_client
        self.target_channel_id = target_channel_id
        self.bot_user_id = bot_user_id
        self.commands = command_settings

    async def _respond(self, sender_login: str, response: str) -> None:
        """Send a response to chat, pinging the sender."""
        message = f"@{sender_login}: {response.strip()}"
        try:
            await self.twitch_client.send_chat_message(
                self.target_channel_id, self.bot_user_id, message
            )
        except TwitchAPIException as e:
            status = getattr(e, "status_code", None) or getattr(e, "status", None)
            if status == 403:
                logger.error(
                    "Chat send failed with 403 — the bot account lacks permission "
                    "to send messages in channel %s. Fix this by:\n"
                    "  1. Adding the bot as a moderator on the broadcaster's channel, OR\n"
                    "  2. Having the broadcaster authorize the app with 'channel:bot' scope.",
                    self.target_channel_id,
                )
            else:
                logger.warning(
                    "Failed to send chat response (status=%s): %s", status, e
                )
        except Exception:
            logger.exception("Failed to send chat response")

    async def on_chat_message(self, event) -> None:
        """Handle incoming chat messages from EventSub.

        Parses the message for known commands (!gif, !sound, !soundlist).
        Only responds to commands — regular chat is ignored.
        """
        msg_data = event.event
        sender_login = msg_data.chatter_user_login
        message_text = msg_data.message.text if msg_data.message else ""

        # Quick check: skip messages that don't start with !
        if not message_text.startswith("!"):
            return

        # Extract command and arguments
        match = re.match(r"^!(\w+)(?:\s+(.*))?$", message_text.strip(), re.IGNORECASE)
        if not match:
            return

        command = match.group(1).lower()
        args = match.group(2) or ""

        if command == "gif":
            await self._respond(sender_login, self.commands.gif_response)
        elif command == "sound":
            await self._respond(sender_login, self.commands.sound_response)
        elif command == "soundlist":
            await self._handle_soundlist(sender_login)
        else:
            # Unknown command — ignore silently
            pass

    async def _handle_soundlist(self, sender_login: str) -> None:
        """Handle !soundlist command."""
        names = validator.get_sound_names()

        if not names:
            await self._respond(sender_login, "🔊 No audio files in the list!")
            return

        if self.commands.soundlist_response != "auto":
            await self._respond(sender_login, self.commands.soundlist_response)
            return

        sound_list = ", ".join(names)
        await self._respond(sender_login, f"🔊 Available sounds: {sound_list}")


async def start_chat_listener(
    twitch_client: Twitch,
    eventsub: EventSubWebsocket,
    target_channel_id: str,
    bot_user_id: str,
    command_settings,
) -> asyncio.Task:
    """Start the chat command listener via EventSub.

    Subscribes to channel.chat.message on the broadcaster's channel, using
    the bot user ID as the subscriber. Responds to !gif, !sound, and !soundlist.

    Args:
        twitch_client: Twitch client for sending responses (Send Chat Message API).
        eventsub: The EventSub WebSocket instance to subscribe on. Must already
                  be started (eventsub.start() called).
        target_channel_id: Broadcaster's channel ID (where chat is read).
        bot_user_id: User ID of the account reading chat (bot or broadcaster).
        command_settings: Settings object with gif_response, sound_response, etc.

    Returns:
        An asyncio.Task running the listener — compatible with the existing
        main.py interface (asyncio.wait on eventsub_task, chat_task, server_task).
    """
    handler = ChatCommandHandler(
        twitch_client=twitch_client,
        target_channel_id=target_channel_id,
        bot_user_id=bot_user_id,
        command_settings=command_settings,
    )

    async def _subscribe() -> None:
        await eventsub.listen_channel_chat_message(
            broadcaster_user_id=target_channel_id,
            user_id=bot_user_id,
            callback=handler.on_chat_message,
        )

    async def _run_chat() -> None:
        try:
            logger.info("Subscribing to chat messages for channel %s...", target_channel_id)
            await _subscribe()
            logger.info(
                "✓ Chat listener active for channel %s (user_id=%s)",
                target_channel_id,
                bot_user_id,
            )

            # The eventsub WebSocket runs in its own thread and calls our
            # callback on every message. This task just needs to stay alive
            # so that asyncio.wait() in main.py doesn't exit prematurely.
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("Chat listener cancelled")
            raise
        except Exception:
            logger.exception("Chat listener crashed")
            raise

    task = asyncio.create_task(_run_chat(), name="chat-listener")
    return task
