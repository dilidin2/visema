"""Tests for visema.media.validator."""

import tempfile
from pathlib import Path

import pytest

from visema.media import validator


# ── GIF Validation ──────────────────────────────────────

ALLOWED_DOMAINS = [
    "i.giphy.com",
    "media.giphy.com",
    "media0.giphy.com",
    "media1.giphy.com",
    "media2.giphy.com",
    "media3.giphy.com",
    "media4.giphy.com",
]


class TestValidateGif:
    def test_valid_i_giphy_url(self):
        url = "https://i.giphy.com/media/abc123/giphy.gif"
        assert validator.validate_gif(url, ALLOWED_DOMAINS) == url

    def test_valid_media_giphy_url(self):
        url = "https://media.giphy.com/media/xyz789/giphy.gif"
        assert validator.validate_gif(url, ALLOWED_DOMAINS) == url

    def test_valid_numbered_cdn(self):
        url = "https://media3.giphy.com/media/test123/giphy.gif"
        assert validator.validate_gif(url, ALLOWED_DOMAINS) == url

    def test_rejects_bare_giphy_com(self):
        url = "https://giphy.com/gifs/test-abc123"
        assert validator.validate_gif(url, ALLOWED_DOMAINS) is None

    def test_rejects_unknown_domain(self):
        url = "https://example.com/image.gif"
        assert validator.validate_gif(url, ALLOWED_DOMAINS) is None

    def test_rejects_no_scheme(self):
        url = "i.giphy.com/media/abc123/giphy.gif"
        assert validator.validate_gif(url, ALLOWED_DOMAINS) is None

    def test_rejects_empty_string(self):
        assert validator.validate_gif("", ALLOWED_DOMAINS) is None

    def test_rejects_none(self):
        assert validator.validate_gif(None, ALLOWED_DOMAINS) is None

    def test_strips_whitespace(self):
        url = "  https://i.giphy.com/media/abc123/giphy.gif  "
        result = validator.validate_gif(url, ALLOWED_DOMAINS)
        assert result == "https://i.giphy.com/media/abc123/giphy.gif"


# ── Audio Validation ────────────────────────────────────

class TestValidateAudio:
    @pytest.fixture(autouse=True)
    def setup_sounds_index(self, tmp_path):
        """Create a temporary sounds directory with test files."""
        # Create test sound files
        (tmp_path / "vine_boom.mp3").touch()
        (tmp_path / "bruh.mp3").touch()
        (tmp_path / "airhorn.ogg").touch()
        (tmp_path / "sad_trombone.wav").touch()
        (tmp_path / "My_Mixed_Case.Mp3").touch()

        validator.build_sounds_index(tmp_path, [".mp3", ".ogg", ".wav"])

    def test_exact_match(self):
        result = validator.validate_audio("vine_boom")
        assert result is not None
        assert result.name == "vine_boom.mp3"

    def test_spaces_to_underscores(self):
        result = validator.validate_audio("vine boom")
        assert result is not None
        assert result.name == "vine_boom.mp3"

    def test_case_insensitive(self):
        result = validator.validate_audio("VINE_BOOM")
        assert result is not None
        assert result.name == "vine_boom.mp3"

    def test_mixed_case_with_spaces(self):
        result = validator.validate_audio("Vine Boom")
        assert result is not None
        assert result.name == "vine_boom.mp3"

    def test_strips_punctuation(self):
        result = validator.validate_audio("vine_boom!!!")
        assert result is not None
        assert result.name == "vine_boom.mp3"

    def test_not_found(self):
        result = validator.validate_audio("nonexistent_sound")
        assert result is None

    def test_empty_string(self):
        result = validator.validate_audio("")
        assert result is None

    def test_none_input(self):
        result = validator.validate_audio(None)
        assert result is None

    def test_get_sound_names(self):
        names = validator.get_sound_names()
        assert "vine_boom" in names
        assert "bruh" in names
        assert "airhorn" in names
        assert "sad_trombone" in names
        assert "my_mixed_case" in names
        assert names == sorted(names)  # Should be sorted

    def test_get_sounds_index(self):
        index = validator.get_sounds_index()
        assert isinstance(index, dict)
        assert len(index) > 0
