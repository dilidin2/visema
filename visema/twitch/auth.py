"""
Twitch authentication via Device Code Flow.

Manages per-account OAuth tokens with configurable token file paths.
Supports both single-account (token.json) and dual-account mode
(token_broadcaster.json + token_bot.json).

Retrocompatible: if a specific token file doesn't exist, falls back to legacy token.json.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from aiohttp import ClientSession
from twitchAPI.eventsub.websocket import EventSubWebsocket
from twitchAPI.twitch import Twitch
from twitchAPI.type import AuthScope

logger = logging.getLogger(__name__)

# Public Visema app — override via TWITCH_CLIENT_ID in .env for forks
DEFAULT_CLIENT_ID = "fdf2c1k8jj7j6nfctiyo2ijavckiv5"

# Retrocompatibilità: se token.json esiste ma il file specifico non c'è, usa token.json come fallback
_DEFAULT_TOKEN_PATH = Path("token.json")

DEVICE_CODE_URL = "https://id.twitch.tv/oauth2/device"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"

# All scopes needed: EventSub + chat + redemption management
REQUIRED_SCOPES = [
    AuthScope.CHANNEL_READ_REDEMPTIONS,
    AuthScope.CHANNEL_MANAGE_REDEMPTIONS,
    AuthScope.CHAT_EDIT,
    AuthScope.CHAT_READ,
    AuthScope.USER_WRITE_CHAT,
]


class TwitchService:
    """Manages single-account Twitch auth (DCF) and EventSub connection."""

    def __init__(self, client_id: str, token_path: str = "token.json"):
        self.client_id = client_id
        self.token_path = Path(token_path)
        self.twitch: Optional[Twitch] = None
        self.eventsub: Optional[EventSubWebsocket] = None

        # DCF state
        self._auth_status: str = "idle"  # idle | pending | success | expired | denied
        self._auth_future: Optional[asyncio.Future] = None

    # ── Auth helpers ──────────────────────────────────────────────────────────

    async def _user_auth_refresh_callback(self, token: str, refresh_token: str) -> None:
        """Called by twitchAPI on every token refresh — persist to disk."""
        logger.info("OAuth token refreshed — saving new tokens to %s", self.token_path)
        with open(self.token_path, "w") as f:
            json.dump({"token": token, "refresh": refresh_token}, f)

    async def _get_device_code(self) -> dict:
        scope_str = " ".join(s.value if hasattr(s, "value") else str(s) for s in REQUIRED_SCOPES)
        data = {"client_id": self.client_id, "scope": scope_str}
        async with ClientSession() as session:
            async with session.post(DEVICE_CODE_URL, data=data) as resp:
                return await resp.json()

    async def _poll_for_token(
        self, device_code: str, interval: int
    ) -> tuple[str, str]:
        """Poll Twitch for the user token after they authorize."""
        current_interval = interval
        scope_str = " ".join(s.value if hasattr(s, "value") else str(s) for s in REQUIRED_SCOPES)
        async with ClientSession() as session:
            while True:
                data = {
                    "client_id": self.client_id,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "scope": scope_str,
                }
                async with session.post(TOKEN_URL, data=data) as resp:
                    result = await resp.json()

                if resp.status == 200 and "access_token" in result:
                    return result["access_token"], result["refresh_token"]

                error = result.get("error")
                if error == "authorization_pending":
                    pass
                elif error == "slow_down":
                    logger.warning("Twitch OAuth: slow_down — increasing poll interval")
                    current_interval += 5
                elif error == "expired_token":
                    self._auth_status = "expired"
                    if self._auth_future and not self._auth_future.done():
                        self._auth_future.set_exception(
                            TimeoutError("Authorization expired")
                        )
                    raise TimeoutError("Device code expired — user did not authorize in time")
                elif error == "access_denied":
                    self._auth_status = "denied"
                    if self._auth_future and not self._auth_future.done():
                        self._auth_future.set_exception(
                            RuntimeError("User denied authorization")
                        )
                    raise RuntimeError("User denied authorization")

                await asyncio.sleep(current_interval)

    async def _do_device_auth(self) -> tuple[str, str]:
        """Execute the Device Code Flow (blocking). Returns (access_token, refresh_token).

        Saves tokens to disk and sets user authentication on the Twitch client.
        """
        device_info = await self._get_device_code()
        user_code = device_info["user_code"]
        verification_uri = device_info["verification_uri"]
        expires_in = device_info["expires_in"]
        interval = device_info["interval"]

        logger.info(
            f"Twitch Device Code Flow — go to {verification_uri} "
            f"and enter code: {user_code}"
        )
        logger.info(f"Code expires in {expires_in}s, polling every {interval}s")

        self._auth_status = "pending"

        token, refresh_token = await self._poll_for_token(
            device_info["device_code"], interval
        )

        with open(self.token_path, "w") as f:
            json.dump({"token": token, "refresh": refresh_token}, f)
        logger.info("✓ Tokens saved to %s", self.token_path)

        # Apply user authentication to the Twitch client
        await self.twitch.set_user_authentication(token, REQUIRED_SCOPES, refresh_token)
        logger.info("✓ User authentication set on Twitch client")

        self._auth_status = "success"
        return token, refresh_token

    async def _start_device_flow_async(self) -> dict:
        """Start DCF in the background. Returns info for the user to complete auth."""
        device_info = await self._get_device_code()
        user_code = device_info["user_code"]
        verification_uri = device_info["verification_uri"]
        expires_in = device_info["expires_in"]
        interval = device_info["interval"]

        logger.info(
            f"Twitch Device Code Flow — go to {verification_uri} "
            f"and enter code: {user_code}"
        )
        logger.info(f"Code expires in {expires_in}s, polling every {interval}s")

        self._auth_status = "pending"
        self._auth_future = asyncio.get_event_loop().create_future()

        asyncio.create_task(
            self._poll_and_connect(device_info["device_code"], interval)
        )

        return {
            "verification_uri": verification_uri,
            "user_code": user_code,
            "expires_in": expires_in,
        }

    async def _poll_and_connect(self, device_code: str, interval: int) -> None:
        """Poll for token and, on success, connect to Twitch automatically."""
        try:
            token, refresh_token = await self._poll_for_token(device_code, interval)
            with open(self.token_path, "w") as f:
                json.dump({"token": token, "refresh": refresh_token}, f)

            await self.connect()
            await self.authenticate_user()

            if self._auth_future and not self._auth_future.done():
                self._auth_future.set_result(True)
        except Exception as e:
            logger.error(f"DCF flow failed: {e}")
            if self._auth_future and not self._auth_future.done():
                self._auth_future.set_exception(e)

    # ── Public API ────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Initialize the Twitch client, loading tokens from self.token_path if present."""
        logger.info("Initializing Twitch client...")
        self.twitch = Twitch(
            app_id=self.client_id, app_secret="", authenticate_app=False
        )

        # Register refresh callback BEFORE setting any token
        self.twitch.user_auth_refresh_callback = self._user_auth_refresh_callback

        # Check specific token file first, fallback to legacy token.json
        token_file = self.token_path
        if not token_file.exists() and _DEFAULT_TOKEN_PATH.exists():
            logger.info("Falling back to legacy token.json")
            token_file = _DEFAULT_TOKEN_PATH

        if token_file.exists():
            try:
                with open(token_file, "r") as f:
                    creds = json.load(f)
                logger.info("Loading existing tokens from %s...", token_file)
                await self.twitch.set_user_authentication(
                    creds["token"], REQUIRED_SCOPES, creds["refresh"]
                )
                logger.info("✓ Tokens loaded from %s", token_file)
            except Exception as e:
                logger.warning(
                    "Failed to load tokens (%s) — starting Device Code Flow for re-authentication",
                    e,
                )
                token, refresh_token = await self._do_device_auth()
                await self.twitch.set_user_authentication(
                    token, REQUIRED_SCOPES, refresh_token
                )
        else:
            logger.info("No %s found — start Device Code Flow to authorize", self.token_path)

        logger.info("Twitch client initialized")

    async def reauthenticate_if_needed(self) -> None:
        """Re-authenticate via Device Code Flow (e.g. after a 401)."""
        logger.warning("Re-authenticating via Device Code Flow...")
        token, refresh_token = await self._do_device_auth()
        await self.twitch.set_user_authentication(token, REQUIRED_SCOPES, refresh_token)
        with open(self.token_path, "w") as f:
            json.dump({"token": token, "refresh": refresh_token}, f)
        logger.info("✓ Re-authenticated successfully")

    async def authenticate_user(self) -> None:
        """Create the EventSub WebSocket client (call after connect())."""
        logger.info("Creating EventSub client...")
        self.eventsub = EventSubWebsocket(twitch=self.twitch)
        logger.info("EventSub client created")

    async def listen_channel_points_redemption(
        self, broadcaster_id: str, callback
    ) -> None:
        """Subscribe to Channel Points redemptions for the given broadcaster."""
        if not self.eventsub:
            raise RuntimeError("Call authenticate_user() first to create EventSub")

        async def _subscribe() -> None:
            await self.eventsub.listen_channel_points_custom_reward_redemption_add(
                broadcaster_user_id=broadcaster_id,
                callback=callback,
            )

        try:
            logger.info(f"Starting EventSub listener for broadcaster: {broadcaster_id}")
            self.eventsub.start()
            await _subscribe()
            logger.info("✓ Listening for channel point redemptions via EventSub")
        except Exception as e:
            error_str = str(e)
            if any(k in error_str for k in ("401", "Unauthorized", "needs user authentication")):
                logger.warning("Auth error during EventSub subscribe — re-authenticating...")
                await self.reauthenticate_if_needed()
                self.eventsub = EventSubWebsocket(twitch=self.twitch)
                self.eventsub.start()
                await _subscribe()
                logger.info("✓ Re-subscribed after re-authentication")
            else:
                logger.error(f"Failed to start redemption listener: {e}")
                raise

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def disconnect(self) -> None:
        if self.eventsub:
            logger.info("Stopping EventSub client...")
            await self.eventsub.stop()
            self.eventsub = None
            logger.info("EventSub disconnected")

    async def reconnect(self, max_retries: int = 5) -> bool:
        """Try to reconnect. Returns True on success."""
        if self.eventsub:
            return True

        for attempt in range(max_retries):
            try:
                await self.connect()
                await self.authenticate_user()
                return True
            except Exception as e:
                wait_time = 2**attempt
                logger.warning(
                    f"Reconnection attempt {attempt + 1}/{max_retries} failed: {e}. "
                    f"Retrying in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)

        logger.error("Max reconnection attempts reached!")
        return False
