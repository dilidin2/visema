"""
GIF URL validation and audio name → file resolution.

On startup, scans the sounds/ directory and builds an in-memory index.
"""

import logging
import re
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# In-memory sounds index: { "vine_boom": Path("sounds/vine_boom.mp3"), ... }
_sounds_index: dict[str, Path] = {}


def build_sounds_index(sounds_dir: Path, allowed_extensions: list[str]) -> dict[str, Path]:
    """Scan the sounds directory and build the lookup index.

    Keys are filenames lowercased with extension stripped.
    """
    global _sounds_index
    _sounds_index = {}

    if not sounds_dir.exists():
        logger.warning("Sounds directory does not exist: %s", sounds_dir)
        return _sounds_index

    for file in sounds_dir.iterdir():
        if file.is_file() and file.suffix.lower() in allowed_extensions:
            key = file.stem.lower()
            _sounds_index[key] = file
            logger.debug("Indexed sound: %s → %s", key, file)

    logger.info("Built sounds index with %d entries", len(_sounds_index))
    return _sounds_index


def get_sounds_index() -> dict[str, Path]:
    """Return the current sounds index (read-only view)."""
    return dict(_sounds_index)


def get_sound_names() -> list[str]:
    """Return sorted list of available sound names."""
    return sorted(_sounds_index.keys())


def validate_gif(url: str, allowed_domains: list[str]) -> str | None:
    """Validate a GIF URL against allowed Giphy CDN domains.

    Returns the URL unchanged if valid, None otherwise.
    Rejects bare 'giphy.com' (page URLs).
    """
    if not url or not isinstance(url, str):
        return None

    url = url.strip()

    try:
        parsed = urlparse(url)
    except Exception:
        logger.warning("Invalid URL: %s", url)
        return None

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname

    if scheme not in ("http", "https"):
        logger.warning("GIF URL missing http/https scheme: %s", url)
        return None

    if not hostname:
        logger.warning("GIF URL has no hostname: %s", url)
        return None

    hostname_lower = hostname.lower()

    # Reject bare giphy.com (page URL, not a direct link)
    if hostname_lower == "giphy.com":
        logger.warning("Rejected bare giphy.com page URL: %s", url)
        return None

    # Check against allowed domains
    if hostname_lower not in allowed_domains:
        logger.warning("GIF URL domain not allowed: %s (%s)", hostname_lower, url)
        return None

    return url


def validate_audio(name: str) -> Path | None:
    """Normalise a sound name and look it up in the sounds index.

    Normalisation: lowercase → strip punctuation → replace spaces with underscores.
    Returns the resolved Path if found, None otherwise.
    """
    if not name or not isinstance(name, str):
        return None

    # Normalise: lowercase, strip leading/trailing whitespace
    key = name.strip().lower()

    # Strip punctuation (keep alphanumeric, underscores, spaces)
    key = re.sub(r"[^a-z0-9_ ]", "", key)

    # Replace spaces with underscores, collapse multiple underscores
    key = re.sub(r"\s+", "_", key)
    key = re.sub(r"_+", "_", key)

    if not key:
        return None

    return _sounds_index.get(key)
