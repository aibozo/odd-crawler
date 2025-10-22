from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Sequence

import numpy as np

import tests._path  # noqa: F401

from oddcrawler.scoring import EmbeddingConfig, EmbeddingIndexer
from oddcrawler.storage import QdrantConfig, QdrantVectorStore


class DummyModel:
    def __init__(self, dim: int = 4) -> None:
        self._dim = dim
        self.device = "cpu"

    def get_sentence_embedding_dimension(self) -> int:
        return self._dim

    def encode(self, texts: Sequence[str], convert_to_numpy: bool = True, normalize_embeddings: bool = True) -> np.ndarray:
        embeddings = []
        for text in texts:
            vec = np.zeros(self._dim, dtype="float32")
            index = (ord(text[0].lower()) - ord("a")) % self._dim if text else 0
            vec[index] = 1.0
            embeddings.append(vec)
        return np.vstack(embeddings)


class EmbeddingIndexerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.dir = Path(self.tmpdir.name)

    def test_add_and_search(self) -> None:
        collection = "test_dummy"
        store_path = self.dir / "dummy.qdrant"
        store = QdrantVectorStore(dim=4, config=QdrantConfig(collection_name=collection, path=str(store_path)))
        self.addCleanup(store.client.close)
        indexer = EmbeddingIndexer(config=EmbeddingConfig(model_name="dummy"), model=DummyModel(), store=store)
        indexer.add(["alpha", "beta", "gamma"], metadata_ids=[100, 101, 102])
        ids, distances = indexer.search(["beta"], k=2)
        self.assertEqual(ids[0][0], 101)
        self.assertEqual(len(ids[0]), 2)

    def test_save_and_load(self) -> None:
        collection = "test_real"
        store_path = self.dir / "real.qdrant"
        store = QdrantVectorStore(
            dim=384,
            config=QdrantConfig(collection_name=collection, path=str(store_path)),
        )
        self.addCleanup(store.client.close)
        indexer = EmbeddingIndexer(
            config=EmbeddingConfig(model_name="sentence-transformers/all-MiniLM-L12-v2"),
            store=store,
        )
        indexer.add(["delta", "epsilon"], metadata_ids=[1, 2])
        indexer.save(self.dir)
        if hasattr(indexer.store, "client"):
            indexer.store.client.close()

        reloaded = EmbeddingIndexer.load(
            self.dir, config=EmbeddingConfig(model_name="sentence-transformers/all-MiniLM-L12-v2")
        )
        if hasattr(reloaded.store, "client"):
            self.addCleanup(reloaded.store.client.close)
        self.addCleanup(getattr(reloaded.store, "client", lambda: None).close)
        ids, _ = reloaded.search(["delta"], k=1)
        self.assertEqual(ids[0][0], 1)


if __name__ == "__main__":
    unittest.main()
