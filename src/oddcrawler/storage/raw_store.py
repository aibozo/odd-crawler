"""Storage helpers for raw responses and excerpt observations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .config import load_storage_config, resolve_section_path


@dataclass(frozen=True)
class RawWriteResult:
    html_path: Path
    meta_path: Path


def _ensure_timestamp(value: Optional[str] = None) -> datetime:
    """Parse an ISO timestamp or return now."""
    if value:
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(tz=timezone.utc)


def _format_prefix(ts: datetime) -> str:
    return ts.strftime("%Y%m%dT%H%M%S")


def write_raw_response(
    url_hash: str,
    *,
    content: bytes,
    headers: Mapping[str, Any],
    fetched_at: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[RawWriteResult]:
    """Write raw HTML content and accompanying metadata to disk."""
    config_data = config or load_storage_config()
    raw_cfg = config_data.get("raw_html", {})
    if not raw_cfg.get("enabled", False):
        return None

    dest_dir = resolve_section_path("raw_html", config_data)
    dest_dir.mkdir(parents=True, exist_ok=True)

    timestamp = _ensure_timestamp(fetched_at)
    prefix = _format_prefix(timestamp)
    shard_dir = dest_dir / url_hash[:2]
    shard_dir.mkdir(parents=True, exist_ok=True)

    html_path = shard_dir / f"{prefix}_{url_hash}.html"
    meta_path = shard_dir / f"{prefix}_{url_hash}.json"

    html_path.write_bytes(content)

    metadata = {
        "url_hash": url_hash,
        "fetched_at": timestamp.isoformat(),
        "headers": dict(headers),
    }
    with meta_path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False)

    return RawWriteResult(html_path=html_path, meta_path=meta_path)


def write_observation_excerpt(
    observation: Mapping[str, Any],
    *,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[Path]:
    """Persist a redacted observation record, enforcing excerpt length."""
    config_data = config or load_storage_config()
    excerpt_cfg = config_data.get("excerpts", {})
    if not excerpt_cfg.get("enabled", True):
        return None

    max_chars = int(excerpt_cfg.get("max_chars", 5000))
    dest_dir = resolve_section_path("excerpts", config_data)
    dest_dir.mkdir(parents=True, exist_ok=True)

    timestamp = _ensure_timestamp(str(observation.get("fetched_at")))
    prefix = _format_prefix(timestamp)
    url_hash = _derive_url_hash(observation)
    record_path = dest_dir / f"{prefix}_{url_hash}.json"

    sanitized = _sanitize_observation(observation, max_chars=max_chars)
    with record_path.open("w", encoding="utf-8") as handle:
        json.dump(sanitized, handle, ensure_ascii=False)

    return record_path


def _sanitize_observation(observation: Mapping[str, Any], *, max_chars: int) -> Dict[str, Any]:
    allowed_copy = {
        key: value
        for key, value in observation.items()
        if key not in {"raw_html", "content", "raw_content", "html"}
    }

    extract = allowed_copy.get("extract")
    if isinstance(extract, Mapping):
        text = extract.get("text_excerpt")
        if isinstance(text, str):
            extract = dict(extract)
            extract["text_excerpt"] = text[:max_chars]
            allowed_copy["extract"] = extract

    return dict(allowed_copy)


def _derive_url_hash(observation: Mapping[str, Any]) -> str:
    hashes = observation.get("hashes")
    if isinstance(hashes, Mapping):
        for key in ("url_sha256", "url_sha1", "url_md5"):
            val = hashes.get(key)
            if isinstance(val, str) and val:
                return val
    url = observation.get("url", "unknown")
    if not isinstance(url, str):
        url = str(url)
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


__all__ = ["write_raw_response", "write_observation_excerpt", "RawWriteResult"]
