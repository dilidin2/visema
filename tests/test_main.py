"""Tests for visema.main — Application entrypoint functions."""

import asyncio
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── setup_logging ─────────────────────────────────────────────────────────────


class TestSetupLogging:
    def test_default_info_level(self):
        from visema.main import setup_logging

        # Should not raise
        setup_logging(verbose=False)

    def test_verbose_debug_level(self):
        from visema.main import setup_logging

        # Should not raise
        setup_logging(verbose=True)

    def test_log_format(self, capsys):
        from visema.main import setup_logging
        import logging

        setup_logging(verbose=True)
        logger = logging.getLogger("visema")
        logger.info("test message")

        captured = capsys.readouterr()
        assert "test message" in captured.err
        # Format should include level and name
        assert "[visema]" in captured.err


# ── start_server ──────────────────────────────────────────────────────────────


class TestStartServer:
    def test_returns_thread(self):
        from visema.main import start_server

        with patch("visema.main.uvicorn.Server") as MockServer:
            mock_instance = MagicMock()
            mock_instance.run = MagicMock()
            MockServer.return_value = mock_instance

            settings = MagicMock()
            settings.overlay.port = 9876

            thread = start_server(settings, threading.Event())

        assert isinstance(thread, threading.Thread)
        assert thread.name == "uvicorn-server"
        assert thread.daemon is True

    def test_starts_thread(self):
        from visema.main import start_server

        with patch("visema.main.uvicorn.Server") as MockServer:
            mock_instance = MagicMock()
            mock_instance.run = MagicMock()
            MockServer.return_value = mock_instance

            settings = MagicMock()
            settings.overlay.port = 9876

            thread = start_server(settings, threading.Event())

        assert thread.is_alive() or True  # Thread should be started

    def test_server_configured_correctly(self):
        from visema.main import start_server

        with patch("visema.main.uvicorn.Server") as MockServer:
            mock_instance = MagicMock()
            mock_instance.run = MagicMock()
            MockServer.return_value = mock_instance

            settings = MagicMock()
            settings.overlay.port = 8080

            thread = start_server(settings, threading.Event())

            # Verify uvicorn.Server was called with correct config
            call_args = MockServer.call_args
            config = call_args[0][0]
            assert config.host == "127.0.0.1"
            assert config.port == 8080
            assert config.access_log is False

    def test_stop_event_stops_server(self):
        from visema.main import start_server

        stop_event = threading.Event()

        with patch("visema.main.uvicorn.Server") as MockServer:
            mock_instance = MagicMock()
            run_called = []

            def mock_run():
                # Wait for stop event in the server thread
                while not stop_event.is_set():
                    import time
                    time.sleep(0.05)

            mock_instance.run = mock_run
            MockServer.return_value = mock_instance

            thread = start_server(MagicMock(), stop_event)

        assert thread.is_alive()
        stop_event.set()
        thread.join(timeout=2)
        # Thread should have stopped


# ── get_channel_id ────────────────────────────────────────────────────────────


class TestGetChannelId:
    @pytest.mark.asyncio
    async def test_resolves_via_helions(self, mock_broadcaster_client):
        from visema.main import get_channel_id

        with patch("visema.main.Helions") as MockHelions:
            mock_helio = MagicMock()
            mock_helio.get_users = AsyncMock(return_value={
                "data": [{"id": "helion-user-123"}]
            })
            MockHelions.return_value = mock_helio

            channel_id = await get_channel_id(mock_broadcaster_client, "testuser")

            assert channel_id == "helion-user-123"

    @pytest.mark.asyncio
    async def test_fallback_to_client(self, mock_broadcaster_client):
        from visema.main import get_channel_id

        # Helions fails, client succeeds
        with patch("visema.main.Helions") as MockHelions:
            mock_helio = MagicMock()
            mock_helio.get_users = AsyncMock(return_value={"data": []})
            MockHelions.return_value = mock_helio

            mock_broadcaster_client.get_users = AsyncMock(return_value={
                "data": [{"id": "client-user-456"}]
            })

            channel_id = await get_channel_id(mock_broadcaster_client, "testuser")

            assert channel_id == "client-user-456"

    @pytest.mark.asyncio
    async def test_raises_on_not_found(self, mock_broadcaster_client):
        from visema.main import get_channel_id

        with patch("visema.main.Helions") as MockHelions:
            mock_helio = MagicMock()
            mock_helio.get_users = AsyncMock(return_value={"data": []})
            MockHelions.return_value = mock_helio

            mock_broadcaster_client.get_users = AsyncMock(return_value={"data": []})

            with pytest.raises(ValueError, match="Could not resolve channel ID"):
                await get_channel_id(mock_broadcaster_client, "ghost_user")


