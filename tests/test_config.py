"""Tests for visema.utils.config — Settings loading from .env + config.yaml."""

import os
from pathlib import Path

import pytest
import yaml

from visema.utils.config import (
    AudioSettings,
    CommandSettings,
    GifSettings,
    OverlaySettings,
    Settings,
    TwitchSettings,
    load_settings,
)


# ── Dataclass defaults ────────────────────────────────────────────────────────


class TestGifSettings:
    def test_default_values(self):
        s = GifSettings()
        assert s.allowed_domains == []
        assert s.display_duration_seconds == 8
        assert s.cooldown_seconds == 3
        assert s.max_queue_size == 5
        assert s.size_percent == 40

    def test_custom_values(self):
        s = GifSettings(
            allowed_domains=["i.giphy.com"],
            display_duration_seconds=10,
            cooldown_seconds=5,
            max_queue_size=10,
            size_percent=60,
        )
        assert s.allowed_domains == ["i.giphy.com"]
        assert s.display_duration_seconds == 10
        assert s.cooldown_seconds == 5
        assert s.max_queue_size == 10
        assert s.size_percent == 60


class TestAudioSettings:
    def test_default_values(self):
        s = AudioSettings()
        assert s.sounds_dir == "sounds"
        assert s.allowed_extensions == [".mp3", ".ogg", ".wav"]
        assert s.volume == 1.0
        assert s.cooldown_seconds == 3
        assert s.max_queue_size == 5

    def test_custom_volume(self):
        s = AudioSettings(volume=0.5)
        assert s.volume == 0.5


class TestOverlaySettings:
    def test_default_values(self):
        s = OverlaySettings()
        assert s.port == 9876
        assert s.position == "center"

    def test_custom_port(self):
        s = OverlaySettings(port=8080)
        assert s.port == 8080


class TestCommandSettings:
    def test_default_values(self):
        s = CommandSettings()
        assert s.gif_response == ""
        assert s.sound_response == ""
        assert s.soundlist_response == "auto"

    def test_custom_strings(self):
        s = CommandSettings(
            gif_response="Custom GIF help",
            sound_response="Custom sound help",
            soundlist_response="Predefined list",
        )
        assert s.gif_response == "Custom GIF help"
        assert s.soundlist_response == "Predefined list"


class TestTwitchSettings:
    def test_default_values(self):
        s = TwitchSettings()
        assert s.target_channel == ""
        assert s.bot_channel == ""
        assert s.reward_gif == "Show a GIF"
        assert s.reward_sound == "Play a Sound"


class TestSettings:
    def test_defaults(self):
        s = Settings()
        assert isinstance(s.twitch, TwitchSettings)
        assert isinstance(s.gif, GifSettings)
        assert isinstance(s.audio, AudioSettings)
        assert isinstance(s.overlay, OverlaySettings)
        assert isinstance(s.commands, CommandSettings)
        assert isinstance(s.sounds_dir_path, Path)

    def test_nested_fields(self):
        s = Settings(
            twitch=TwitchSettings(target_channel="mychannel"),
            gif=GifSettings(display_duration_seconds=15),
        )
        assert s.twitch.target_channel == "mychannel"
        assert s.gif.display_duration_seconds == 15


# ── load_settings() — .env loading ───────────────────────────────────────────


