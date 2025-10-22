"""Embedding utilities using SentenceTransformers and persistent vector stores."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Optional

import numpy as np
from qdrant_client.models import Distance
from sentence_transformers import SentenceTransformer

from oddcrawler.storage import (
    FaissVectorStore,
    QdrantConfig,
    QdrantVectorStore,
    load_storage_config,
    resolve_section_path,
)


@dataclass
class EmbeddingConfig:
    model_name: str = "sentence-transformers/all-MiniLM-L12-v2"
    index_factory: str = "Flat"


class EmbeddingIndexer:
    """Generate text embeddings and index them for nearest-neighbor search."""

    def __init__(
        self,
        *,
        config: EmbeddingConfig | None = None,
        model: SentenceTransformer | None = None,
        store: FaissVectorStore | QdrantVectorStore | None = None,
    ) -> None:
        self.config = config or EmbeddingConfig()
        self.model = model or SentenceTransformer(self.config.model_name)
        dim = self.model.get_sentence_embedding_dimension()

        if store is None:
            storage_cfg = load_storage_config()
            vector_dir = resolve_section_path("vectors", storage_cfg)
            vector_dir.mkdir(parents=True, exist_ok=True)
            qdrant_path = vector_dir / "qdrant.db"
            store = QdrantVectorStore(dim=dim, config=QdrantConfig(collection_name="embeddings", path=str(qdrant_path)))

        self.store = store
        self.dim = dim

        self._next_id = 0
        if hasattr(self.store, "get_all"):
            try:
                ids, _ = self.store.get_all()  # type: ignore[arg-type]
            except Exception:  # pragma: no cover - defensive fallback
                ids = []
            self._next_id = max(ids, default=-1) + 1

    def embed(self, texts: Sequence[str], *, normalize: bool = True) -> np.ndarray:
        embeddings = self.model.encode(list(texts), convert_to_numpy=True, normalize_embeddings=normalize)
        return embeddings.astype("float32")

    def add(self, texts: Sequence[str], metadata_ids: Iterable[int] | None = None) -> None:
        embeddings = self.embed(texts)

        if isinstance(self.store, QdrantVectorStore):
            if metadata_ids is None:
                ids = list(range(self._next_id, self._next_id + len(embeddings)))
            else:
                ids = list(metadata_ids)
            self.store.add(ids, embeddings)
        else:
            ids = list(metadata_ids) if metadata_ids is not None else None
            self.store.add(embeddings, ids=ids)  # type: ignore[arg-type]
            if ids is None:
                ids = list(range(self._next_id, self._next_id + len(embeddings)))

        if ids:
            self._next_id = max(ids) + 1

    def search(self, query_texts: Sequence[str], k: int = 5) -> tuple[list[list[int]], list[list[float]]]:
        query_vectors = self.embed(query_texts)
        return self.store.search(query_vectors, k=k)

    def save(self, directory: Path | str) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        meta = {"model_name": self.config.model_name}

        if isinstance(self.store, QdrantVectorStore):
            meta.update(
                {
                    "backend": "qdrant",
                    "collection": self.store.collection,
                    "path": str(self.store.config.path) if self.store.config.path is not None else None,
                    "distance": self.store.config.distance_metric.value,
                }
            )
        elif hasattr(self.store, "save"):
            meta["backend"] = "faiss"
            index_path = directory / "vectors.index"
            self.store.save(index_path)
        else:
            meta["backend"] = "custom"

        with (directory / "embedding_meta.json").open("w", encoding="utf-8") as handle:
            json.dump(meta, handle, indent=2)

    @classmethod
    def load(cls, directory: Path | str, *, config: EmbeddingConfig | None = None) -> "EmbeddingIndexer":
        directory = Path(directory)
        meta_path = directory / "embedding_meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"Embedding metadata not found: {meta_path}")

        with meta_path.open("r", encoding="utf-8") as handle:
            metadata = json.load(handle)

        model_name = metadata.get("model_name", (config.model_name if config else EmbeddingConfig().model_name))
        config = config or EmbeddingConfig(model_name=model_name)
        model = SentenceTransformer(model_name)

        backend = metadata.get("backend", "qdrant")
        if backend == "qdrant":
            store = QdrantVectorStore(
                dim=None,
                config=QdrantConfig(
                    collection_name=metadata.get("collection", "embeddings"),
                    path=metadata.get("path"),
                    distance_metric=Distance(metadata.get("distance", Distance.COSINE.value)),
                ),
            )
        elif backend == "faiss":
            store = FaissVectorStore.load(directory / "vectors.index")
        else:
            store = None

        return cls(config=config, model=model, store=store)


__all__ = ["EmbeddingIndexer", "EmbeddingConfig"]
