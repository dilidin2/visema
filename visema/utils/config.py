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

# Public Visema app — override via TWITCH_CLIENT_ID in .env for forks
DEFAULT_CLIENT_ID = "fdf2c1k8jj7j6nfctiyo2ijavckiv5"


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
    reward_gif: str = "Mostra una GIF"
    reward_sound: str = "Suona Suono"
    reward_gif_cost: int = 500
    reward_sound_cost: int = 300


@dataclass
class Settings:
    twitch: TwitchSettings = field(default_factory=TwitchSettings)
    gif: GifSettings = field(default_factory=GifSettings)
    audio: AudioSettings = field(default_factory=AudioSettings)
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    commands: CommandSettings = field(default_factory=CommandSettings)
    sounds_dir_path: Path = field(default_factory=lambda: _PROJECT_ROOT / "sounds")

    # From .env
    twitch_client_id: str = DEFAULT_CLIENT_ID


def load_settings() -> Settings:
    """Load .env and config.yaml, return a Settings object."""
    load_dotenv(str(_ENV_PATH))

    settings = Settings()

    # ── Load .env values ────────────────────────────────
    settings.twitch_client_id = os.getenv("TWITCH_CLIENT_ID", DEFAULT_CLIENT_ID)

    # ── Load config.yaml ────────────────────────────────
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, "r") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {}

    # Twitch
    if "twitch" in cfg:
        d = cfg["twitch"]
        settings.twitch.reward_gif = d.get("reward_gif", settings.twitch.reward_gif)
        settings.twitch.reward_sound = d.get("reward_sound", settings.twitch.reward_sound)
        settings.twitch.reward_gif_cost = d.get("reward_gif_cost", settings.twitch.reward_gif_cost)
        settings.twitch.reward_sound_cost = d.get("reward_sound_cost", settings.twitch.reward_sound_cost)

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
