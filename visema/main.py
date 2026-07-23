"""
Visema — Twitch Channel Points GIF/Sound overlay bot.

Entrypoint: wires everything together and starts the event loop.

Modes:
  Single account (default): uv run visema
    → broadcaster handles EventSub, chat, and API calls
    → tokens saved to token_broadcaster.json

  Dual account (--bot flag): uv run visema --bot
    → requires broadcaster already authenticated (token_broadcaster.json exists)
    → broadcaster: EventSub + redemption management
    → bot: chat messages only (token_bot.json)
"""
import argparse
import asyncio
import logging
import sys

import uvicorn
from twitchAPI.twitch import Twitch

from visema.media import queue as queue_module
from visema.media import validator
from visema.server import app as server_app
from visema.twitch import auth as auth_module
from visema.twitch import chat as chat_module
from visema.twitch import eventsub as eventsub_module
from visema.utils.config import load_settings

logger = logging.getLogger("visema")

BROADCASTER_TOKEN_PATH = "token_broadcaster.json"
BOT_TOKEN_PATH = "token_bot.json"


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the application."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def start_server(settings) -> tuple[asyncio.Task, uvicorn.Server]:
    """Start the FastAPI/uvicorn server as a task in the current event loop.

    Returns (task, server) so the caller can signal graceful shutdown via
    server.should_exit before cancelling the task.
    """
    config = uvicorn.Config(
        server_app.create_app(),
        host="127.0.0.1",
        port=settings.overlay.port,
        log_level="info",
        access_log=False,
        loop="asyncio",
        # Disable lifespan — we don't use startup/shutdown hooks, and the
        # Starlette lifespan task blocks on receive() when cancelled,
        # leaving a CancelledError in the logs.
        lifespan="off",
    )
    # Patch: skip capture_signals so asyncio.run() owns SIGINT/SIGTERM.
    # Without this, uvicorn.capture_signals() installs its own signal.signal()
    # handler which swallows the first Ctrl+C and hangs indefinitely when a
    # WebSocket connection (OBS overlay) is open. The patch makes it a no-op.
    from contextlib import nullcontext
    uvicorn.Server.capture_signals = lambda self: nullcontext()

    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(), name="uvicorn-server")

    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.1)
    else:
        logger.warning("Uvicorn may not have started in time — continuing anyway")

    logger.info("Overlay server running at http://127.0.0.1:%d", settings.overlay.port)
    logger.info("Overlay page: http://127.0.0.1:%d/overlay", settings.overlay.port)
    logger.info("WebSocket endpoint: ws://localhost:%d/ws", settings.overlay.port)
    logger.info("")
    logger.info("── OBS SETUP ─────────────────────────────────────────────────")
    logger.info("Add a Browser Source in OBS with URL: http://127.0.0.1:%d/overlay", settings.overlay.port)
    logger.info("Set width/height to your canvas (e.g. 1920x1080), enable 'Allow transparency'")
    logger.info("─────────────────────────────────────────────────────────────")

    return task, server


async def _ensure_auth(
    twitch_service: auth_module.TwitchService, account_label: str
) -> None:
    """Ensure a TwitchService is authenticated — run DCF if tokens are missing."""
    if twitch_service.token_path.exists():
        logger.info("✓ %s connected automatically (saved tokens loaded)", account_label)
    else:
        logger.warning(
            "⚠️  No %s found — starting Device Code Flow for %s",
            twitch_service.token_path,
            account_label,
        )
        await twitch_service._do_device_auth()


async def _get_user_info(client: Twitch) -> tuple[str, str]:
    """Resolve username and user ID from the authenticated client.

    Returns (login_name, user_id).
    """
    async for user in client.get_users():
        return user.login, user.id

    raise ValueError("Could not resolve user info from get_users()")


