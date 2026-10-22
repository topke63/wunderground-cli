"""Tiny on-disk response cache so repeated commands don't hammer the public proxy."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "wunderground-cli"
TTL_SECONDS = 120

# Flipped by the `--no-cache` flag; WU_NO_CACHE=1 also disables caching.
enabled = not os.environ.get("WU_NO_CACHE")


def _path(path: str, params: dict[str, Any]) -> Path:
    key = json.dumps([path, sorted(params.items())], default=str)
    return CACHE_DIR / (hashlib.sha256(key.encode()).hexdigest() + ".json")


def get(path: str, params: dict[str, Any]) -> Any | None:
    """Return a cached response younger than the TTL, or None."""
    if not enabled:
        return None
    file = _path(path, params)
    try:
        entry = json.loads(file.read_text())
        if time.time() - entry["ts"] < TTL_SECONDS:
            return entry["data"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def put(path: str, params: dict[str, Any], data: Any) -> None:
    if not enabled or data is None:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _path(path, params).write_text(json.dumps({"ts": time.time(), "data": data}))
    except OSError:
        pass  # caching is best-effort


def clear() -> int:
    """Delete all cached responses; returns how many were removed."""
    removed = 0
    for file in CACHE_DIR.glob("*.json") if CACHE_DIR.exists() else []:
        try:
            file.unlink()
            removed += 1
        except OSError:
            pass
    return removed
