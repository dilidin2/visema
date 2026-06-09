"""
EventSub WebSocket listener for Channel Points redemptions.

Subscribes to channel.channel_points_custom_reward_redemption.add
and routes events through validation → queue → broadcast.
Mirrors the pattern from twitch-tts-git with re-auth handling.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Callable, Dict, Optional

from twitchAPI.twitch import Twitch

from visema.media import validator
from visema.media.queue import MediaQueue

logger = logging.getLogger(__name__)

# EventSub topic constant
REDEEM_TOPIC = "channel.channel_points_custom_reward_redemption.add"

# Local registry of reward IDs created by this app
_REWARDS_FILE = Path(__file__).resolve().parent.parent.parent / ".visema_rewards.json"


class RedemptionHandler:
    """Handles Channel Points redemption events from EventSub."""

    def __init__(
        self,
        broadcaster_client: Twitch,
        bot_client: Twitch,
        queue: MediaQueue,
        target_channel_id: str,
        bot_user_id: str,
        reward_gif_name: str,
        reward_sound_name: str,
        gif_settings,
        audio_settings,
        command_settings,
        reward_gif_cost: int = 500,
        reward_sound_cost: int = 300,
    ):
        self.broadcaster_client = broadcaster_client
        self.bot_client = bot_client
        self.queue = queue
        self.target_channel_id = target_channel_id
        self.bot_user_id = bot_user_id

        self.reward_gif_name = reward_gif_name
        self.reward_sound_name = reward_sound_name

        self.gif_settings = gif_settings
        self.audio_settings = audio_settings
        self.command_settings = command_settings
        self.reward_gif_cost = reward_gif_cost
        self.reward_sound_cost = reward_sound_cost

        # Reward IDs — resolved at runtime from the API
        self.reward_gif_id: Optional[str] = None
        self.reward_sound_id: Optional[str] = None

        # Whether each reward was created by this app (can be fulfilled/canceled)
        self._gif_reward_owned = False
        self._sound_reward_owned = False

        # Store for re-subscription after re-auth
        self._eventsub = None

    async def resolve_reward_ids(self) -> None:
        """Fetch custom reward IDs from the Twitch API and check ownership."""
        # Load the local registry of reward IDs created by this app
        registry = self._load_rewards_registry()

        try:
            rewards = await self.broadcaster_client.get_custom_reward(
                self.target_channel_id
            )
        except Exception:
            logger.exception("Failed to fetch channel points rewards")
            return

        for reward in rewards:
            name = reward.title
            reward_id = reward.id
            if name == self.reward_gif_name:
                self.reward_gif_id = reward_id
                self._gif_reward_owned = reward_id in registry.get("gif_reward_id", "")
                logger.info("Resolved GIF reward ID: %s (owned=%s)", reward_id, self._gif_reward_owned)
            elif name == self.reward_sound_name:
                self.reward_sound_id = reward_id
                self._sound_reward_owned = reward_id in registry.get("sound_reward_id", "")
                logger.info("Resolved audio reward ID: %s (owned=%s)", reward_id, self._sound_reward_owned)

        if not self.reward_gif_id:
            logger.warning("GIF reward '%s' not found on channel", self.reward_gif_name)
        if not self.reward_sound_id:
            logger.warning("Audio reward '%s' not found on channel", self.reward_sound_name)

        # Warn about manually-created rewards that can't be managed via API
        if self.reward_gif_id and not self._gif_reward_owned:
            logger.warning(
                "Reward '%s' exists but was not created by this app. "
                "fulfill/cancel via API will not work. "
                "To fix: delete the reward from the Twitch dashboard and restart the app — "
                "it will be recreated automatically.",
                self.reward_gif_name,
            )
        if self.reward_sound_id and not self._sound_reward_owned:
            logger.warning(
                "Reward '%s' exists but was not created by this app. "
                "fulfill/cancel via API will not work. "
                "To fix: delete the reward from the Twitch dashboard and restart the app — "
                "it will be recreated automatically.",
                self.reward_sound_name,
            )

    def _load_rewards_registry(self) -> dict:
        """Load the local registry of reward IDs created by this app."""
        if _REWARDS_FILE.exists():
            try:
                with open(_REWARDS_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                logger.warning("Failed to load rewards registry, starting fresh")
        return {}

    def _save_rewards_registry(self, registry: dict) -> None:
        """Save the local registry of reward IDs created by this app."""
        try:
            with open(_REWARDS_FILE, "w") as f:
                json.dump(registry, f, indent=2)
            logger.info("Saved rewards registry")
        except Exception:
            logger.warning("Failed to save rewards registry")

    async def _create_reward(
        self,
        title: str,
        cost: int,
        prompt: str,
    ) -> Optional[str]:
        """Create a custom reward via API. Returns the reward ID or None on failure."""
        try:
            reward = await self.broadcaster_client.create_custom_reward(
                broadcaster_id=self.target_channel_id,
                title=title,
                cost=cost,
                prompt=prompt,
                is_enabled=True,
                is_user_input_required=True,
                should_redemptions_skip_request_queue=False,
            )
            reward_id = reward.id
            logger.info("Created reward '%s' (id=%s, cost=%d)", title, reward_id, cost)
            return reward_id
        except Exception:
            logger.exception("Failed to create reward '%s'", title)
            return None

    async def ensure_rewards_exist(self) -> None:
        """Create rewards via API if they don't exist yet."""
        registry = self._load_rewards_registry()

        # Ensure GIF reward
        if not self.reward_gif_id:
            reward_id = await self._create_reward(
                title=self.reward_gif_name,
                cost=self.reward_gif_cost,
                prompt="Incolla il link diretto di una GIF da Giphy (i.giphy.com o media.giphy.com)",
            )
            if reward_id:
                self.reward_gif_id = reward_id
                registry["gif_reward_id"] = reward_id
                self._gif_reward_owned = True

        # Ensure audio reward
        if not self.reward_sound_id:
            reward_id = await self._create_reward(
                title=self.reward_sound_name,
                cost=self.reward_sound_cost,
                prompt="Scrivi il nome del suono. Usa !soundlist per la lista.",
            )
            if reward_id:
                self.reward_sound_id = reward_id
                registry["sound_reward_id"] = reward_id
                self._sound_reward_owned = True

        # Save registry if we created any rewards
        if self.reward_gif_id or self.reward_sound_id:
            self._save_rewards_registry(registry)

    async def on_redemption(self, event) -> None:
        """Process a single redemption event."""
        redemption = event.event
        reward_id = redemption.reward.id
        user_id = redemption.user_id
        user_login = redemption.user_login
        redemption_id = redemption.id
        input_text = (redemption.user_input or "").strip()

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
                self.reward_gif_id,
                user_login,
                "❌ Invalid GIF URL. Use a direct Giphy CDN link (i.giphy.com or media.giphy.com). "
                "Right-click a GIF on giphy.com → 'Copy Image Address'.",
            )
            return

        if self.queue.is_full:
            await self._cancel_redemption(
                redemption_id,
                self.reward_gif_id,
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
            await self._fulfill_redemption(redemption_id, self.reward_gif_id)
        else:
            await self._cancel_redemption(
                redemption_id,
                self.reward_gif_id,
                user_login,
                "⏳ Queue is full, please try again later!",
            )

    async def _handle_audio(self, redemption_id: str, user_login: str, name: str) -> None:
        """Validate and enqueue an audio redemption."""
        resolved_path = validator.validate_audio(name)

        if not resolved_path:
            await self._cancel_redemption(
                redemption_id,
                self.reward_sound_id,
                user_login,
                f"❌ Sound '{name}' not found. Use !soundlist to see available sounds.",
            )
            return

        if self.queue.is_full:
            await self._cancel_redemption(
                redemption_id,
                self.reward_sound_id,
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
            await self._fulfill_redemption(redemption_id, self.reward_sound_id)
        else:
            await self._cancel_redemption(
                redemption_id,
                self.reward_sound_id,
                user_login,
                "⏳ Queue is full, please try again later!",
            )

    async def _fulfill_redemption(self, redemption_id: str, reward_id: str) -> None:
        """Mark a redemption as fulfilled."""
        from twitchAPI.type import CustomRewardRedemptionStatus, TwitchAPIException

        # Skip API call if reward is not owned by this app
        if reward_id == self.reward_gif_id and not self._gif_reward_owned:
            logger.debug("Skipping fulfill for manual GIF reward (redemption %s)", redemption_id)
            return
        if reward_id == self.reward_sound_id and not self._sound_reward_owned:
            logger.debug("Skipping fulfill for manual audio reward (redemption %s)", redemption_id)
            return

        try:
            await self.broadcaster_client.update_redemption_status(
                broadcaster_id=self.target_channel_id,
                reward_id=reward_id,
                redemption_ids=redemption_id,
                status=CustomRewardRedemptionStatus.FULFILLED,
            )
        except TwitchAPIException as e:
            # Reward created manually in dashboard — can't fulfill via API.
            # Media is already enqueued, so this is non-fatal.
            logger.warning("Could not fulfill redemption %s (reward not created via API): %s", redemption_id, e)
        except Exception:
            logger.exception("Failed to fulfill redemption %s", redemption_id)

    async def _notify_chat(self, message: str) -> None:
        """Send a notification message to chat via the bot account."""
        try:
            await self.bot_client.send_chat_message(self.target_channel_id, self.bot_user_id, message)
        except Exception:
            logger.warning("Failed to send chat notification")

    async def _cancel_redemption(self, redemption_id: str, reward_id: str, user_login: str, reason: str) -> None:
        """Cancel a redemption (refunds points) and post reason in chat."""
        from twitchAPI.type import CustomRewardRedemptionStatus, TwitchAPIException

        # Check if reward is owned by this app
        is_owned = (
            (reward_id == self.reward_gif_id and self._gif_reward_owned)
            or (reward_id == self.reward_sound_id and self._sound_reward_owned)
        )

        if is_owned:
            try:
                await self.broadcaster_client.update_redemption_status(
                    broadcaster_id=self.target_channel_id,
                    reward_id=reward_id,
                    redemption_ids=redemption_id,
                    status=CustomRewardRedemptionStatus.CANCELED,
                )
                logger.info("Canceled redemption for %s: %s", user_login, reason)
            except TwitchAPIException as e:
                logger.warning("Could not cancel redemption %s (reward not created via API): %s", redemption_id, e)
            except Exception:
                logger.exception("Failed to cancel redemption %s", redemption_id)
        else:
            logger.warning(
                "Cannot cancel redemption for %s (reward not created by this app) — points will NOT be refunded. "
                "Reason: %s", user_login, reason
            )

        await self._chat_message(reason)

    async def _chat_message(self, message: str) -> None:
        """Send a message to chat via the bot account."""
        try:
            await self.bot_client.send_chat_message(self.target_channel_id, self.bot_user_id, message)
        except Exception:
            logger.warning("Failed to send chat message")


async def start_eventsub(
    broadcaster_client: Twitch,
    bot_client: Twitch,
    queue: MediaQueue,
    settings,
    channel_id: str,
    bot_user_id: str,
) -> asyncio.Task:
    """Start the EventSub WebSocket listener.

    Mirrors twitch-tts-git pattern with re-auth on 401 errors.
    Returns the asyncio Task running the listener.
    """
    from twitchAPI.eventsub.websocket import EventSubWebsocket

    handler = RedemptionHandler(
        broadcaster_client=broadcaster_client,
        bot_client=bot_client,
        queue=queue,
        target_channel_id=channel_id,
        bot_user_id=bot_user_id,
        reward_gif_name=settings.twitch.reward_gif,
        reward_sound_name=settings.twitch.reward_sound,
        gif_settings=settings.gif,
        audio_settings=settings.audio,
        command_settings=settings.commands,
        reward_gif_cost=settings.twitch.reward_gif_cost,
        reward_sound_cost=settings.twitch.reward_sound_cost,
    )

    # Resolve reward IDs
    await handler.resolve_reward_ids()

    # Create rewards via API if they don't exist yet
    await handler.ensure_rewards_exist()

    async def _subscribe(eventsub):
        """Create EventSub subscription."""
        await eventsub.listen_channel_points_custom_reward_redemption_add(
            broadcaster_user_id=channel_id,
            callback=handler.on_redemption,
        )

    async def _run_eventsub():
        max_retries = 5
        for attempt in range(max_retries):
            try:
                # Create fresh EventSub with current auth state
                eventsub = EventSubWebsocket(broadcaster_client)
                handler._eventsub = eventsub

                logger.info("Starting EventSub listener for channel %s", channel_id)
                eventsub.start()
                await _subscribe(eventsub)
                logger.info("✓ Listening for channel point redemptions via EventSub")

                # Wait for connection to close (graceful shutdown or crash)
                try:
                    while eventsub._running:
                        await asyncio.sleep(1)
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.exception("EventSub WebSocket crashed")
            except Exception as e:
                error_str = str(e)
                # Re-auth on 401 / auth errors (twitch-tts-git pattern)
                if any(k in error_str for k in ("401", "Unauthorized", "needs user authentication")):
                    logger.warning("Auth error during EventSub — will retry with re-auth")
                    # The broadcaster_client should auto-refresh via the callback
                    await asyncio.sleep(2 ** attempt)
                    continue
                elif "already subscribed" in error_str.lower():
                    # Subscription already exists, connection is fine
                    try:
                        while eventsub._running:
                            await asyncio.sleep(1)
                    except asyncio.CancelledError:
                        break
                    except Exception:
                        pass
                else:
                    logger.error("EventSub error: %s", e)
                    await asyncio.sleep(2 ** min(attempt, 4))
                    continue

            # If we get here without CancelledError, the connection dropped
            wait_time = 2 ** min(attempt, 4)
            logger.info("EventSub disconnected, retrying in %ds...", wait_time)
            await asyncio.sleep(wait_time)

        logger.info("EventSub listener stopped")

    task = asyncio.create_task(_run_eventsub(), name="eventsub-listener")
    return task
