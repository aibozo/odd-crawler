"""Compliance helpers for dangerous-content breadcrumbs.

This module defines data structures and helpers for the dangerous-content
breadcrumb flow described in docs/data-governance.md and docs/dataspec.md.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Literal, Mapping, Optional

from .config import load_storage_config, resolve_section_path

DangerousCategory = Literal["self-harm", "illegal-trade", "adult", "extremist", "violent", "other"]


@dataclass
class DangerousBreadcrumb:
    """Structured representation of a dangerous-content breadcrumb."""

    url_hash: str
    observed_at: datetime
    category: DangerousCategory
    reason: str
    source: str
    salt_version: str
    excerpt_redacted: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["observed_at"] = self.observed_at.isoformat()
        return data


def validate_breadcrumb(breadcrumb: DangerousBreadcrumb, max_excerpt_chars: int = 200) -> None:
    """Perform validation before persistence."""
    if not breadcrumb.url_hash:
        raise ValueError("url_hash must be non-empty")

    if breadcrumb.excerpt_redacted and len(breadcrumb.excerpt_redacted) > max_excerpt_chars:
        raise ValueError(f"excerpt_redacted must be <= {max_excerpt_chars} characters")

    if breadcrumb.observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")


def _parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=timezone.utc)
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.now(tz=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _truncate_excerpt(excerpt: str | None, max_chars: int) -> Optional[str]:
    if not excerpt:
        return None
    excerpt = excerpt.strip()
    return excerpt[:max_chars]


def _derive_url_hash(observation: Mapping[str, Any], fallback_url: str) -> str:
    hashes = observation.get("hashes") if isinstance(observation, Mapping) else None
    if isinstance(hashes, Mapping):
        for key in ("url_sha256", "url_sha1", "url_md5"):
            hashed = hashes.get(key)
            if isinstance(hashed, str) and hashed:
                return hashed
    return hashlib.sha256(fallback_url.encode("utf-8")).hexdigest()


def _build_reason(notes: str | None, why_flagged: Iterable[str]) -> str:
    if notes:
        return notes.strip()
    reasons = [item.strip() for item in why_flagged if item.strip()]
    return "; ".join(reasons)[:300] if reasons else "dangerous-content"


def maybe_record_breadcrumb(
    finding: Mapping[str, Any],
    *,
    observation: Optional[Mapping[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[DangerousBreadcrumb]:
    """Create and persist a breadcrumb if the Analyst flagged dangerous content."""
    dangerous_content = finding.get("dangerous_content") if isinstance(finding, Mapping) else None
    if not isinstance(dangerous_content, Mapping):
        return None
    if not dangerous_content.get("present"):
        return None

    config_data = config or load_storage_config()
    compliance_cfg = config_data.get("dangerous_breadcrumbs", {})
    if not compliance_cfg.get("enabled", False):
        return None

    max_excerpt_chars = int(compliance_cfg.get("max_excerpt_chars", 200))
    salt_version = None

    if isinstance(observation, Mapping):
        salt_version = observation.get("salt_version")
    if not salt_version:
        salt_version = config_data.get("salt_rotation", {}).get("active_version", "unknown")

    url = finding.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError("Finding must include a non-empty 'url'")

    observation_ts = None
    excerpt = None
    if isinstance(observation, Mapping):
        observation_ts = observation.get("fetched_at") or observation.get("observed_at")
        extract_section = observation.get("extract")
        if isinstance(extract_section, Mapping):
            excerpt = extract_section.get("text_excerpt")

    observed_at = _parse_timestamp(observation_ts)
    excerpt_redacted = _truncate_excerpt(excerpt, max_excerpt_chars)
    reason = _build_reason(dangerous_content.get("notes"), finding.get("why_flagged", []))
    url_hash = _derive_url_hash(observation or {}, url)

    breadcrumb = DangerousBreadcrumb(
        url_hash=url_hash,
        observed_at=observed_at,
        category=_normalize_category(dangerous_content.get("category")),
        reason=reason,
        source="analyst",
        salt_version=salt_version,
        excerpt_redacted=excerpt_redacted,
    )

    validate_breadcrumb(breadcrumb, max_excerpt_chars=max_excerpt_chars)
    persist_breadcrumb(breadcrumb, config_data)
    return breadcrumb


def _normalize_category(value: Any) -> DangerousCategory:
    allowed: tuple[DangerousCategory, ...] = (
        "self-harm",
        "illegal-trade",
        "adult",
        "extremist",
        "violent",
        "other",
    )
    if value in allowed:
        return value  # type: ignore[return-value]
    return "other"


def persist_breadcrumb(breadcrumb: DangerousBreadcrumb, config: Optional[Dict[str, Any]] = None) -> Path:
    """Persist the breadcrumb using the configured sink."""
    config_data = config or load_storage_config()
    compliance_cfg = config_data.get("dangerous_breadcrumbs", {})
    if not compliance_cfg.get("enabled", False):
        return Path()

    sink = compliance_cfg.get("sink", "local")
    if sink != "local":
        raise NotImplementedError(f"Unsupported breadcrumb sink: {sink}")

    max_excerpt_chars = int(compliance_cfg.get("max_excerpt_chars", 200))
    validate_breadcrumb(breadcrumb, max_excerpt_chars=max_excerpt_chars)

    destination_dir = resolve_section_path("dangerous_breadcrumbs", config_data)
    destination_dir.mkdir(parents=True, exist_ok=True)

    file_path = destination_dir / f"{breadcrumb.observed_at.date().isoformat()}.jsonl"
    record = breadcrumb.to_dict()

    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False))
        handle.write("\n")

    return file_path


__all__ = [
    "DangerousBreadcrumb",
    "maybe_record_breadcrumb",
    "persist_breadcrumb",
    "validate_breadcrumb",
]
