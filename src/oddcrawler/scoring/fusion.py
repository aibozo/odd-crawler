"""Basic oddness scoring engine."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Mapping

from oddcrawler.agents.triage import ScoreDecision

from .config import load_scoring_config


@dataclass
class FeatureScores:
    retro_html: float
    url_weird: float
    semantic: float
    anomaly: float
    graph: float


class ScoringEngine:
    """Combine feature scores into a single oddness score."""

    def __init__(self, config_path: str | None = None) -> None:
        self.config = load_scoring_config(config_path)
        self.weights = self.config.get("weights", {})
        self.thresholds = self.config.get("thresholds", {})

    def score_features(self, features: Mapping[str, Any]) -> FeatureScores:
        retro = float(features.get("html_retro", {}).get("score", 0.0))
        url_weird = float(features.get("url_weird", {}).get("score", 0.0))
        semantic = float(features.get("semantic", {}).get("score", 0.0))
        anomaly = float(features.get("anomaly", {}).get("score", 0.0))
        graph = float(features.get("graph", {}).get("score", 0.0))
        return FeatureScores(retro_html=retro, url_weird=url_weird, semantic=semantic, anomaly=anomaly, graph=graph)

    def fuse(self, scores: FeatureScores) -> float:
        bias = float(self.weights.get("bias", 0.0))
        raw = (
            scores.retro_html * float(self.weights.get("retro_html", 0.0))
            + scores.url_weird * float(self.weights.get("url_weird", 0.0))
            + scores.semantic * float(self.weights.get("semantic", 0.0))
            + scores.anomaly * float(self.weights.get("anomaly", 0.0))
            + scores.graph * float(self.weights.get("graph", 0.0))
            + bias
        )
        return 1.0 / (1.0 + math.exp(-raw))

    def decide(self, fused_score: float, reasons: list[str]) -> ScoreDecision:
        persist_threshold = float(self.thresholds.get("persist", 0.35))
        llm_threshold = float(self.thresholds.get("llm_gate", 0.60))
        alert_threshold = float(self.thresholds.get("alert", 0.80))

        if fused_score >= llm_threshold:
            action = "llm"
        elif fused_score >= persist_threshold:
            action = "persist"
        else:
            action = "skip"

        thresholds_hit = {
            "persist": persist_threshold,
            "llm": llm_threshold if fused_score >= llm_threshold else None,
            "alert": alert_threshold if fused_score >= alert_threshold else None,
        }

        thresholds_hit = {k: v for k, v in thresholds_hit.items() if v is not None}

        return ScoreDecision(
            score=fused_score,
            action=action,
            thresholds_hit=thresholds_hit,
            reasons=reasons,
        )

    def evaluate(self, observation: Dict[str, Any]) -> ScoreDecision:
        features = observation.get("features", {})
        scores = self.score_features(features)
        reasons: list[str] = []

        if features.get("html_retro", {}).get("signals"):
            signals = ", ".join(features["html_retro"].get("signals", []))
            reasons.append(f"retro HTML signals: {signals}")
        if features.get("url_weird", {}).get("flags"):
            flags = ", ".join(features["url_weird"].get("flags", []))
            reasons.append(f"url oddities: {flags}")
        graph_features = features.get("graph", {})
        if isinstance(graph_features, Mapping):
            if graph_features.get("has_webring"):
                reasons.append("possible webring membership")
            component_size = graph_features.get("component_size")
            if isinstance(component_size, (int, float)) and component_size and component_size <= 3:
                reasons.append(f"small link neighborhood (size={int(component_size)})")

        fused_score = self.fuse(scores)
        observation["prelim_score"] = fused_score
        return self.decide(fused_score, reasons)


__all__ = ["ScoringEngine", "FeatureScores"]
