"""Qdrant vector store adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http import models as http_models
from qdrant_client.models import Distance, PointStruct, VectorParams

Vector = Sequence[float]


@dataclass
class QdrantConfig:
    collection_name: str = "oddcrawler_embeddings"
    distance_metric: Distance = Distance.COSINE
    host: str | None = None
    port: int | None = None
    path: str | None = None  # for local file-based storage


class QdrantVectorStore:
    """Wrapper around QdrantClient with a simple add/search interface."""

    def __init__(self, dim: Optional[int] = None, *, config: QdrantConfig | None = None) -> None:
        self.config = config or QdrantConfig()

        kwargs = {}
        if self.config.host:
            kwargs["host"] = self.config.host
        if self.config.port:
            kwargs["port"] = self.config.port
        if self.config.path:
            kwargs["path"] = self.config.path

        self.client = QdrantClient(**kwargs)
        self.collection = self.config.collection_name
        exists = self.client.collection_exists(collection_name=self.collection)

        if not exists:
            if dim is None:
                raise ValueError("Dimension must be provided when creating a new Qdrant collection")
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=dim, distance=self.config.distance_metric),
            )
            self.dim = dim
        else:
            info = self.client.get_collection(self.collection)
            vectors_cfg = info.config.params.vectors
            size = getattr(vectors_cfg, "size", None)
            if size is None and isinstance(vectors_cfg, dict):
                size = vectors_cfg.get("size")
            if size is None:
                raise ValueError("Unable to determine vector size from existing Qdrant collection")
            self.dim = int(size)
            if dim is not None and dim != self.dim:
                raise ValueError(f"Provided dim {dim} does not match existing collection size {self.dim}")

    def add(self, ids: Iterable[int], vectors: Sequence[Vector]) -> None:
        points = [PointStruct(id=int(idx), vector=list(vec)) for idx, vec in zip(ids, vectors)]
        if points:
            self.client.upsert(collection_name=self.collection, points=points)

    def search(self, query_vectors: Sequence[Vector], k: int = 5) -> Tuple[List[List[int]], List[List[float]]]:
        ids: List[List[int]] = []
        distances: List[List[float]] = []
        for vec in query_vectors:
            response = self.client.query_points(
                collection_name=self.collection,
                query=list(vec),
                limit=k,
            )
            ids.append([int(point.id) for point in response.points])
            distances.append([float(point.score) for point in response.points])
        return ids, distances

    def get_all_ids(self) -> List[int]:
        records = self.client.scroll(collection_name=self.collection, limit=10000)[0]
        return [int(record.id) for record in records]

    def get_all(self) -> Tuple[List[int], np.ndarray]:
        ids: List[int] = []
        vectors: List[List[float]] = []
        offset: Optional[http_models.ScrollResult] = None
        while True:
            batch, offset = self.client.scroll(
                collection_name=self.collection,
                offset=offset,
                limit=256,
                with_vectors=True,
            )
            for record in batch:
                vec = record.vector
                if isinstance(vec, dict):
                    vec = next(iter(vec.values()))
                ids.append(int(record.id))
                vectors.append(list(vec))
            if offset is None:
                break
        return ids, np.array(vectors, dtype="float32")


__all__ = ["QdrantVectorStore", "QdrantConfig"]
