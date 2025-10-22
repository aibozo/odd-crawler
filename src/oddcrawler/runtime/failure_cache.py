"""Persistent cache for failed URLs that should be skipped."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, Set


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FailureEntry:
    url: str
    status: Optional[int]
    reason: str
    first_recorded_at: str
    last_recorded_at: str
    count: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "url": self.url,
            "status": self.status,
            "reason": self.reason,
            "first_recorded_at": self.first_recorded_at,
            "last_recorded_at": self.last_recorded_at,
            "count": self.count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "FailureEntry":
        return cls(
            url=str(data.get("url", "")),
            status=int(data["status"]) if data.get("status") is not None else None,
            reason=str(data.get("reason", "")),
            first_recorded_at=str(data.get("first_recorded_at", _utc_now())),
            last_recorded_at=str(data.get("last_recorded_at", _utc_now())),
            count=int(data.get("count", 1)),
        )


class FailureCache:
    """Caches hard failures (e.g., HTTP 404) to avoid re-crawling them."""

    def __init__(
        self,
        path: Path | str,
        *,
        skip_statuses: Optional[Set[int]] = None,
        expiry_seconds: Optional[int] = 7 * 24 * 60 * 60,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.skip_statuses = set(skip_statuses or {404})
        self.expiry_seconds = expiry_seconds
        self._entries: Dict[str, FailureEntry] = {}
        self._dirty = False
        self._load()

    def should_skip(self, url: str) -> bool:
        entry = self._entries.get(url)
        if not entry:
            return False
        if self._expired(entry):
            self._entries.pop(url, None)
            self._dirty = True
            return False
        if entry.status is None:
            return False
        return entry.status in self.skip_statuses

    def record(self, url: str, status: Optional[int], reason: str) -> None:
        now = _utc_now()
        entry = self._entries.get(url)
        if entry is None:
            entry = FailureEntry(
                url=url,
                status=status,
                reason=reason,
                first_recorded_at=now,
                last_recorded_at=now,
                count=1,
            )
        else:
            entry.status = status
            entry.reason = reason
            entry.last_recorded_at = now
            entry.count += 1
        self._entries[url] = entry
        self._dirty = True

    def entries(self) -> Dict[str, FailureEntry]:
        return dict(self._entries)

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._entries)

    def save(self) -> None:
        self.cleanup()
        if not self._dirty:
            return
        payload = [entry.to_dict() for entry in self._entries.values()]
        tmp_path = self.path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        tmp_path.replace(self.path)
        self._dirty = False

    def cleanup(self) -> None:
        if self.expiry_seconds is None:
            return
        expired = [url for url, entry in self._entries.items() if self._expired(entry)]
        if expired:
            for url in expired:
                self._entries.pop(url, None)
            self._dirty = True

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError):
            data = []
        for item in data or []:
            if not isinstance(item, dict):
                continue
            entry = FailureEntry.from_dict(item)
            if entry.url and not self._expired(entry):
                self._entries[entry.url] = entry

    def _expired(self, entry: FailureEntry) -> bool:
        if self.expiry_seconds is None:
            return False
        try:
            last_seen = datetime.fromisoformat(entry.last_recorded_at)
        except ValueError:
            return True
        expire_at = last_seen + timedelta(seconds=self.expiry_seconds)
        return expire_at < datetime.now(timezone.utc)


__all__ = ["FailureCache", "FailureEntry"]
