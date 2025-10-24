"""Staged triage cascade with cheap heuristics and logging."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

from bs4 import BeautifulSoup

from oddcrawler.prefilter import PrefilterEngine, PrefilterDecision
from oddcrawler.utils.dedupe import simhash as compute_simhash


_DEFAULT_BORING_KEYWORDS = [
    "insurance",
    "mortgage",
    "real estate",
    "press release",
    "terms and conditions",
    "privacy policy",
]

_DEFAULT_ALLOWED_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
}


@dataclass
class CascadeStageResult:
    stage: str
    status: str  # pass | skip | warn
    reason: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "stage": self.stage,
            "status": self.status,
        }
        if self.reason:
            payload["reason"] = self.reason
        if self.metrics:
            payload["metrics"] = self.metrics
        return payload


@dataclass
class CascadeDecision:
    should_skip: bool
    stages: List[CascadeStageResult]
    final_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "should_skip": self.should_skip,
            "final_reason": self.final_reason,
            "stages": [stage.to_dict() for stage in self.stages],
        }


@dataclass
class CascadeConfig:
    max_content_length: int = 2_500_000  # ~2.5 MiB
    min_content_length: int = 512
    snippet_bytes: int = 8192
    max_script_ratio: float = 0.55
    max_anchor_ratio: float = 0.65
    min_text_density: float = 0.02
    boring_keywords: Iterable[str] = field(default_factory=lambda: list(_DEFAULT_BORING_KEYWORDS))
    allowed_content_types: Iterable[str] = field(default_factory=lambda: set(_DEFAULT_ALLOWED_CONTENT_TYPES))
    simhash_enabled: bool = True
    classifier_weights: Mapping[str, float] = field(
        default_factory=lambda: {
            "bias": -1.59,
            "text_density": 0.29,
            "retro_score": 0.04,
            "script_ratio": -0.35,
            "anchor_ratio": 0.75,
            "token_ratio": 3.01,
            "odd_keyword": 0.89,
        }
    )
    classifier_threshold: float = 0.35
    retro_override_score: float = 0.3
    density_token_override: int = 40
    density_anchor_override: float = 0.35
    density_skip_token_cap: int = 15
    odd_keywords: Iterable[str] = field(
        default_factory=lambda: ("webring", "guestbook", "bbs", "forum", "tilde", "topsites", "gopher", "zine")
    )


class TriageCascade:
    """Apply staged gates before full scoring."""

    def __init__(
        self,
        config: Optional[Mapping[str, Any]] = None,
        *,
        prefilter_config: Optional[Mapping[str, Any]] = None,
    ) -> None:
        cfg = dict(config or {})
        self.config = CascadeConfig(
            max_content_length=int(cfg.get("max_content_length", CascadeConfig.max_content_length)),
            min_content_length=int(cfg.get("min_content_length", CascadeConfig.min_content_length)),
            snippet_bytes=int(cfg.get("snippet_bytes", CascadeConfig.snippet_bytes)),
            max_script_ratio=float(cfg.get("max_script_ratio", CascadeConfig.max_script_ratio)),
            max_anchor_ratio=float(cfg.get("max_anchor_ratio", CascadeConfig.max_anchor_ratio)),
            min_text_density=float(cfg.get("min_text_density", CascadeConfig.min_text_density)),
            boring_keywords=tuple(cfg.get("boring_keywords", list(_DEFAULT_BORING_KEYWORDS))),
            allowed_content_types=set(cfg.get("allowed_content_types", _DEFAULT_ALLOWED_CONTENT_TYPES)),
            simhash_enabled=bool(cfg.get("simhash_enabled", True)),
            classifier_weights=dict(cfg.get("classifier_weights", CascadeConfig().classifier_weights)),
            classifier_threshold=float(cfg.get("classifier_threshold", CascadeConfig.classifier_threshold)),
            retro_override_score=float(cfg.get("retro_override_score", CascadeConfig.retro_override_score)),
            density_token_override=int(cfg.get("density_token_override", CascadeConfig.density_token_override)),
            density_anchor_override=float(cfg.get("density_anchor_override", CascadeConfig.density_anchor_override)),
            odd_keywords=tuple(cfg.get("odd_keywords", CascadeConfig().odd_keywords)),
            density_skip_token_cap=int(cfg.get("density_skip_token_cap", CascadeConfig.density_skip_token_cap)),
        )
        self.prefilter = PrefilterEngine(config=prefilter_config or cfg.get("prefilter"))
        self._simhash_seen: set[int] = set()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def evaluate(self, fetch_result: Mapping[str, Any]) -> CascadeDecision:
        stages: List[CascadeStageResult] = []

        if not self._stage_head(fetch_result, stages):
            reason = stages[-1].reason if stages else "head-stage-skip"
            return CascadeDecision(True, stages, final_reason=reason)

        snippet = self._stage_snippet(fetch_result, stages)
        if snippet is None:
            reason = stages[-1].reason if stages else "snippet-stage-skip"
            return CascadeDecision(True, stages, final_reason=reason)

        metrics = self._stage_structure(snippet, stages)
        if metrics is None:
            reason = stages[-1].reason if stages else "structure-stage-skip"
            return CascadeDecision(True, stages, final_reason=reason)

        if not self._stage_keywords(snippet, stages):
            reason = stages[-1].reason if stages else "keyword-stage-skip"
            return CascadeDecision(True, stages, final_reason=reason)

        if not self._stage_simhash(snippet, stages):
            reason = stages[-1].reason if stages else "simhash-stage-skip"
            return CascadeDecision(True, stages, final_reason=reason)

        if not self._stage_classifier(metrics, stages):
            reason = stages[-1].reason if stages else "classifier-stage-skip"
            return CascadeDecision(True, stages, final_reason=reason)

        if not self._stage_prefilter(fetch_result, stages):
            reason = stages[-1].reason if stages else "prefilter-stage-skip"
            return CascadeDecision(True, stages, final_reason=reason)

        return CascadeDecision(False, stages, final_reason=None)

    # ------------------------------------------------------------------ #
    # Individual stages
    # ------------------------------------------------------------------ #
    def _stage_head(self, fetch_result: Mapping[str, Any], stages: List[CascadeStageResult]) -> bool:
        headers = dict(fetch_result.get("headers") or {})
        content_type = (headers.get("Content-Type") or headers.get("content-type") or "").split(";")[0].strip().lower()
        content_length_header = headers.get("Content-Length") or headers.get("content-length")
        try:
            content_length = int(content_length_header) if content_length_header else len(fetch_result.get("body", b""))
        except ValueError:
            content_length = len(fetch_result.get("body", b""))
        if self.config.allowed_content_types and content_type and content_type not in self.config.allowed_content_types:
            stages.append(
                CascadeStageResult(
                    stage="head",
                    status="skip",
                    reason=f"content-type:{content_type}",
                    metrics={"content_type": content_type, "content_length": content_length},
                )
            )
            return False
        if content_length < self.config.min_content_length:
            stages.append(
                CascadeStageResult(
                    stage="head",
                    status="skip",
                    reason=f"content-length<{self.config.min_content_length}",
                    metrics={"content_length": content_length},
                )
            )
            return False
        if content_length > self.config.max_content_length:
            stages.append(
                CascadeStageResult(
                    stage="head",
                    status="skip",
                    reason=f"content-length>{self.config.max_content_length}",
                    metrics={"content_length": content_length},
                )
            )
            return False

        stages.append(
            CascadeStageResult(
                stage="head",
                status="pass",
                metrics={"content_type": content_type, "content_length": content_length},
            )
        )
        return True

    def _stage_snippet(self, fetch_result: Mapping[str, Any], stages: List[CascadeStageResult]) -> Optional[str]:
        body = fetch_result.get("body", b"")
        if not isinstance(body, (bytes, bytearray)):
            stages.append(
                CascadeStageResult(
                    stage="snippet",
                    status="skip",
                    reason="body-missing",
                )
            )
            return None
        snippet_bytes = body[: self.config.snippet_bytes]
        snippet = snippet_bytes.decode("utf-8", errors="ignore")
        if not snippet.strip():
            stages.append(
                CascadeStageResult(
                    stage="snippet",
                    status="skip",
                    reason="empty-snippet",
                )
            )
            return None
        stages.append(
            CascadeStageResult(
                stage="snippet",
                status="pass",
                metrics={"snippet_length": len(snippet)},
            )
        )
        return snippet

    def _stage_structure(self, snippet: str, stages: List[CascadeStageResult]) -> Optional[Dict[str, Any]]:
        soup = BeautifulSoup(snippet, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        total_len = max(len(text), 1)
        token_count = len(text.split())
        anchors = soup.find_all("a")
        scripts = soup.find_all("script")
        text_len = len(text)
        anchor_ratio = len(anchors) / max(len(soup.find_all()), 1)
        script_ratio = len(scripts) / max(len(soup.find_all()), 1)
        text_density = text_len / max(len(snippet), 1)
        retro_tags = ["marquee", "blink", "font", "center"]
        retro_hits = sum(len(soup.find_all(tag)) for tag in retro_tags)
        retro_score = min(retro_hits / 3.0, 1.0)
        lower_text = text.lower()
        odd_keyword_present = any(keyword in lower_text for keyword in self.config.odd_keywords)

        metrics = {
            "token_count": token_count,
            "anchor_ratio": round(anchor_ratio, 4),
            "script_ratio": round(script_ratio, 4),
            "text_density": round(text_density, 4),
            "retro_score": round(retro_score, 4),
            "text_length": text_len,
            "odd_keyword": odd_keyword_present,
        }

        if script_ratio > self.config.max_script_ratio:
            stages.append(
                CascadeStageResult(
                    stage="structure",
                    status="skip",
                    reason=f"script-ratio>{self.config.max_script_ratio}",
                    metrics=metrics,
                )
            )
            return None
        if anchor_ratio > self.config.max_anchor_ratio:
            stages.append(
                CascadeStageResult(
                    stage="structure",
                    status="skip",
                    reason=f"anchor-ratio>{self.config.max_anchor_ratio}",
                    metrics=metrics,
                )
            )
            return None
        low_density = text_density < self.config.min_text_density
        override = None
        if low_density:
            if token_count >= self.config.density_token_override:
                override = "token"
            elif retro_score >= self.config.retro_override_score:
                override = "retro"
            elif anchor_ratio >= self.config.density_anchor_override:
                override = "anchor"
            elif odd_keyword_present:
                override = "keyword"

        if low_density and override is None and token_count <= self.config.density_skip_token_cap:
            stages.append(
                CascadeStageResult(
                    stage="structure",
                    status="skip",
                    reason=f"text-density<{self.config.min_text_density}",
                    metrics=metrics,
                )
            )
            return None

        if low_density and override is None:
            override = "low_density"

        if override:
            metrics["override"] = override
            stages.append(
                CascadeStageResult(
                    stage="structure",
                    status="warn",
                    reason=f"text-density<{self.config.min_text_density}-override:{override}",
                    metrics=metrics,
                )
            )
        else:
            stages.append(
                CascadeStageResult(
                    stage="structure",
                    status="pass",
                    metrics=metrics,
                )
            )

        return metrics

    def _stage_keywords(self, snippet: str, stages: List[CascadeStageResult]) -> bool:
        boring_keywords = tuple(self.config.boring_keywords)
        if not boring_keywords:
            stages.append(CascadeStageResult(stage="keywords", status="pass"))
            return True
        lower_snippet = snippet.lower()
        for keyword in boring_keywords:
            token = keyword.strip().lower()
            if not token:
                continue
            if token in lower_snippet:
                stages.append(
                    CascadeStageResult(
                        stage="keywords",
                        status="skip",
                        reason=f"keyword:{token}",
                    )
                )
                return False
        stages.append(CascadeStageResult(stage="keywords", status="pass"))
        return True

    def _stage_simhash(self, snippet: str, stages: List[CascadeStageResult]) -> bool:
        if not self.config.simhash_enabled:
            stages.append(CascadeStageResult(stage="simhash", status="pass"))
            return True
        fingerprint = compute_simhash(snippet)
        if fingerprint in self._simhash_seen:
            stages.append(
                CascadeStageResult(
                    stage="simhash",
                    status="skip",
                    reason="simhash-duplicate",
                )
            )
            return False
        self._simhash_seen.add(fingerprint)
        stages.append(
            CascadeStageResult(
                stage="simhash",
                status="pass",
                metrics={"fingerprint": fingerprint},
            )
        )
        return True

    def _stage_classifier(self, metrics: Mapping[str, Any], stages: List[CascadeStageResult]) -> bool:
        weights = self.config.classifier_weights
        bias = float(weights.get("bias", 0.0))
        score = bias
        score += float(weights.get("text_density", 0.0)) * float(metrics.get("text_density", 0.0))
        score += float(weights.get("retro_score", 0.0)) * float(metrics.get("retro_score", 0.0))
        score += float(weights.get("script_ratio", 0.0)) * float(metrics.get("script_ratio", 0.0))
        score += float(weights.get("anchor_ratio", 0.0)) * float(metrics.get("anchor_ratio", 0.0))
        token_component = min(2.0, float(metrics.get("token_count", 0)) / 100.0)
        score += float(weights.get("token_ratio", 0.0)) * token_component
        if metrics.get("odd_keyword"):
            score += float(weights.get("odd_keyword", 0.0))
        logistic = 1.0 / (1.0 + math.exp(-score))
        if logistic < self.config.classifier_threshold:
            stages.append(
                CascadeStageResult(
                    stage="classifier",
                    status="skip",
                    reason=f"classifier<{self.config.classifier_threshold}",
                    metrics={"probability": round(logistic, 4)},
                )
            )
            return False
        stages.append(
            CascadeStageResult(
                stage="classifier",
                status="pass",
                metrics={"probability": round(logistic, 4)},
            )
        )
        return True

    def _stage_prefilter(self, fetch_result: Mapping[str, Any], stages: List[CascadeStageResult]) -> bool:
        observation = {
            "url": fetch_result.get("url"),
            "extract": {
                "text_excerpt": self._safe_excerpt(fetch_result),
                "token_count": self._approx_tokens(fetch_result),
            },
            "links": fetch_result.get("links") or {"outbound": []},
        }
        decision: PrefilterDecision = self.prefilter.evaluate(observation)
        if decision.should_skip:
            stages.append(
                CascadeStageResult(
                    stage="prefilter",
                    status="skip",
                    reason=";".join(decision.reasons) if decision.reasons else "prefilter-skip",
                )
            )
            return False
        stages.append(
            CascadeStageResult(
                stage="prefilter",
                status="pass",
            )
        )
        return True

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _safe_excerpt(fetch_result: Mapping[str, Any], limit: int = 1200) -> str:
        body = fetch_result.get("body", b"")
        if isinstance(body, (bytes, bytearray)):
            return body[:limit].decode("utf-8", errors="ignore")
        return str(body)[:limit]

    @staticmethod
    def _approx_tokens(fetch_result: Mapping[str, Any]) -> int:
        body = fetch_result.get("body", b"")
        if isinstance(body, (bytes, bytearray)):
            snippet = body[:2048].decode("utf-8", errors="ignore")
        else:
            snippet = str(body)[:2048]
        return len(re.findall(r"\w+", snippet))


__all__ = ["CascadeDecision", "CascadeStageResult", "CascadeConfig", "TriageCascade"]
