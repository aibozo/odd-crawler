"""Helpers for loading storage configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULT_CONFIG_PATH = Path("config/storage.yaml")


@lru_cache(maxsize=1)
def load_storage_config(config_path: str | Path | None = None) -> Dict[str, Any]:
    """Load storage configuration from YAML and cache the result."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Storage configuration not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    data.setdefault("base_dir", "var/oddcrawler")
    base_dir = Path(data["base_dir"])
    if not base_dir.is_absolute():
        base_dir = (path.parent / base_dir).resolve()
    data["base_dir"] = str(base_dir)
    data.setdefault("__config_path__", str(path))
    return data


def resolve_section_path(section: str, config: Dict[str, Any]) -> Path:
    """Resolve an absolute path for a storage section."""
    base_dir = Path(config.get("base_dir", "var/oddcrawler"))

    section_settings = config.get(section, {})
    raw_path = section_settings.get("path") or section
    path = Path(raw_path)
    if not path.is_absolute():
        path = base_dir / path

    return path


__all__ = ["load_storage_config", "resolve_section_path", "DEFAULT_CONFIG_PATH"]
