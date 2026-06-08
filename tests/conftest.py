"""Shared fixtures for all Visema tests."""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Temp directories & files ──────────────────────────────────────────────────


@pytest.fixture()
def tmp_sounds_dir(tmp_path):
    """Create a temporary sounds directory with sample audio files."""
    files = {
        "vine_boom.mp3": b"fake audio",
        "bruh.mp3": b"fake audio",
        "airhorn.ogg": b"fake audio",
        "sad_trombone.wav": b"fake audio",
        "My_Mixed_Case.Mp3": b"fake audio",
        "ignored.txt": b"not audio",
    }
    for name, content in files.items():
        (tmp_path / name).write_bytes(content)
    return tmp_path


@pytest.fixture()
def minimal_sounds_dir(tmp_path):
    """Create a sounds directory with just one file."""
    (tmp_path / "test.mp3").write_bytes(b"fake audio")
    return tmp_path


# ── Settings fixtures ─────────────────────────────────────────────────────────

@pytest.fixture()
def sample_config():
    """Return a minimal config.yaml dict."""
    return {
        "twitch": {
            "target_channel": "teststreamer",
            "bot_channel": "testbot",
            "reward_gif": "Show a GIF",
            "reward_sound": "Play a Sound",
        },
        "gif": {
            "allowed_domains": [
                "i.giphy.com",
                "media.giphy.com",
                "media0.giphy.com",
                "media1.giphy.com",
                "media2.giphy.com",
                "media3.giphy.com",
                "media4.giphy.com",
            ],
            "display_duration_seconds": 8,
            "cooldown_seconds": 3,
            "max_queue_size": 5,
            "size_percent": 40,
        },
        "audio": {
            "sounds_dir": "sounds",
            "allowed_extensions": [".mp3", ".ogg", ".wav"],
            "volume": 1.0,
            "cooldown_seconds": 3,
            "max_queue_size": 5,
        },
        "overlay": {
            "port": 9876,
            "position": "center",
        },
        "commands": {
            "gif_response": "How to use GIF",
            "sound_response": "How to use sound",
            "soundlist_response": "auto",
        },
    }


@pytest.fixture()
def env_lines():
    """Return a list of .env lines."""
    return [
        "# Twitch credentials\n",
        "TWITCH_CLIENT_ID=my_client_id\n",
        "TWITCH_CLIENT_SECRET=my_secret\n",
        "BROADCASTER_ACCESS_TOKEN=broad_tok_123\n",
        "BROADCASTER_REFRESH_TOKEN=broad_refresh\n",
        "BOT_ACCESS_TOKEN=bot_tok_456\n",
        "BOT_REFRESH_TOKEN=bot_refresh\n",
    ]


# ── Mock Twitch clients ───────────────────────────────────────────────────────

@pytest.fixture()
def mock_broadcaster_client():
    """Create a mock broadcaster Twitch client."""
    client = AsyncMock()
    client.get_channel_points_rewards = AsyncMock(return_value={
        "data": [
            {"id": "gif-reward-id", "title": "Show a GIF"},
            {"id": "sound-reward-id", "title": "Play a Sound"},
        ]
    })
    client.update_channel_points_redemption = AsyncMock(return_value={"success": True})
    return client


@pytest.fixture()
def mock_bot_client():
    """Create a mock bot Twitch client."""
    client = AsyncMock()
    client.send_chat_message = AsyncMock(return_value={"success": True})
    return client


# ── Mock EventSub / Chat listener helpers ─────────────────────────────────────

@pytest.fixture()
def mock_eventsub():
    """Create a mock EventSub WebSocket."""
    eventsub = MagicMock()
    eventsub.listen_channel_points_custom_reward_redemption_add = MagicMock()
    eventsub.start = MagicMock()
    eventsub.connect = AsyncMock()
    return eventsub


# ── Mock WebSocket for server tests ───────────────────────────────────────────

class FakeSocket:
    """Minimal fake WebSocket for testing ws_manager without FastAPI."""

    def __init__(self):
        self.messages_sent = []
        self._closed = False
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_text(self, text):
        if not self._closed:
            self.messages_sent.append(text)

    async def receive_text(self):
        """Return a fake ack message."""
        return json.dumps({"ack": "audio_done"})

    async def close(self):
        self._closed = True


class MockWebSocketManager:
    """Minimal mock that replaces the singleton for queue tests."""

    def __init__(self):
        self.broadcast_calls = []
        self.connections = set()

    async def broadcast(self, payload):
        self.broadcast_calls.append(payload)

    @property
    def connection_count(self):
        return len(self.connections)


@pytest.fixture()
def mock_ws_manager(monkeypatch):
    """Replace the WebSocketManager singleton with a test double."""
    manager = MockWebSocketManager()
    from visema.server import ws_manager as wm_module
    monkeypatch.setattr(wm_module, "_manager", manager)
    return manager


# ── MediaQueue creation helpers ───────────────────────────────────────────────

@pytest.fixture()
def media_queue_with_broadcast(mock_ws_manager):
    """Create a MediaQueue that uses the mock WebSocket manager for broadcasting."""
    from visema.media.queue import MediaQueue
    q = MediaQueue(max_size=3, cooldown_seconds=0.1)
    return q


# ── Async helpers ─────────────────────────────────────────────────────────────

@pytest.fixture()
def event_loop():
    """Create an isolated event loop for each test."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Redemptions fixtures ─────────────────────────────────────────────────────

@pytest.fixture()
def gif_redemption_event():
    """A mock EventSub redemption event for a GIF."""
    return {
        "event": {
            "id": "redemption-001",
            "user": {"id": "user-123", "login": "viewer_one"},
            "channel_points_custom_reward_id": "gif-reward-id",
            "user_input": "https://i.giphy.com/media/abc123/giphy.gif",
        }
    }


@pytest.fixture()
def sound_redemption_event():
    """A mock EventSub redemption event for audio."""
    return {
        "event": {
            "id": "redemption-002",
            "user": {"id": "user-456", "login": "viewer_two"},
            "channel_points_custom_reward_id": "sound-reward-id",
            "user_input": "vine boom",
        }
    }


@pytest.fixture()
def unknown_redemption_event():
    """A redemption event with an unrecognized reward ID."""
    return {
        "event": {
            "id": "redemption-003",
            "user": {"id": "user-789", "login": "viewer_three"},
            "channel_points_custom_reward_id": "unknown-reward-id",
            "user_input": "something",
        }
    }


# ── Chat message mock ────────────────────────────────────────────────────────

@pytest.fixture()
def fake_chat_message():
    """Create a mock twitchAPI chat message object."""
    msg = MagicMock()
    msg.message = "!gif"
    msg.sender = MagicMock()
    msg.sender.name = "testuser"
    return msg


# ── Overlay content fixtures ─────────────────────────────────────────────────

@pytest.fixture()
def overlay_html_content():
    """Return the expected HTML structure for index.html."""
    return {
        "has_doctype": True,
        "has_overlay_container": True,
        "links_css": True,
        "links_js": True,
    }


# ── Helper: reset validator state ────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_validator_state():
    """Reset the global sounds index before and after each test."""
    from visema.media import validator
    validator._sounds_index = {}
    yield
    validator._sounds_index = {}


# ── Helper: reset ws_manager state ───────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_ws_manager_state(monkeypatch):
    """Reset the WebSocketManager singleton before each test."""
    from visema.server import ws_manager as wm_module
    original = wm_module._manager
    wm_module._manager = wm_module.WebSocketManager()
    wm_module._ack_callback = None
    yield
    wm_module._manager = original
    wm_module._ack_callback = None
