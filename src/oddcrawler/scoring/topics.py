"""BERTopic-based topic summarization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

import hdbscan
import umap
from bertopic import BERTopic
from sentence_transformers import SentenceTransformer


@dataclass
class TopicConfig:
    model_name: str = "sentence-transformers/all-MiniLM-L12-v2"
    n_neighbors: int = 15
    n_components: int = 5
    min_cluster_size: int = 5
    min_samples: int | None = None


class TopicSummarizer:
    def __init__(self, config: TopicConfig | None = None, *, model: SentenceTransformer | None = None) -> None:
        self.config = config or TopicConfig()
        self.model = model or SentenceTransformer(self.config.model_name)
        umap_model = umap.UMAP(
            n_neighbors=min(self.config.n_neighbors, 10),
            n_components=min(self.config.n_components, 5),
            random_state=42,
            min_dist=0.0,
        )
        hdbscan_model = hdbscan.HDBSCAN(
            min_cluster_size=max(self.config.min_cluster_size, 2),
            min_samples=self.config.min_samples,
        )
        self.topic_model = BERTopic(
            umap_model=umap_model,
            hdbscan_model=hdbscan_model,
            embedding_model=self.model,
            verbose=False,
        )

    def fit_transform(self, documents: Iterable[str]) -> Tuple[List[int], List[float]]:
        docs = list(documents)
        topics, probs = self.topic_model.fit_transform(docs)
        return topics, probs  # type: ignore[return-value]

    def get_topic_info(self):
        return self.topic_model.get_topic_info()

    def get_topic(self, topic_id: int):
        return self.topic_model.get_topic(topic_id)

    def summarize(self, documents: Sequence[str], top_n: int = 5) -> List[dict]:
        topics, _ = self.fit_transform(documents)
        info = self.topic_model.get_topic_info()
        summaries: List[dict] = []
        for _, row in info.iterrows():
            topic_id = row["Topic"]
            if topic_id == -1:
                continue
            top_terms = self.topic_model.get_topic(topic_id) or []
            summaries.append(
                {
                    "topic": int(topic_id),
                    "representation": [(term, float(weight)) for term, weight in top_terms[:top_n]],
                    "count": int(row["Count"]),
                }
            )
        return summaries


__all__ = ["TopicConfig", "TopicSummarizer"]
