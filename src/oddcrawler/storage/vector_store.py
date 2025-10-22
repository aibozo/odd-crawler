"""FAISS vector store wrapper."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import faiss
import numpy as np

Vector = Sequence[float]


class FaissVectorStore:
    """Lightweight FAISS wrapper for embedding storage and search."""

    def __init__(self, dim: int, *, index_factory: str = "Flat", ids: Iterable[int] | None = None) -> None:
        if dim <= 0:
            raise ValueError("Dimension must be positive")

        self.dim = dim
        base_index = faiss.index_factory(dim, index_factory)
        if not isinstance(base_index, faiss.IndexIDMap):
            self._index = faiss.IndexIDMap(base_index)
        else:
            self._index = base_index

        if ids is not None:
            self._ids: List[int] = list(ids)
            if len(self._ids) != self._index.ntotal:
                raise ValueError("IDs length must match existing index size")
        else:
            self._ids = list(map(int, self._index.id_map_to_array())) if self._index.ntotal else []
        self._next_id = max(self._ids, default=-1) + 1

    @property
    def size(self) -> int:
        return len(self._ids)

    def add(self, vectors: Sequence[Vector], ids: Iterable[int] | None = None) -> None:
        if len(vectors) == 0:
            return
        faiss_vectors = self._to_faiss_array(vectors)
        if ids is not None:
            id_list = list(ids)
            if len(id_list) != len(vectors):
                raise ValueError("ids length must match vectors length")
        else:
            id_list = list(range(self._next_id, self._next_id + len(vectors)))
        self._index.add_with_ids(faiss_vectors, self._to_faiss_ids(id_list))
        self._ids.extend(id_list)
        self._next_id = max(self._ids, default=-1) + 1

    def search(self, vectors: Sequence[Vector], k: int = 5) -> Tuple[List[List[int]], List[List[float]]]:
        if len(vectors) == 0:
            return ([], [])
        faiss_vectors = self._to_faiss_array(vectors)
        distances, raw_ids = self._index.search(faiss_vectors, k)
        ids = [list(map(int, row)) for row in raw_ids]
        return ids, [list(map(float, row)) for row in distances]

    def get_all(self) -> Tuple[List[int], np.ndarray]:
        if self.size == 0:
            return [], np.zeros((0, self.dim), dtype="float32")
        base = self._index.index if isinstance(self._index, faiss.IndexIDMap) else self._index
        vectors = base.reconstruct_n(0, self.size)
        return list(self._ids), np.array(vectors, dtype="float32")

    def save(self, index_path: Path | str, ids_path: Path | str | None = None) -> None:
        index_path = Path(index_path)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(index_path))

        ids_path = Path(ids_path) if ids_path else index_path.with_suffix(".ids.json")
        with ids_path.open("w", encoding="utf-8") as handle:
            json.dump(self._ids, handle)

    @classmethod
    def load(cls, index_path: Path | str, ids_path: Path | str | None = None) -> "FaissVectorStore":
        index_path = Path(index_path)
        index = faiss.read_index(str(index_path))
        if not isinstance(index, faiss.IndexIDMap):
            index = faiss.IndexIDMap(index)
        dim = index.d

        ids_path = Path(ids_path) if ids_path else index_path.with_suffix(".ids.json")
        if ids_path.exists():
            with ids_path.open("r", encoding="utf-8") as handle:
                ids = [int(x) for x in json.load(handle)]
        else:
            ids = [int(x) for x in index.id_map_to_array()]

        store = cls(dim)
        store._index = index
        store._ids = ids
        store._next_id = max(store._ids, default=-1) + 1
        return store

    def _to_faiss_array(self, vectors: Sequence[Vector]) -> np.ndarray:
        np_array = np.asarray(vectors, dtype="float32")
        if np_array.ndim != 2 or np_array.shape[1] != self.dim:
            raise ValueError(f"Expected shape (n, {self.dim}), got {np_array.shape}")
        return np.ascontiguousarray(np_array)

    @staticmethod
    def _to_faiss_ids(ids: Sequence[int]) -> np.ndarray:
        return np.asarray(ids, dtype="int64")


__all__ = ["FaissVectorStore"]
