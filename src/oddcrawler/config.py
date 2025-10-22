"""Top-level configuration loader."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULT_CONFIG_PATH = Path("config/default.yaml")


@lru_cache(maxsize=1)
def load_app_config(path: str | Path | None = None) -> Dict[str, Any]:
    """Load application configuration."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data


__all__ = ["load_app_config", "DEFAULT_CONFIG_PATH"]
