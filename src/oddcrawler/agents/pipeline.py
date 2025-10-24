"""Pipeline glue that wires fetch results, scoring, and triage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from oddcrawler.storage import write_raw_response

from .triage import ScoreDecision, TriageOrchestrator


@dataclass
class FetchResult:
    """Minimal fetch result representation used by the pipeline."""

    url: str
    url_hash: str
    fetched_at: str
    headers: Mapping[str, Any]
    body: bytes
    status: Optional[int] = None
    duration_ms: Optional[float] = None
    bytes_downloaded: Optional[int] = None
    via_tor: bool = False


class OddcrawlerPipeline:
    """Coordinates storage and triage for the crawler pipeline."""

    def __init__(self, *, triage: Optional[TriageOrchestrator] = None) -> None:
        self.triage = triage or TriageOrchestrator()

    def record_fetch(self, result: FetchResult) -> None:
        """Persist raw response according to storage policy."""
        write_raw_response(
            result.url_hash,
            content=result.body,
            headers=result.headers,
            fetched_at=result.fetched_at,
            config=self.triage.config,
        )

    def handle_scored_observation(
        self,
        observation: Mapping[str, Any],
        decision: ScoreDecision,
        *,
        finding: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        """Send observation through triage and return the structured result."""
        return self.triage.handle_decision(
            decision,
            observation=observation,
            finding=finding,
        )


__all__ = ["FetchResult", "OddcrawlerPipeline"]
