"""Analyst result handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from oddcrawler.llm import GeminiClient
from oddcrawler.storage import maybe_record_breadcrumb, write_observation_excerpt
from oddcrawler.storage.config import load_storage_config


@dataclass
class AnalystProcessingResult:
    finding: Mapping[str, Any]
    breadcrumb: Optional[Any]
    observation_path: Optional[str]


class AnalystResultProcessor:
    """Handles validated analyst findings and optional breadcrumbs."""

    def __init__(
        self,
        storage_config: Optional[Dict[str, Any]] = None,
        *,
        llm_client: Optional[GeminiClient] = None,
        llm_config_path: str = "config/llm.yaml",
    ) -> None:
        try:
            self.config = storage_config or load_storage_config()
        except FileNotFoundError:
            self.config = storage_config or {}
        self._llm_client = llm_client
        self.llm_config_path = llm_config_path

    def process(
        self,
        finding: Optional[Mapping[str, Any]] = None,
        *,
        observation: Optional[Mapping[str, Any]] = None,
        persist_observation: bool = True,
    ) -> AnalystProcessingResult:
        if finding is None:
            if observation is None:
                raise ValueError("Observation required when generating finding via LLM.")
            finding = self._generate_finding(observation)

        finding_dict = dict(finding)
        if observation:
            observation_ref = self._ensure_observation_ref(finding_dict, observation)
        else:
            observation_ref = finding_dict.get("observation_ref")

        observation_path = None
        if persist_observation and observation:
            path = write_observation_excerpt(observation, config=self.config)
            observation_path = str(path) if path else None

        breadcrumb = maybe_record_breadcrumb(finding_dict, observation=observation, config=self.config)

        return AnalystProcessingResult(
            finding=finding_dict,
            breadcrumb=breadcrumb,
            observation_path=observation_path,
        )

    def _ensure_observation_ref(
        self, finding: Dict[str, Any], observation: Mapping[str, Any]
    ) -> str:
        fetched_at = observation.get("fetched_at", "unknown")
        hashes = observation.get("hashes")
        url_hash = ""
        if isinstance(hashes, Mapping):
            url_hash = str(hashes.get("url_sha256") or hashes.get("url_sha1") or "")
        observation_ref = finding.get("observation_ref")
        if not observation_ref:
            observation_ref = f"observation:{fetched_at}:{url_hash[:8]}"
            finding["observation_ref"] = observation_ref
        if "url" not in finding and observation.get("url"):
            finding["url"] = observation.get("url")
        return observation_ref

    def _generate_finding(self, observation: Mapping[str, Any]) -> Dict[str, Any]:
        client = self._ensure_llm_client()
        extra_context = {}
        hashes = observation.get("hashes")
        if isinstance(hashes, Mapping):
            extra_context["hashes"] = dict(hashes)
        return client.generate_analyst_finding(observation, extra_context=extra_context)

    def _ensure_llm_client(self) -> GeminiClient:
        if self._llm_client is None:
            self._llm_client = GeminiClient(model_key="analyst", config_path=self.llm_config_path)
        return self._llm_client


__all__ = ["AnalystResultProcessor", "AnalystProcessingResult"]