async def run(use_bot: bool = False) -> None:
    """Main async entrypoint."""
    settings = load_settings()
    logger.info("Visema starting up...")

    # ── Build sounds index ──────────────────────────────
    validator.build_sounds_index(
        settings.sounds_dir_path,
        settings.audio.allowed_extensions,
    )

    # ── Start overlay server (same event loop as queue worker) ─
    server_task, server = await start_server(settings)

    # ── Setup media queue ───────────────────────────────
    max_queue = max(settings.gif.max_queue_size, settings.audio.max_queue_size)
    cooldown = max(settings.gif.cooldown_seconds, settings.audio.cooldown_seconds)

    media_queue = queue_module.MediaQueue(
        max_size=max_queue,
        cooldown_seconds=cooldown,
    )
    await media_queue.start()

    # ── Determine mode ──────────────────────────────────
    if use_bot:
        logger.info("Dual-account mode (--bot): broadcaster + bot")

        from pathlib import Path
        if not Path(BROADCASTER_TOKEN_PATH).exists():
            logger.error(
                "Broadcaster token not found (%s).\n"
                "Run `uv run visema` first to authenticate the broadcaster account.",
                BROADCASTER_TOKEN_PATH,
            )
            sys.exit(1)
    else:
        logger.info("Single-account mode (default)")

    # ── Connect broadcaster account ─────────────────────
    broadcaster_service = auth_module.TwitchService(
        client_id=settings.twitch_client_id,
        token_path=BROADCASTER_TOKEN_PATH,
    )

    try:
        await broadcaster_service.connect()
    except Exception as e:
        logger.error("Failed to initialize broadcaster Twitch client: %s", e)
        sys.exit(1)

    # Auth DCF only in single-account mode (dual mode requires pre-existing token)
    if not use_bot:
        await _ensure_auth(broadcaster_service, "broadcaster")

    # Resolve broadcaster info from API
    try:
        broadcaster_name, broadcaster_id = await _get_user_info(
            broadcaster_service.twitch
        )
    except Exception:
        logger.error("Failed to resolve broadcaster info")
        sys.exit(1)

    logger.info("Broadcaster: %s (ID: %s)", broadcaster_name, broadcaster_id)

    # ── Setup bot account or reuse broadcaster ──────────
    if use_bot:
        from twitchAPI.type import AuthScope

        # Bot account needs USER_BOT to join another channel's chat via EventSub.
        # Combined with the base scopes (read/write chat + redemptions).
        bot_scopes = auth_module.REQUIRED_SCOPES + [AuthScope.USER_BOT]

        bot_service = auth_module.TwitchService(
            client_id=settings.twitch_client_id,
            token_path=BOT_TOKEN_PATH,
            scopes=bot_scopes,
        )
        try:
            await bot_service.connect()
        except Exception as e:
            logger.error("Failed to initialize bot Twitch client: %s", e)
            sys.exit(1)

        await _ensure_auth(bot_service, "bot")

        try:
            _, bot_user_id = await _get_user_info(bot_service.twitch)
        except Exception:
            logger.error("Failed to resolve bot user info")
            sys.exit(1)

        chat_client = bot_service.twitch
        logger.info("Bot account: user_id=%s", bot_user_id)
    else:
        bot_user_id = broadcaster_id
        chat_client = broadcaster_service.twitch

    # ── Create and start EventSub instances ─────────────
    from twitchAPI.eventsub.websocket import EventSubWebsocket

    # Broadcaster EventSub: used for redemptions (always).
    # In single-account mode, also shared with the chat listener.
    broadcaster_eventsub = EventSubWebsocket(broadcaster_service.twitch)
    broadcaster_service.eventsub = broadcaster_eventsub
    broadcaster_service._external_eventsub = broadcaster_eventsub
    broadcaster_eventsub.start()
    logger.info("Broadcaster EventSub started")

    # Bot EventSub: only needed in dual-account mode for chat messages.
    # Each Twitch client can only have one EventSubWebsocket (thread-bound),
    # so the bot gets its own separate connection.
    bot_eventsub = None
    if use_bot:
        bot_eventsub = EventSubWebsocket(bot_service.twitch)
        bot_service.eventsub = bot_eventsub
        bot_service._external_eventsub = bot_eventsub
        bot_eventsub.start()
        logger.info("Bot EventSub started")

    # ── Start EventSub listener (redemptions)
    # EventSub connections are already started above — start_eventsub()
    # only handles subscription + retry loop, not the connection itself.
    #──────────────────────────────────────────────────────
    eventsub_task = await eventsub_module.start_eventsub(
        twitch_service=broadcaster_service,
        queue=media_queue,
        settings=settings,
        channel_id=broadcaster_id,
        bot_user_id=bot_user_id,
        chat_client=chat_client if use_bot else None,
        eventsub_instance=broadcaster_eventsub,
    )

    # ── Start chat listener (EventSub-based)
    # Both EventSub connections are already running at this point,
    # so subscribe calls in both eventsub.py and chat.py are safe.
    #──────────────────────────────────────────────────────
    # Single-account: reuse broadcaster EventSub.
    # Dual-account: use bot's own EventSub.
    chat_eventsub = broadcaster_eventsub if not use_bot else bot_eventsub
    chat_task = await chat_module.start_chat_listener(
        twitch_client=chat_client,
        eventsub=chat_eventsub,
        target_channel_id=broadcaster_id,
        bot_user_id=bot_user_id,
        command_settings=settings.commands,
    )

    logger.info("Visema is running! Press Ctrl+C to stop.")

    # ── Run until interrupted ───────────────────────────
    try:
        done, pending = await asyncio.wait(
            [eventsub_task, chat_task, server_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down...")

        # Signal uvicorn to exit its run loop so it closes listeners and
        # cleans up internal threads — without this, a brute-force cancel()
        # leaves background threads alive and Python refuses to exit.
        server.should_exit = True

        for task in [eventsub_task, chat_task, server_task]:
            task.cancel()
        # Give all tasks a chance to finish (uvicorn needs it for thread cleanup)
        await asyncio.sleep(0.5)

        # Stop EventSub connections (external instances managed by main.py)
        try:
            await broadcaster_eventsub.stop()
            logger.info("Broadcaster EventSub stopped")
        except Exception:
            logger.exception("Error stopping broadcaster EventSub")
        if bot_eventsub is not None:
            try:
                await bot_eventsub.stop()
                logger.info("Bot EventSub stopped")
            except Exception:
                logger.exception("Error stopping bot EventSub")

        # Disconnect Twitch clients (token cleanup, no EventSub — already done above)
        for svc in [broadcaster_service]:
            await svc.disconnect()
        if use_bot:
            await bot_service.disconnect()

        await media_queue.stop()
        logger.info("Visema stopped.")


def main():
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Visema — Twitch Channel Points overlay bot"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--bot",
        action="store_true",
        help="Use separate bot account for chat messages",
    )
    args = parser.parse_args()

    setup_logging(args.verbose)

    asyncio.run(run(use_bot=args.bot))


if __name__ == "__main__":
    main()
