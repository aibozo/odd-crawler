"""Embedding- and heuristic-based prefilter stage."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

import numpy as np
from pydantic import BaseModel, Field, ConfigDict, ValidationError, field_validator

try:  # pragma: no cover - optional dependency
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover
    SentenceTransformer = None  # type: ignore[assignment]


class EmbeddingConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    odd_centroids: Sequence[Sequence[float]] = Field(default_factory=list)
    boring_centroids: Sequence[Sequence[float]] = Field(default_factory=list)
    odd_similarity_threshold: float = 0.55
    boring_similarity_threshold: float = 0.70

    @field_validator("odd_centroids", "boring_centroids", mode="before")
    @classmethod
    def _coerce_centroids(cls, value: Any) -> Sequence[Sequence[float]]:
        if value is None:
            return []
        if isinstance(value, (bytes, str)):
            raise ValueError("centroid lists must be provided as arrays, not strings")
        centroids: list[list[float]] = []
        for row in value:
            if row is None:
                continue
            if isinstance(row, (bytes, str)):
                raise ValueError("centroid rows must be numeric sequences")
            centroids.append([float(item) for item in row])
        return centroids

    @field_validator("odd_similarity_threshold", "boring_similarity_threshold", mode="before")
    @classmethod
    def _floats(cls, value: Any) -> float:
        return float(value)


class HeuristicConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    min_token_count: int = 50
    boring_keywords: Sequence[str] = Field(default_factory=list)
    max_same_domain_outbound_ratio: float = 1.0

    @field_validator("min_token_count", mode="before")
    @classmethod
    def _coerce_token_count(cls, value: Any) -> int:
        return int(value)

    @field_validator("max_same_domain_outbound_ratio", mode="before")
    @classmethod
    def _coerce_ratio(cls, value: Any) -> float:
        return float(value)

    @field_validator("boring_keywords", mode="before")
    @classmethod
    def _coerce_keywords(cls, value: Any) -> Sequence[str]:
        if value is None:
            return []
        if isinstance(value, str):
            tokens = [token.strip() for token in value.split(",")]
        else:
            tokens = [str(item).strip() for item in value if str(item).strip()]
        deduped: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            lowered = token.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            deduped.append(token)
        return deduped


class PrefilterConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    heuristics: HeuristicConfig = Field(default_factory=HeuristicConfig)
    embedding: Optional[EmbeddingConfig] = None


@dataclass
class PrefilterDecision:
    should_skip: bool
    reasons: Sequence[str]
    scores: Mapping[str, float]


class PrefilterEngine:
    """Applies cheap heuristics to avoid expensive scoring/LLM passes."""

    def __init__(
        self,
        config_path: Path | str = Path("config/prefilter.yaml"),
        *,
        config: Optional[Mapping[str, Any]] = None,
    ) -> None:
        raw_config: Dict[str, Any] = {}
        if config is not None:
            raw_config = dict(config)
        else:
            path = Path(config_path)
            if path.exists():
                raw_config = self._load_from_path(path)
        try:
            self.config = PrefilterConfig.model_validate(raw_config or {})
        except ValidationError as exc:  # pragma: no cover - configuration errors
            raise ValueError(f"Invalid prefilter configuration: {exc}") from exc
        self._model: Optional[SentenceTransformer] = None
        self._odd_centroids: Optional[np.ndarray] = None
        self._boring_centroids: Optional[np.ndarray] = None
        if self.config.embedding and SentenceTransformer is not None:
            self._prepare_centroids(self.config.embedding)

    @staticmethod
    def _load_from_path(path: Path) -> Dict[str, Any]:
        data = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            return json.loads(data)
        if path.suffix in {".yaml", ".yml"}:
            return dict(PrefilterEngine._load_yaml(path))
        # fall back to YAML for extensionless files
        return dict(PrefilterEngine._load_yaml(path))

    @staticmethod
    def _load_yaml(path: Path) -> Mapping[str, Any]:
        import yaml  # lazy import

        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def _prepare_centroids(self, cfg: EmbeddingConfig) -> None:
        if cfg.odd_centroids:
            self._odd_centroids = np.array(cfg.odd_centroids, dtype=np.float32)
        if cfg.boring_centroids:
            self._boring_centroids = np.array(cfg.boring_centroids, dtype=np.float32)

    def _ensure_model(self) -> Optional[SentenceTransformer]:
        if not self.config.embedding:
            return None
        if SentenceTransformer is None:
            return None
        if self._model is None:
            self._model = SentenceTransformer(self.config.embedding.model)
        return self._model

    def evaluate(self, observation: Mapping[str, Any]) -> PrefilterDecision:
        if not self.config.enabled:
            return PrefilterDecision(False, [], {})

        reasons: list[str] = []
        scores: dict[str, float] = {}
        heuristics = self.config.heuristics

        extract = observation.get("extract")
        text_excerpt = ""
        token_count = 0
        if isinstance(extract, Mapping):
            text_excerpt = str(extract.get("text_excerpt") or "")
            token_count = int(extract.get("token_count") or 0)
        if token_count and token_count < heuristics.min_token_count:
            reasons.append(f"token_count<{heuristics.min_token_count}")

        lower_excerpt = text_excerpt.lower()
        for keyword in heuristics.boring_keywords:
            if keyword.lower() in lower_excerpt:
                reasons.append(f"keyword:{keyword}")
                break

        links = observation.get("links")
        outbound_links = []
        if isinstance(links, Mapping):
            outbound_links = links.get("outbound") or []
        same_domain_ratio = self._compute_same_domain_ratio(observation.get("url"), outbound_links)
        if same_domain_ratio is not None:
            scores["outbound_same_ratio"] = same_domain_ratio
            if same_domain_ratio >= heuristics.max_same_domain_outbound_ratio:
                reasons.append("outbound_same_domain")

        embed_cfg = self.config.embedding
        if embed_cfg and (self._odd_centroids is not None or self._boring_centroids is not None):
            vector = self._compute_embedding(text_excerpt)
            if vector is not None:
                if self._odd_centroids is not None and len(self._odd_centroids):
                    odd_sim = float(np.max(self._odd_centroids @ vector))
                    scores["odd_similarity"] = odd_sim
                    if odd_sim >= embed_cfg.odd_similarity_threshold:
                        # strong odd match -> override boring reasons
                        return PrefilterDecision(False, [], scores)
                if self._boring_centroids is not None and len(self._boring_centroids):
                    boring_sim = float(np.max(self._boring_centroids @ vector))
                    scores["boring_similarity"] = boring_sim
                    if boring_sim >= embed_cfg.boring_similarity_threshold:
                        reasons.append("boring_embedding")

        should_skip = bool(reasons)
        return PrefilterDecision(should_skip, reasons, scores)

    def _compute_embedding(self, text: str) -> Optional[np.ndarray]:
        if not text or len(text.strip()) < 20:
            return None
        model = self._ensure_model()
        if model is None:
            return None
        vector = model.encode([text], normalize_embeddings=True)
        if not isinstance(vector, np.ndarray):
            vector = np.asarray(vector)
        return vector.reshape(-1)

    @staticmethod
    def _compute_same_domain_ratio(root_url: Any, links: Iterable[Any]) -> Optional[float]:
        from urllib.parse import urlsplit

        if not isinstance(root_url, str) or not links:
            return None
        root_domain = urlsplit(root_url).netloc
        if not root_domain:
            return None
        total = 0
        same = 0
        for item in links:
            if isinstance(item, Mapping):
                url = item.get("url")
            else:
                url = None
            if not isinstance(url, str):
                continue
            total += 1
            if urlsplit(url).netloc == root_domain:
                same += 1
        if total == 0:
            return None
        return same / total
