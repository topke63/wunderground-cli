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


def load() -> Config:
    if not CONFIG_FILE.exists():
        return Config()
    data = json.loads(CONFIG_FILE.read_text())
    return Config(**{**asdict(Config()), **data})


def save(config: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(asdict(config), indent=2))
