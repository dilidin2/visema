"""
Visema — Twitch Channel Points GIF/Sound overlay bot.

Entrypoint: wires everything together and starts the event loop.
"""

import argparse
import asyncio
import logging
import sys
import threading

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


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the application."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def start_server(settings, stop_event: threading.Event) -> threading.Thread:
    """Start the FastAPI server in a background thread."""

    def _run():
        server = uvicorn.Server(
            uvicorn.Config(
                server_app.create_app(),
                host="127.0.0.1",
                port=settings.overlay.port,
                log_level="info",
                access_log=False,
            )
        )
        server.run()

    thread = threading.Thread(target=_run, name="uvicorn-server", daemon=True)
    thread.start()

    # Wait for server to be ready
    import time
    for _ in range(30):
        if thread.is_alive():
            # Give it a moment to bind
            time.sleep(0.2)
            # We check by trying to import; if uvicorn started without error, it's running
            break
        time.sleep(0.1)

    logger.info("Overlay server running at http://127.0.0.1:%d", settings.overlay.port)
    logger.info("Overlay page: http://127.0.0.1:%d/overlay", settings.overlay.port)
    logger.info("WebSocket endpoint: ws://127.0.0.1:%d/ws", settings.overlay.port)
    logger.info("")
    logger.info("── OBS SETUP ─────────────────────────────────────────────────")
    logger.info("Add a Browser Source in OBS with URL: http://127.0.0.1:%d/overlay", settings.overlay.port)
    logger.info("Set width/height to your canvas (e.g. 1920x1080), enable 'Allow transparency'")
    logger.info("─────────────────────────────────────────────────────────────")

    return thread


async def get_channel_id(client: Twitch, channel_name: str) -> str:
    """Resolve a channel name to its Twitch user ID via the authenticated client."""
    async for user in client.get_users(logins=[channel_name]):
        return user.id

    raise ValueError(f"Could not resolve channel ID for '{channel_name}'")


async def run() -> None:
    """Main async entrypoint."""
    settings = load_settings()
    logger.info("Visema starting up...")

    # ── Build sounds index ──────────────────────────────
    validator.build_sounds_index(
        settings.sounds_dir_path,
        settings.audio.allowed_extensions,
    )

    # ── Start overlay server ────────────────────────────
    stop_event = threading.Event()
    server_thread = start_server(settings, stop_event)

    # ── Setup media queue ───────────────────────────────
    max_queue = max(settings.gif.max_queue_size, settings.audio.max_queue_size)
    cooldown = max(settings.gif.cooldown_seconds, settings.audio.cooldown_seconds)

    media_queue = queue_module.MediaQueue(
        max_size=max_queue,
        cooldown_seconds=cooldown,
    )
    await media_queue.start()

    # ── Authenticate Twitch accounts ────────────────────
    broadcaster_client, bot_client = await auth_module.setup_auth(
        client_id=settings.twitch_client_id,
        client_secret=settings.twitch_client_secret,
        broadcaster_name=settings.twitch.target_channel,
        bot_name=settings.twitch.bot_channel,
    )

    # ── Resolve channel IDs ─────────────────────────────
    if settings.twitch.target_channel_id:
        channel_id = settings.twitch.target_channel_id
    else:
        try:
            channel_id = await get_channel_id(broadcaster_client, settings.twitch.target_channel)
        except Exception:
            logger.error("Failed to resolve channel ID for '%s'", settings.twitch.target_channel)
            sys.exit(1)

    # Resolve bot user ID from the authenticated client (guaranteed to match the OAuth token)
    async for user in bot_client.get_users():
        bot_user_id = user.id
        break

    logger.info("Target channel: %s (ID: %s)", settings.twitch.target_channel, channel_id)

    # ── Start EventSub listener ─────────────────────────
    eventsub_task = await eventsub_module.start_eventsub(
        broadcaster_client=broadcaster_client,
        bot_client=bot_client,
        queue=media_queue,
        settings=settings,
        channel_id=channel_id,
        bot_user_id=bot_user_id,
    )

    # ── Start chat listener ─────────────────────────────
    chat_task = await chat_module.start_chat_listener(
        bot_client=bot_client,
        target_channel_name=settings.twitch.target_channel,
        target_channel_id=channel_id,
        bot_user_id=bot_user_id,
        command_settings=settings.commands,
    )

    logger.info("Visema is running! Press Ctrl+C to stop.")

    # ── Run until interrupted ───────────────────────────
    try:
        # Wait for either task to finish (shouldn't happen normally)
        done, pending = await asyncio.wait(
            [eventsub_task, chat_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down...")
        for task in [eventsub_task, chat_task]:
            task.cancel()
        await media_queue.stop()
        stop_event.set()
        logger.info("Visema stopped.")


def main():
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Visema — Twitch Channel Points overlay bot")
    parser.add_argument("--setup", action="store_true", help="Run OAuth setup and exit")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    setup_logging(args.verbose)

    asyncio.run(run())


if __name__ == "__main__":
    main()
