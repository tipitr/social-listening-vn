"""Single source of truth for reading YAML config files.

Every scraper used to carry its own copy of this. Now they all import
from here so we read one file in one place.
"""

from pathlib import Path

import yaml

_CONFIG_DIR = Path(__file__).parent.parent / "config"


def _load(name: str) -> dict:
    with open(_CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_keywords() -> dict:
    return _load("keywords.yaml")


def load_sources() -> dict:
    return _load("sources.yaml")


def load_settings() -> dict:
    return _load("settings.yaml")


def load_banks() -> dict:
    return _load("banks.yaml")
