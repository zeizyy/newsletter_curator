from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml

import main


def deep_merge(base: dict, override: dict) -> dict:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def write_temp_config(tmp_path: Path, overrides: dict | None = None) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config = deep_merge(main.DEFAULT_CONFIG, overrides or {})
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path


def temp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_repository.sqlite3"
