"""Local config: remembers the default station so you don't retype it."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "wunderground-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class Config:
    station_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    units: str = "metric"
    language: str = "en-US"


VALID_UNITS = ("metric", "imperial", "hybrid")


class ConfigError(RuntimeError):
    pass


def load() -> Config:
    """Load the config; a missing file gives defaults, a corrupt one raises ConfigError."""
    if not CONFIG_FILE.exists():
        return Config()
    try:
        data = json.loads(CONFIG_FILE.read_text())
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
    except (OSError, ValueError) as exc:
        raise ConfigError(f"Could not read {CONFIG_FILE}: {exc}. Fix or delete the file.") from exc
    known = asdict(Config())
    return Config(**{**known, **{k: v for k, v in data.items() if k in known}})


def save(config: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(asdict(config), indent=2))
