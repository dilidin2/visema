"""
OAuth2 authorization for both broadcaster and bot Twitch accounts.

Handles the authorization code flow (via browser), token refresh,
and persists tokens to .env. Mirrors the pattern used in twitch-tts-git.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from twitchAPI.twitch import Twitch
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.type import AuthScope

logger = logging.getLogger(__name__)

# Project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

# Scopes needed per account
BROADCASTER_SCOPES = [
    AuthScope.CHANNEL_READ_REDEMPTIONS,
    AuthScope.CHANNEL_MANAGE_REDEMPTIONS,
]

BOT_SCOPES = [
    AuthScope.CHAT_EDIT,
    AuthScope.CHAT_READ,
    AuthScope.USER_WRITE_CHAT,
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
    lines = []
    if _ENV_PATH.exists():
        with open(_ENV_PATH, "r") as f:
            lines = f.readlines()

    existing_keys = set()
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if line_stripped and not line_stripped.startswith("#") and "=" in line_stripped:
            key = line_stripped.split("=", 1)[0].strip()
            existing_keys.add(key)

    written_keys = set()
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if line_stripped and not line_stripped.startswith("#") and "=" in line_stripped:
            key = line_stripped.split("=", 1)[0].strip()
            if key in env:
                lines[i] = f"{key}={env[key]}\n"
                written_keys.add(key)

    for key, value in env.items():
        if key not in written_keys:
            lines.append(f"{key}={value}\n")

    with open(_ENV_PATH, "w") as f:
        f.writelines(lines)

    logger.debug("Updated .env with keys: %s", list(env.keys()))


async def _user_auth_refresh_callback(token: str, refresh_token: str, token_prefix: str) -> None:
    """
    Called automatically by twitchAPI whenever the OAuth token is refreshed.
    Persisting new tokens here prevents silent expiry after ~4 hours.
    Mirrors the pattern from twitch-tts-git.
    """
    logger.info("OAuth token refreshed — saving new tokens to .env")
    _write_env({
        f"{token_prefix}ACCESS_TOKEN": token,
        f"{token_prefix}REFRESH_TOKEN": refresh_token,
    })


async def _do_browser_auth(
    twitch: Twitch,
    scopes: list[str],
    token_prefix: str,
    label: str,
) -> tuple[str, str]:
    """Open browser for first-time or re-authentication, return (token, refresh)."""
    logger.info("Opening browser for %s OAuth authentication...", label)
    auth = UserAuthenticator(
        twitch,
        scopes,
        force_verify=False,
    )
    token, refresh_token = await auth.authenticate()
    _write_env({
        f"{token_prefix}ACCESS_TOKEN": token,
        f"{token_prefix}REFRESH_TOKEN": refresh_token,
    })
    logger.info("Saved tokens for %s", label)
    return token, refresh_token


async def _authenticate_account(
    client_id: str,
    client_secret: str,
    scopes: list[str],
    token_prefix: str,
    label: str,
) -> Twitch:
    """
    Authenticate a single Twitch account using the twitch-tts-git pattern:

    1. Load existing tokens from .env
    2. If valid, use them (with auto-refresh callback)
    3. If missing/expired, open browser for OAuth flow
    4. Save tokens back to .env on every refresh

    Returns an authenticated Twitch client.
    """
    env = _read_env()
    access_token = env.get(f"{token_prefix}ACCESS_TOKEN", "")
    refresh_token = env.get(f"{token_prefix}REFRESH_TOKEN", "")

    logger.info("Initializing Twitch client for %s...", label)
    twitch = Twitch(client_id, client_secret)

    # Register the auto-refresh callback BEFORE setting any token,
    # so the library transparently persists renewed tokens on every refresh.
    twitch.user_auth_refresh_callback = lambda t, r: _user_auth_refresh_callback(t, r, token_prefix)  # noqa: E731

    if access_token and refresh_token:
        logger.info("Loading existing tokens for %s from .env...", label)
        try:
            await twitch.set_user_authentication(
                access_token,
                scopes,
                refresh_token,
            )
            logger.info("✓ Tokens loaded for %s", label)
        except Exception as e:
            logger.warning("Failed to load tokens (%s) — falling back to browser auth", e)
            access_token = ""
            refresh_token = ""

    if not access_token:
        # First-time or re-authentication via browser
        token, refresh_token = await _do_browser_auth(twitch, scopes, token_prefix, label)
        await twitch.set_user_authentication(token, scopes, refresh_token)

    logger.info("✓ %s authenticated", label)
    return twitch


async def setup_auth(
    client_id: str,
    client_secret: str,
    broadcaster_name: str,
    bot_name: str,
):
    """Set up authentication for both broadcaster and bot accounts.

    Uses the same pattern as twitch-tts-git:
    - Loads existing tokens from .env
    - Opens browser automatically for first-time auth
    - Auto-refreshes tokens on expiry

    Returns (broadcaster_client, bot_client).
    """
    logger.info("Authenticating broadcaster account: %s", broadcaster_name)
    broadcaster_client = await _authenticate_account(
        client_id=client_id,
        client_secret=client_secret,
        scopes=BROADCASTER_SCOPES,
        token_prefix="BROADCASTER_",
        label=broadcaster_name,
    )

    logger.info("Authenticating bot account: %s", bot_name)
    bot_client = await _authenticate_account(
        client_id=client_id,
        client_secret=client_secret,
        scopes=BOT_SCOPES,
        token_prefix="BOT_",
        label=bot_name,
    )

    return broadcaster_client, bot_client
