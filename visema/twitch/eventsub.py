"""
EventSub WebSocket listener for Channel Points redemptions.

Subscribes to channel.channel_points_custom_reward_redemption.add
and routes events through validation → queue → broadcast.
"""

import asyncio
import logging
from typing import Callable, Dict, Optional

from twitchAPI.twitch import Twitch

from visema.media import validator
from visema.media.queue import MediaQueue

logger = logging.getLogger(__name__)

# EventSub EventSubTopic constants
# channel.channel_points_custom_reward_redemption.add
REDEEM_TOPIC = "channel.channel_points_custom_reward_redemption.add"


class RedemptionHandler:
    """Handles Channel Points redemption events from EventSub."""

    def __init__(
        self,
        broadcaster_client: Twitch,
        bot_client: Twitch,
        queue: MediaQueue,
        target_channel_id: str,
        reward_gif_name: str,
        reward_sound_name: str,
        gif_settings,
        audio_settings,
        command_settings,
    ):
        self.broadcaster_client = broadcaster_client
        self.bot_client = bot_client
        self.queue = queue
        self.target_channel_id = target_channel_id

        self.reward_gif_name = reward_gif_name
        self.reward_sound_name = reward_sound_name

        self.gif_settings = gif_settings
        self.audio_settings = audio_settings
        self.command_settings = command_settings

        # Reward IDs — resolved at runtime from the API
        self.reward_gif_id: Optional[str] = None
        self.reward_sound_id: Optional[str] = None

    async def resolve_reward_ids(self) -> None:
        """Fetch custom reward IDs from the Twitch API."""
        try:
            rewards = await self.broadcaster_client.get_channel_points_rewards(
                self.target_channel_id
            )
        except Exception:
            logger.exception("Failed to fetch channel points rewards")
            return

        for reward in rewards.get("data", []):
            name = reward.get("title", "")
            reward_id = reward.get("id", "")
            if name == self.reward_gif_name:
                self.reward_gif_id = reward_id
                logger.info("Resolved GIF reward ID: %s", reward_id)
            elif name == self.reward_sound_name:
                self.reward_sound_id = reward_id
                logger.info("Resolved audio reward ID: %s", reward_id)

        if not self.reward_gif_id:
            logger.warning("GIF reward '%s' not found on channel", self.reward_gif_name)
        if not self.reward_sound_id:
            logger.warning("Audio reward '%s' not found on channel", self.reward_sound_name)

    async def on_redemption(self, event: dict) -> None:
        """Process a single redemption event."""
        redemption = event.get("event", {})
        reward_id = redemption.get("reward", {}).get("id", "")
        user_id = redemption.get("user", {}).get("id", "")
        user_login = redemption.get("user", {}).get("login", "")
        redemption_id = redemption.get("id", "")
        input_text = (redemption.get("user_input", "") or "").strip()

        logger.info(
            "Redemption from %s (reward=%s, input='%s')",
            user_login, reward_id, input_text,
        )

        # Determine reward type
        if reward_id == self.reward_gif_id:
            await self._handle_gif(redemption_id, user_login, input_text)
        elif reward_id == self.reward_sound_id:
            await self._handle_audio(redemption_id, user_login, input_text)
        else:
            logger.warning("Unknown reward ID: %s", reward_id)

    async def _handle_gif(self, redemption_id: str, user_login: str, url: str) -> None:
        """Validate and enqueue a GIF redemption."""
        validated_url = validator.validate_gif(url, self.gif_settings.allowed_domains)

        if not validated_url:
            await self._cancel_redemption(
                redemption_id,
                user_login,
                "❌ Invalid GIF URL. Use a direct Giphy CDN link (i.giphy.com or media.giphy.com). "
                "Right-click a GIF on giphy.com → 'Copy Image Address'.",
            )
            return

        if self.queue.is_full:
            await self._cancel_redemption(
                redemption_id,
                user_login,
                "⏳ Queue is full, please try again later!",
            )
            return

        # Enqueue
        item = {
            "type": "gif",
            "url": validated_url,
            "duration": self.gif_settings.display_duration_seconds,
            "user": user_login,
        }

        enqueued = await self.queue.enqueue(item)
        if enqueued:
            await self._fulfill_redemption(redemption_id)
            await self._chat_message(f"🎬 @{user_login}'s GIF is queued! (position {self.queue.size})")
        else:
            await self._cancel_redemption(
                redemption_id,
                user_login,
                "⏳ Queue is full, please try again later!",
            )

    async def _handle_audio(self, redemption_id: str, user_login: str, name: str) -> None:
        """Validate and enqueue an audio redemption."""
        resolved_path = validator.validate_audio(name)

        if not resolved_path:
            await self._cancel_redemption(
                redemption_id,
                user_login,
                f"❌ Sound '{name}' not found. Use !soundlist to see available sounds.",
            )
            return

        if self.queue.is_full:
            await self._cancel_redemption(
                redemption_id,
                user_login,
                "⏳ Queue is full, please try again later!",
            )
            return

        # Build the src path for the overlay (relative to /sounds mount)
        sound_name = resolved_path.stem.lower()
        src = f"/sounds/{resolved_path.name}"

        item = {
            "type": "audio",
            "src": src,
            "volume": self.audio_settings.volume,
            "user": user_login,
        }

        enqueued = await self.queue.enqueue(item)
        if enqueued:
            await self._fulfill_redemption(redemption_id)
            await self._chat_message(f"🔊 @{user_login}'s sound '{sound_name}' is queued! (position {self.queue.size})")
        else:
            await self._cancel_redemption(
                redemption_id,
                user_login,
                "⏳ Queue is full, please try again later!",
            )

    async def _fulfill_redemption(self, redemption_id: str) -> None:
        """Mark a redemption as fulfilled."""
        try:
            await self.broadcaster_client.update_channel_points_redemption(
                broadcaster_id=self.target_channel_id,
                redemption_id=redemption_id,
                status="FULFILLED",
            )
        except Exception:
            logger.exception("Failed to fulfill redemption %s", redemption_id)

    async def _cancel_redemption(self, redemption_id: str, user_login: str, reason: str) -> None:
        """Cancel a redemption (refunds points) and post reason in chat."""
        try:
            await self.broadcaster_client.update_channel_points_redemption(
                broadcaster_id=self.target_channel_id,
                redemption_id=redemption_id,
                status="CANCELED",
            )
            logger.info("Canceled redemption for %s: %s", user_login, reason)
        except Exception:
            logger.exception("Failed to cancel redemption %s", redemption_id)

        await self._chat_message(reason)

    async def _chat_message(self, message: str) -> None:
        """Send a message to chat via the bot account."""
        try:
            await self.bot_client.send_chat_message(self.target_channel_id, message)
        except Exception:
            logger.exception("Failed to send chat message")


