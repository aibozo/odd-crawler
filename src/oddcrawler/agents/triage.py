"""Triage orchestration utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from oddcrawler.llm import GeminiConfigurationError
from oddcrawler.storage import write_observation_excerpt
from oddcrawler.storage.config import load_storage_config

from .analyst import AnalystResultProcessor, AnalystProcessingResult


@dataclass
class ScoreDecision:
    score: float
    action: str  # skip | persist | llm
    thresholds_hit: Dict[str, float]
    reasons: Optional[list[str]] = None


class TriageOrchestrator:
    """Coordinates storage and downstream escalation based on scoring decisions."""

    def __init__(
        self,
        storage_config: Optional[Dict[str, Any]] = None,
        *,
        llm_client: Optional[Any] = None,
    ) -> None:
        try:
            self.config = storage_config or load_storage_config()
        except FileNotFoundError:
            self.config = storage_config or {}
        self.analyst_processor = AnalystResultProcessor(storage_config=self.config, llm_client=llm_client)

    def handle_decision(
        self,
        decision: ScoreDecision,
        *,
        observation: Mapping[str, Any],
        finding: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist observation excerpts and optionally escalate to analyst."""
        observation_path = write_observation_excerpt(observation, config=self.config)

        result: Optional[AnalystProcessingResult] = None
        finding_payload: Optional[Mapping[str, Any]] = finding
        if decision.action == "llm":
            try:
                result = self.analyst_processor.process(
                    finding,
                    observation=observation,
                    persist_observation=False,
                )
                finding_payload = result.finding
            except GeminiConfigurationError:
                fallback = self._fallback_finding(observation, decision)
                result = self.analyst_processor.process(
                    fallback,
                    observation=observation,
                    persist_observation=False,
                )
                finding_payload = result.finding

        return {
            "decision": decision,
            "observation_path": str(observation_path) if observation_path else None,
            "finding": finding_payload,
            "analyst_result": result,
        }

    def _fallback_finding(self, observation: Mapping[str, Any], decision: ScoreDecision) -> Dict[str, Any]:
        reasons = decision.reasons or ["auto-escalated"]
        url = str(observation.get("url", ""))
        fetched_at = observation.get("fetched_at", "unknown")

        hashes = observation.get("hashes")
        url_hash = ""
        if isinstance(hashes, Mapping):
            url_hash = str(hashes.get("url_sha256") or hashes.get("url_sha1") or "")
        observation_ref = f"observation:{fetched_at}:{url_hash[:8]}"

        extract = observation.get("extract")
        summary = ""
        if isinstance(extract, Mapping):
            summary = str(extract.get("text_excerpt", "")).strip()
        if not summary and reasons:
            summary = f"Page at {url} flagged because {', '.join(reasons)}."
        if len(summary) > 360:
            summary = summary[:357].rstrip() + "..."

        risk_tag = "unknown"
        features = observation.get("features")
        if isinstance(features, Mapping):
            retro = features.get("html_retro")
            if isinstance(retro, Mapping) and retro.get("signals"):
                risk_tag = "harmless-retro"

        return {
            "url": url,
            "summary": summary or "Auto-generated analyst summary.",
            "why_flagged": reasons,
            "risk_tag": risk_tag,
            "dangerous_content": {"present": False, "category": "none", "notes": ""},
            "confidence": round(decision.score, 2),
            "observation_ref": observation_ref,
        }


__all__ = ["ScoreDecision", "TriageOrchestrator"]
