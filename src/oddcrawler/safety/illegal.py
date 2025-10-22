"""Keyword-based illegal content guardrails."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence


@dataclass
class IllegalDetection:
    illegal: bool
    reason: str
    matches: Sequence[str]


class IllegalContentDetector:
    """Simple keyword-powered detector to keep obviously illegal material out of storage."""

    def __init__(self, config: Optional[Mapping[str, object]] = None) -> None:
        safety_cfg: Mapping[str, object] = config or {}
        illegal_cfg = safety_cfg.get("illegal_content") if isinstance(safety_cfg, Mapping) else {}

        keywords: Iterable[str] = ()
        if isinstance(illegal_cfg, Mapping):
            kw = illegal_cfg.get("keywords", [])
            if isinstance(kw, (list, tuple, set)):
                keywords = [str(item).strip().lower() for item in kw if str(item).strip()]
        self.keywords = tuple(sorted(set(keywords)))

        self.min_matches = 1
        if isinstance(illegal_cfg, Mapping):
            min_matches = illegal_cfg.get("min_keyword_matches")
            if isinstance(min_matches, int) and min_matches > 0:
                self.min_matches = min_matches

    def scan(self, text: str) -> IllegalDetection:
        if not text or not self.keywords:
            return IllegalDetection(illegal=False, reason="", matches=[])

        lowered = text.lower()
        matches = [term for term in self.keywords if term in lowered]
        unique_matches = sorted(set(matches))
        if len(unique_matches) >= self.min_matches:
            reason = "; ".join(unique_matches[:5])
            return IllegalDetection(illegal=True, reason=reason, matches=unique_matches)
        return IllegalDetection(illegal=False, reason="", matches=[])


__all__ = ["IllegalContentDetector", "IllegalDetection"]

