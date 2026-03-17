"""File-based caching layer for downloaded data (DA-6).

Simple functions that check if a cached file exists on disk, and if not,
let the caller download and store it. This avoids re-downloading
multi-gigabyte LODES files on repeated runs.

The cache directory defaults to ~/.wfh_perturbation_cache. All functions
accept an optional cache_dir override.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default location for cached downloads
DEFAULT_CACHE_DIR = Path.home() / ".wfh_perturbation_cache"


def _ensure_cache_dir(cache_dir: Optional[str] = None) -> Path:
    """Create the cache directory if it doesn't exist and return its Path."""
    d = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key_to_path(key: str, suffix: str = "", cache_dir: Optional[str] = None) -> Path:
    """Convert a human-readable cache key to a safe filesystem path.

    Long keys are truncated and appended with a short hash to avoid
    filename-length issues while keeping the name partially readable.
    """
    d = _ensure_cache_dir(cache_dir)
    # Replace non-alphanumeric characters with underscores for safety
    safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
    if len(safe_name) > 80:
        h = hashlib.md5(key.encode()).hexdigest()[:12]
        safe_name = safe_name[:60] + "_" + h
    return d / (safe_name + suffix)


def cache_has(key: str, suffix: str = "", cache_dir: Optional[str] = None) -> bool:
    """Check whether a cached file exists for this key."""
    return _key_to_path(key, suffix, cache_dir).exists()


def cache_get_path(key: str, suffix: str = "", cache_dir: Optional[str] = None) -> Optional[Path]:
    """Return the path to a cached file, or None if it hasn't been cached yet."""
    path = _key_to_path(key, suffix, cache_dir)
    return path if path.exists() else None


def cache_put_path(key: str, suffix: str = "", cache_dir: Optional[str] = None) -> Path:
    """Return the path where the caller should write cached data.

    The caller is responsible for actually writing the file to this path.
    """
    return _key_to_path(key, suffix, cache_dir)


def cache_put_bytes(key: str, data: bytes, suffix: str = "", cache_dir: Optional[str] = None) -> Path:
    """Write raw bytes into the cache and return the path."""
    path = _key_to_path(key, suffix, cache_dir)
    path.write_bytes(data)
    logger.debug(f"Cached {len(data)} bytes at {path}")
    return path


def cache_put_json(key: str, data: dict, cache_dir: Optional[str] = None) -> Path:
    """Write a JSON-serializable dict into the cache."""
    path = _key_to_path(key, suffix=".json", cache_dir=cache_dir)
    path.write_text(json.dumps(data))
    return path


def cache_get_json(key: str, cache_dir: Optional[str] = None) -> Optional[dict]:
    """Read a cached JSON dict, or return None if not cached."""
    path = _key_to_path(key, suffix=".json", cache_dir=cache_dir)
    if path.exists():
        return json.loads(path.read_text())
    return None