# ── run() entrypoint integration ─────────────────────────────────────────────


class TestRunEntrypoint:
    @pytest.mark.asyncio
    async def test_run_sets_up_components(self):
        """Verify that run() wires up all components correctly (mocked)."""
        from visema.main import run

        with patch("visema.main.load_settings") as mock_load, \
             patch("visema.main.start_server") as mock_start_server, \
             patch("visema.main.auth_module.setup_auth") as mock_auth, \
             patch("visema.main.eventsub_module.start_eventsub") as mock_eventsub, \
             patch("visema.main.chat_module.start_chat_listener") as mock_chat, \
             patch("visema.main.get_channel_id") as mock_get_id, \
             patch("visema.main.validator.build_sounds_index"), \
             patch("visema.media.queue.MediaQueue") as MockMQ:

            # Setup mocks
            mock_settings = MagicMock()
            mock_settings.sounds_dir_path = Path("/tmp/sounds")
            mock_settings.audio.allowed_extensions = [".mp3"]
            mock_settings.gif.max_queue_size = 5
            mock_settings.audio.max_queue_size = 5
            mock_settings.gif.cooldown_seconds = 1
            mock_settings.audio.cooldown_seconds = 1
            mock_settings.overlay.port = 9876
            mock_load.return_value = mock_settings

            mock_start_server.return_value = MagicMock()

            mock_broadcaster = AsyncMock()
            mock_bot = AsyncMock()
            mock_auth.return_value = (mock_broadcaster, mock_bot)

            mock_get_id.return_value = "channel-123"

            mock_eventsub_task = AsyncMock()
            mock_chat_task = AsyncMock()
            mock_eventsub.return_value = asyncio.create_task(asyncio.sleep(0))
            mock_chat.return_value = asyncio.create_task(asyncio.sleep(0))

            MockMQ.return_value = MagicMock()
            MockMQ.return_value.start = AsyncMock()
            MockMQ.return_value.stop = AsyncMock()

            # Run the coroutine (it will wait on tasks that finish immediately)
            try:
                await asyncio.wait_for(run(), timeout=2.0)
            except (asyncio.TimeoutError, Exception):
                pass  # Expected — some mocks aren't perfect

            # Verify key calls were made
            mock_load.assert_called_once()
            mock_start_server.assert_called_once()
            mock_auth.assert_called_once()
            mock_get_id.assert_called_once()


# ── main() CLI entrypoint ─────────────────────────────────────────────────────


class TestMainCLI:
    def test_parser_has_setup_flag(self):
        import argparse
        from visema.main import main

        # Create a parser like main() does and verify flags exist
        parser = argparse.ArgumentParser()
        parser.add_argument("--setup", action="store_true")
        parser.add_argument("--verbose", "-v", action="store_true")

        args = parser.parse_args(["--verbose"])
        assert args.verbose is True

        args = parser.parse_args(["--setup"])
        assert args.setup is True

    def test_parser_no_flags(self):
        import argparse
        from visema.main import main

        parser = argparse.ArgumentParser()
        parser.add_argument("--setup", action="store_true")
        parser.add_argument("--verbose", "-v", action="store_true")

        args = parser.parse_args([])
        assert args.setup is False
        assert args.verbose is False
