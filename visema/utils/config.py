"""
Loads .env and config.yaml, exposes a typed Settings object.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml
from dotenv import load_dotenv

# Resolve paths relative to the project root (parent of visema/ package)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"
_CONFIG_PATH = _PROJECT_ROOT / "config.yaml"


@dataclass
class GifSettings:
    allowed_domains: List[str] = field(default_factory=list)
    display_duration_seconds: int = 8
    cooldown_seconds: int = 3
    max_queue_size: int = 5
    size_percent: int = 40


@dataclass
class AudioSettings:
    sounds_dir: str = "sounds"
    allowed_extensions: List[str] = field(default_factory=lambda: [".mp3", ".ogg", ".wav"])
    volume: float = 1.0
    cooldown_seconds: int = 3
    max_queue_size: int = 5


@dataclass
class OverlaySettings:
    port: int = 9876
    position: str = "center"


@dataclass
class CommandSettings:
    gif_response: str = ""
    sound_response: str = ""
    soundlist_response: str = "auto"


@dataclass
class TwitchSettings:
    target_channel: str = ""
    target_channel_id: str = ""
    bot_channel: str = ""
    reward_gif: str = "Show a GIF"
    reward_sound: str = "Play a Sound"


@dataclass
class Settings:
    twitch: TwitchSettings = field(default_factory=TwitchSettings)
    gif: GifSettings = field(default_factory=GifSettings)
    audio: AudioSettings = field(default_factory=AudioSettings)
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    commands: CommandSettings = field(default_factory=CommandSettings)
    sounds_dir_path: Path = field(default_factory=lambda: _PROJECT_ROOT / "sounds")

    # Twitch credentials from .env
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    broadcaster_access_token: str = ""
    broadcaster_refresh_token: str = ""
    bot_access_token: str = ""
    bot_refresh_token: str = ""


def load_settings() -> Settings:
    """Load .env and config.yaml, return a Settings object."""
    load_dotenv(str(_ENV_PATH))

    settings = Settings()

    # ── Load .env credentials ───────────────────────────
    settings.twitch_client_id = os.getenv("TWITCH_CLIENT_ID", "")
    settings.twitch_client_secret = os.getenv("TWITCH_CLIENT_SECRET", "")
    settings.broadcaster_access_token = os.getenv("BROADCASTER_ACCESS_TOKEN", "")
    settings.broadcaster_refresh_token = os.getenv("BROADCASTER_REFRESH_TOKEN", "")
    settings.bot_access_token = os.getenv("BOT_ACCESS_TOKEN", "")
    settings.bot_refresh_token = os.getenv("BOT_REFRESH_TOKEN", "")

    # ── Load config.yaml ────────────────────────────────
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, "r") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {}

    # Twitch
    if "twitch" in cfg:
        d = cfg["twitch"]
        settings.twitch.target_channel = d.get("target_channel", settings.twitch.target_channel)
        settings.twitch.target_channel_id = d.get("target_channel_id", settings.twitch.target_channel_id)
        settings.twitch.bot_channel = d.get("bot_channel", settings.twitch.bot_channel)
        settings.twitch.reward_gif = d.get("reward_gif", settings.twitch.reward_gif)
        settings.twitch.reward_sound = d.get("reward_sound", settings.twitch.reward_sound)

    # GIF
    if "gif" in cfg:
        d = cfg["gif"]
        settings.gif.allowed_domains = d.get("allowed_domains", settings.gif.allowed_domains)
        settings.gif.display_duration_seconds = d.get("display_duration_seconds", settings.gif.display_duration_seconds)
        settings.gif.cooldown_seconds = d.get("cooldown_seconds", settings.gif.cooldown_seconds)
        settings.gif.max_queue_size = d.get("max_queue_size", settings.gif.max_queue_size)
        settings.gif.size_percent = d.get("size_percent", settings.gif.size_percent)

    # Audio
    if "audio" in cfg:
        d = cfg["audio"]
        settings.audio.sounds_dir = d.get("sounds_dir", settings.audio.sounds_dir)
        settings.audio.allowed_extensions = d.get("allowed_extensions", settings.audio.allowed_extensions)
        settings.audio.volume = d.get("volume", settings.audio.volume)
        settings.audio.cooldown_seconds = d.get("cooldown_seconds", settings.audio.cooldown_seconds)
        settings.audio.max_queue_size = d.get("max_queue_size", settings.audio.max_queue_size)
        settings.sounds_dir_path = _PROJECT_ROOT / settings.audio.sounds_dir

    # Overlay
    if "overlay" in cfg:
        d = cfg["overlay"]
        settings.overlay.port = d.get("port", settings.overlay.port)
        settings.overlay.position = d.get("position", settings.overlay.position)

    # Commands
    if "commands" in cfg:
        d = cfg["commands"]
        settings.commands.gif_response = d.get("gif_response", settings.commands.gif_response)
        settings.commands.sound_response = d.get("sound_response", settings.commands.sound_response)
        settings.commands.soundlist_response = d.get("soundlist_response", settings.commands.soundlist_response)

    return settings
