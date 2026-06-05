"""
OAuth2 authorization for both broadcaster and bot Twitch accounts.

Handles the authorization code flow, token refresh, and persists tokens to .env.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from twitchAPI import Twitch
from twitchAPI.oauth import AuthorizationCodeGrant

logger = logging.getLogger(__name__)

# Project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

# Scopes needed per account
BROADCASTER_SCOPES = [
    "channel:read:redemptions",
    "channel:manage:redemptions",
]

BOT_SCOPES = [
    "chat:edit",
    "chat:read",
]


def _read_env() -> dict[str, str]:
    """Read all key=value pairs from .env file."""
    env = {}
    if _ENV_PATH.exists():
        with open(_ENV_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
    return env


def _write_env(env: dict[str, str]) -> None:
    """Write key=value pairs back to .env, preserving comments and structure."""
    # Read existing file to preserve comments
    lines = []
    if _ENV_PATH.exists():
        with open(_ENV_PATH, "r") as f:
            lines = f.readlines()

    # Build a map of existing keys to their line indices
    existing_keys = set()
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if line_stripped and not line_stripped.startswith("#") and "=" in line_stripped:
            key = line_stripped.split("=", 1)[0].strip()
            existing_keys.add(key)

    # Update existing keys or add new ones
    written_keys = set()
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if line_stripped and not line_stripped.startswith("#") and "=" in line_stripped:
            key = line_stripped.split("=", 1)[0].strip()
            if key in env:
                lines[i] = f"{key}={env[key]}\n"
                written_keys.add(key)

    # Append any new keys not already in the file
    for key, value in env.items():
        if key not in written_keys:
            lines.append(f"{key}={value}\n")

    with open(_ENV_PATH, "w") as f:
        f.writelines(lines)

    logger.debug("Updated .env with keys: %s", list(env.keys()))


class TwitchAuth:
    """Manages OAuth2 authentication for a single Twitch account."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        scopes: list[str],
        token_prefix: str,
        label: str = "account",
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scopes
        self.token_prefix = token_prefix  # e.g. "BROADCASTER_" or "BOT_"
        self.label = label
        self._client: Optional[Twitch] = None

    def _get_access_token(self) -> str:
        env = _read_env()
        return env.get(f"{self.token_prefix}ACCESS_TOKEN", "")

    def _get_refresh_token(self) -> str:
        env = _read_env()
        return env.get(f"{self.token_prefix}REFRESH_TOKEN", "")

    def _save_tokens(self, access_token: str, refresh_token: str) -> None:
        _write_env({
            f"{self.token_prefix}ACCESS_TOKEN": access_token,
            f"{self.token_prefix}REFRESH_TOKEN": refresh_token,
        })

    async def authorize(self) -> Twitch:
        """Run the OAuth2 authorization flow.

        Opens a browser for the user to authorize, then saves tokens.
        Returns an authenticated Twitch client.
        """
        access_token = self._get_access_token()
        refresh_token = self._get_refresh_token()

        if access_token and refresh_token:
            logger.info("Using existing tokens for %s", self.label)
        else:
            logger.info("No tokens found for %s, starting authorization flow", self.label)

        grant = AuthorizationCodeGrant(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri="http://localhost",
            scope=self.scopes,
        )

        # If we have a refresh token, use it to get a new access token
        if refresh_token:
            try:
                token = await grant.refresh_token(refresh_token)
                access_token = token["access_token"]
                refresh_token = token.get("refresh_token", refresh_token)
                self._save_tokens(access_token, refresh_token)
                logger.info("Refreshed token for %s", self.label)
            except Exception:
                logger.warning("Token refresh failed for %s, starting new auth flow", self.label)
                access_token = ""
                refresh_token = ""

        if not access_token:
            # Full authorization flow
            auth_url = grant.get_url(self.scopes, "visema_" + self.label)
            logger.info("Authorization URL for %s: %s", self.label, auth_url)
            logger.info("Open this URL in your browser and authorize the app.")

            code = input(f"Enter the authorization code for {self.label}: ").strip()
            token = await grant.fetch_token(code)
            access_token = token["access_token"]
            refresh_token = token.get("refresh_token", "")
            self._save_tokens(access_token, refresh_token)
            logger.info("Saved tokens for %s", self.label)

        # Create the Twitch client
        self._client = Twitch(access_token)
        return self._client

    @property
    def client(self) -> Optional[Twitch]:
        return self._client

    async def get_or_refresh_client(self) -> Twitch:
        """Get the Twitch client, refreshing if needed."""
        if self._client is None:
            return await self.authorize()
        return self._client


async def setup_auth(
    client_id: str,
    client_secret: str,
    broadcaster_name: str,
    bot_name: str,
):
    """Set up authentication for both broadcaster and bot accounts.

    Returns (broadcaster_client, bot_client).
    """
    broadcaster_auth = TwitchAuth(
        client_id=client_id,
        client_secret=client_secret,
        scopes=BROADCASTER_SCOPES,
        token_prefix="BROADCASTER_",
        label=broadcaster_name,
    )

    bot_auth = TwitchAuth(
        client_id=client_id,
        client_secret=client_secret,
        scopes=BOT_SCOPES,
        token_prefix="BOT_",
        label=bot_name,
    )

    logger.info("Authenticating broadcaster account: %s", broadcaster_name)
    broadcaster_client = await broadcaster_auth.authorize()

    logger.info("Authenticating bot account: %s", bot_name)
    bot_client = await bot_auth.authorize()

    return broadcaster_client, bot_client, broadcaster_auth, bot_auth