class TestLoadSettingsEnv:
    def test_reads_twitch_credentials(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "TWITCH_CLIENT_ID=test_id\n"
            "TWITCH_CLIENT_SECRET=test_secret\n"
            "BROADCASTER_ACCESS_TOKEN=btok\n"
            "BROADCASTER_REFRESH_TOKEN=brefresh\n"
            "BOT_ACCESS_TOKEN=btok2\n"
            "BOT_REFRESH_TOKEN=brefresh2\n"
        )

        with monkeypatch.context() as m:
            from visema.utils import config as cfg_module
            original_root = cfg_module._PROJECT_ROOT
            original_env = cfg_module._ENV_PATH
            m.setattr(cfg_module, "_PROJECT_ROOT", tmp_path)
            m.setattr(cfg_module, "_ENV_PATH", env_file)

            settings = load_settings()

        assert settings.twitch_client_id == "test_id"
        assert settings.twitch_client_secret == "test_secret"
        assert settings.broadcaster_access_token == "btok"
        assert settings.broadcaster_refresh_token == "brefresh"
        assert settings.bot_access_token == "btok2"
        assert settings.bot_refresh_token == "brefresh2"

    def test_missing_env_file(self, tmp_path, monkeypatch):
        non_existent = tmp_path / "nonexistent.env"

        with monkeypatch.context() as m:
            from visema.utils import config as cfg_module
            m.setattr(cfg_module, "_PROJECT_ROOT", tmp_path)
            m.setattr(cfg_module, "_ENV_PATH", non_existent)

            settings = load_settings()

        assert settings.twitch_client_id == ""
        assert settings.twitch_client_secret == ""
        assert settings.broadcaster_access_token == ""

    def test_empty_env_file(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("# only comments\n# nothing else\n")

        with monkeypatch.context() as m:
            from visema.utils import config as cfg_module
            m.setattr(cfg_module, "_PROJECT_ROOT", tmp_path)
            m.setattr(cfg_module, "_ENV_PATH", env_file)

            settings = load_settings()

        assert settings.twitch_client_id == ""


# ── load_settings() — config.yaml loading ─────────────────────────────────────


class TestLoadSettingsYaml:
    def test_reads_config_yaml(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.yaml"
        config_data = {
            "twitch": {
                "target_channel": "streamer1",
                "bot_channel": "botuser",
                "reward_gif": "Show a GIF",
                "reward_sound": "Play a Sound",
            },
            "gif": {
                "allowed_domains": ["i.giphy.com"],
                "display_duration_seconds": 12,
                "cooldown_seconds": 5,
                "max_queue_size": 8,
                "size_percent": 30,
            },
            "audio": {
                "sounds_dir": "my_sounds",
                "allowed_extensions": [".mp3"],
                "volume": 0.75,
                "cooldown_seconds": 2,
                "max_queue_size": 6,
            },
            "overlay": {
                "port": 8080,
                "position": "bottom-left",
            },
            "commands": {
                "gif_response": "Custom GIF instructions",
                "sound_response": "Custom sound instructions",
                "soundlist_response": "Predefined",
            },
        }
        config_file.write_text(yaml.dump(config_data))

        with monkeypatch.context() as m:
            from visema.utils import config as cfg_module
            m.setattr(cfg_module, "_PROJECT_ROOT", tmp_path)
            m.setattr(cfg_module, "_CONFIG_PATH", config_file)

            settings = load_settings()

        # Twitch
        assert settings.twitch.target_channel == "streamer1"
        assert settings.twitch.bot_channel == "botuser"

        # GIF
        assert settings.gif.allowed_domains == ["i.giphy.com"]
        assert settings.gif.display_duration_seconds == 12
        assert settings.gif.cooldown_seconds == 5
        assert settings.gif.max_queue_size == 8
        assert settings.gif.size_percent == 30

        # Audio
        assert settings.audio.sounds_dir == "my_sounds"
        assert settings.audio.allowed_extensions == [".mp3"]
        assert settings.audio.volume == 0.75
        assert settings.audio.cooldown_seconds == 2
        assert settings.audio.max_queue_size == 6
        assert settings.sounds_dir_path == tmp_path / "my_sounds"

        # Overlay
        assert settings.overlay.port == 8080
        assert settings.overlay.position == "bottom-left"

        # Commands
        assert settings.commands.gif_response == "Custom GIF instructions"
        assert settings.commands.soundlist_response == "Predefined"


class TestLoadSettingsMissingYaml:
    def test_missing_config_file(self, tmp_path, monkeypatch):
        non_existent = tmp_path / "no_config.yaml"

        with monkeypatch.context() as m:
            from visema.utils import config as cfg_module
            m.setattr(cfg_module, "_PROJECT_ROOT", tmp_path)
            m.setattr(cfg_module, "_CONFIG_PATH", non_existent)

            settings = load_settings()

        # Should use defaults
        assert settings.twitch.target_channel == ""
        assert settings.gif.display_duration_seconds == 8
        assert settings.overlay.port == 9876


class TestLoadSettingsPartialYaml:
    def test_partial_config_uses_defaults_for_missing_keys(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.yaml"
        # Only override a subset of settings
        config_data = {
            "overlay": {"port": 5000},
        }
        config_file.write_text(yaml.dump(config_data))

        with monkeypatch.context() as m:
            from visema.utils import config as cfg_module
            m.setattr(cfg_module, "_PROJECT_ROOT", tmp_path)
            m.setattr(cfg_module, "_CONFIG_PATH", config_file)

            settings = load_settings()

        assert settings.overlay.port == 5000
        # Everything else should use defaults
        assert settings.twitch.target_channel == ""
        assert settings.gif.display_duration_seconds == 8
        assert settings.audio.volume == 1.0


class TestLoadSettingsEmptyYaml:
    def test_empty_yaml(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")

        with monkeypatch.context() as m:
            from visema.utils import config as cfg_module
            m.setattr(cfg_module, "_PROJECT_ROOT", tmp_path)
            m.setattr(cfg_module, "_CONFIG_PATH", config_file)

            settings = load_settings()

        assert settings.overlay.port == 9876


# ── Combined .env + config.yaml ───────────────────────────────────────────────


class TestLoadSettingsCombined:
    def test_env_and_yaml_merged(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("TWITCH_CLIENT_ID=from_env\n")

        config_file = tmp_path / "config.yaml"
        config_data = {
            "twitch": {"target_channel": "from_yaml"},
            "overlay": {"port": 5555},
        }
        config_file.write_text(yaml.dump(config_data))

        with monkeypatch.context() as m:
            from visema.utils import config as cfg_module
            m.setattr(cfg_module, "_PROJECT_ROOT", tmp_path)
            m.setattr(cfg_module, "_ENV_PATH", env_file)
            m.setattr(cfg_module, "_CONFIG_PATH", config_file)

            settings = load_settings()

        # Credentials come from .env
        assert settings.twitch_client_id == "from_env"
        # Config comes from yaml
        assert settings.twitch.target_channel == "from_yaml"
        assert settings.overlay.port == 5555


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestSettingsEdgeCases:
    def test_project_root_resolution(self):
        """Verify _PROJECT_ROOT resolves to the parent of the visema/ package."""
        from visema.utils import config as cfg_module
        # Project root should be one level above visema/utils/
        assert cfg_module._PROJECT_ROOT.name == "visema"

    def test_sounds_dir_path_updates(self, tmp_path, monkeypatch):
        """Verify sounds_dir_path updates when audio.sounds_dir changes in config."""
        config_file = tmp_path / "config.yaml"
        config_data = {
            "audio": {"sounds_dir": "custom_sounds"},
        }
        config_file.write_text(yaml.dump(config_data))

        with monkeypatch.context() as m:
            from visema.utils import config as cfg_module
            m.setattr(cfg_module, "_PROJECT_ROOT", tmp_path)
            m.setattr(cfg_module, "_CONFIG_PATH", config_file)

            settings = load_settings()

        assert settings.sounds_dir_path == tmp_path / "custom_sounds"

    def test_invalid_yaml(self, tmp_path, monkeypatch):
        """Handle malformed YAML gracefully."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("invalid: yaml: [broken")

        with monkeypatch.context() as m:
            from visema.utils import config as cfg_module
            m.setattr(cfg_module, "_PROJECT_ROOT", tmp_path)
            m.setattr(cfg_module, "_CONFIG_PATH", config_file)

            # Should not crash — falls back to empty dict
            settings = load_settings()

        assert settings.overlay.port == 9876  # default
