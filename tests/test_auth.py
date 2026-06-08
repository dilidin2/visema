"""Tests for visema.twitch.auth — OAuth2 helper functions (token I/O)."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── _read_env ─────────────────────────────────────────────────────────────────


class TestReadEnv:
    def test_reads_valid_lines(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "KEY1=value1\n"
            "KEY2=value with spaces\n"
            "KEY3=\n"
        )

        from visema.twitch import auth as auth_module
        monkeypatch_env_path(tmp_path / ".env", auth_module)

        result = auth_module._read_env()

        assert result["KEY1"] == "value1"
        assert result["KEY2"] == "value with spaces"
        assert result["KEY3"] == ""

    def test_skips_comments(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# This is a comment\n"
            "  # Indented comment\n"
            "REAL_KEY=real_value\n"
        )

        from visema.twitch import auth as auth_module
        monkeypatch_env_path(tmp_path / ".env", auth_module)

        result = auth_module._read_env()

        assert "REAL_KEY" in result
        assert "This is a comment" not in str(result)

    def test_skips_empty_lines(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("\n\nKEY=value\n\n")

        from visema.twitch import auth as auth_module
        monkeypatch_env_path(tmp_path / ".env", auth_module)

        result = auth_module._read_env()

        assert len(result) == 1
        assert result["KEY"] == "value"

    def test_handles_missing_file(self, tmp_path):
        non_existent = tmp_path / "does_not_exist.env"

        from visema.twitch import auth as auth_module
        monkeypatch_env_path(non_existent, auth_module)

        result = auth_module._read_env()
        assert result == {}

    def test_handles_equals_in_value(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text('TOKEN=abc123=def456\n')

        from visema.twitch import auth as auth_module
        monkeypatch_env_path(tmp_path / ".env", auth_module)

        result = auth_module._read_env()
        assert result["TOKEN"] == "abc123=def456"


# ── _write_env ────────────────────────────────────────────────────────────────


class TestWriteEnv:
    def test_writes_new_keys(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# existing file\n")

        from visema.twitch import auth as auth_module
        monkeypatch_env_path(tmp_path / ".env", auth_module)

        auth_module._write_env({"NEW_KEY": "new_value"})

        content = env_file.read_text()
        assert "NEW_KEY=new_value" in content

    def test_updates_existing_keys(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY1=old_value\nKEY2=keep_this\n")

        from visema.twitch import auth as auth_module
        monkeypatch_env_path(tmp_path / ".env", auth_module)

        auth_module._write_env({"KEY1": "new_value"})

        content = env_file.read_text()
        assert "KEY1=new_value" in content
        assert "KEY2=keep_this" in content

    def test_preserves_comments(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# My comment\n"
            "KEY=value\n"
            "# Another comment\n"
        )

        from visema.twitch import auth as auth_module
        monkeypatch_env_path(tmp_path / ".env", auth_module)

        auth_module._write_env({"KEY": "updated"})

        content = env_file.read_text()
        assert "# My comment" in content
        assert "# Another comment" in content
        assert "KEY=updated" in content

    def test_appends_missing_keys(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING=val\n")

        from visema.twitch import auth as auth_module
        monkeypatch_env_path(tmp_path / ".env", auth_module)

        auth_module._write_env({"NEW_KEY": "new_val"})

        content = env_file.read_text()
        lines = [l.strip() for l in content.strip().splitlines()]
        assert "EXISTING=val" in lines
        assert "NEW_KEY=new_val" in lines

    def test_writes_empty_string_value(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("")

        from visema.twitch import auth as auth_module
        monkeypatch_env_path(tmp_path / ".env", auth_module)

        auth_module._write_env({"KEY": ""})

        content = env_file.read_text()
        assert "KEY=" in content


# ── Scopes ────────────────────────────────────────────────────────────────────


class TestScopes:
    def test_broadcaster_scopes(self):
        from visema.twitch.auth import BROADCASTER_SCOPES

        assert len(BROADCASTER_SCOPES) == 2
        scopes_str = [str(s) for s in BROADCASTER_SCOPES]
        assert "channel:read:redemptions" in scopes_str
        assert "channel:manage:redemptions" in scopes_str

    def test_bot_scopes(self):
        from visema.twitch.auth import BOT_SCOPES

        assert len(BOT_SCOPES) == 2
        scopes_str = [str(s) for s in BOT_SCOPES]
        assert "chat:edit" in scopes_str
        assert "chat:read" in scopes_str


# ── Token prefix logic ────────────────────────────────────────────────────────


class TestTokenPrefixes:
    def test_broadcaster_prefix(self, tmp_path):
        """Verify BROADCASTER_ prefix writes correct .env keys."""
        env_file = tmp_path / ".env"
        env_file.write_text("")

        from visema.twitch import auth as auth_module
        monkeypatch_env_path(tmp_path / ".env", auth_module)

        auth_module._write_env({
            "BROADCASTER_ACCESS_TOKEN": "tok123",
            "BROADCASTER_REFRESH_TOKEN": "refresh456",
        })

        content = env_file.read_text()
        assert "BROADCASTER_ACCESS_TOKEN=tok123" in content
        assert "BROADCASTER_REFRESH_TOKEN=refresh456" in content

    def test_bot_prefix(self, tmp_path):
        """Verify BOT_ prefix writes correct .env keys."""
        env_file = tmp_path / ".env"
        env_file.write_text("")

        from visema.twitch import auth as auth_module
        monkeypatch_env_path(tmp_path / ".env", auth_module)

        auth_module._write_env({
            "BOT_ACCESS_TOKEN": "tok789",
            "BOT_REFRESH_TOKEN": "refresh012",
        })

        content = env_file.read_text()
        assert "BOT_ACCESS_TOKEN=tok789" in content
        assert "BOT_REFRESH_TOKEN=refresh012" in content


# ── _user_auth_refresh_callback ───────────────────────────────────────────────


class TestRefreshCallback:
    @pytest.mark.asyncio
    async def test_persists_refreshed_tokens(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("")

        from visema.twitch import auth as auth_module
        monkeypatch_env_path(tmp_path / ".env", auth_module)

        await auth_module._user_auth_refresh_callback(
            token="new_access",
            refresh_token="new_refresh",
            token_prefix="BROADCASTER_",
        )

        content = env_file.read_text()
        assert "BROADCASTER_ACCESS_TOKEN=new_access" in content
        assert "BROADCASTER_REFRESH_TOKEN=new_refresh" in content


# ── Helper ────────────────────────────────────────────────────────────────────


def monkeypatch_env_path(env_path, auth_module):
    """Patch the _ENV_PATH on the auth module."""
    auth_module._ENV_PATH = env_path
