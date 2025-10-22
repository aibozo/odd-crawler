"""Helpers for loading scoring configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULT_SCORING_CONFIG_PATH = Path("config/scoring.yaml")


@lru_cache(maxsize=1)
def load_scoring_config(path: str | Path | None = None) -> Dict[str, Any]:
    """Load scoring configuration from YAML, falling back to defaults."""
    config_path = Path(path) if path else DEFAULT_SCORING_CONFIG_PATH
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    else:
        data = {}

    data.setdefault("weights", {
        "retro_html": 0.25,
        "url_weird": 0.10,
        "semantic": 0.30,
        "anomaly": 0.20,
        "graph": 0.15,
        "bias": 0.0,
    })

    data.setdefault("thresholds", {
        "persist": 0.35,
        "llm_gate": 0.60,
        "alert": 0.80,
    })

    return data


__all__ = ["load_scoring_config", "DEFAULT_SCORING_CONFIG_PATH"]