async def start_eventsub(
    broadcaster_client: Twitch,
    bot_client: Twitch,
    queue: MediaQueue,
    settings,
    channel_id: str,
) -> asyncio.Task:
    """Start the EventSub WebSocket listener.

    Returns the asyncio Task running the listener.
    """
    from twitchAPI.eventsub import EventSubWebSocket

    handler = RedemptionHandler(
        broadcaster_client=broadcaster_client,
        bot_client=bot_client,
        queue=queue,
        target_channel_id=channel_id,
        reward_gif_name=settings.twitch.reward_gif,
        reward_sound_name=settings.twitch.reward_sound,
        gif_settings=settings.gif,
        audio_settings=settings.audio,
        command_settings=settings.commands,
    )

    # Resolve reward IDs
    await handler.resolve_reward_ids()

    eventsub = EventSubWebSocket(
        broadcaster_client,
        settings.twitch_client_id,
        settings.twitch_client_secret,
    )

    # Subscribe to redemptions
    eventsub.subscribe_channel_points_custom_reward_redemption_add(
        broadcaster_id=channel_id,
        callback=handler.on_redemption,
    )

    async def _run_eventsub():
        try:
            await eventsub.connect()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("EventSub WebSocket crashed")
            raise

    task = asyncio.create_task(_run_eventsub(), name="eventsub-listener")
    logger.info("EventSub listener started for channel %s", channel_id)
    return task
