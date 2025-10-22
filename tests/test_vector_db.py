from __future__ import annotations

import tempfile
import unittest

import numpy as np

import tests._path  # noqa: F401

from oddcrawler.storage.vector_db import QdrantConfig, QdrantVectorStore


class QdrantVectorStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = f"{self.tmpdir.name}/qdrant"  # persistent local storage

    def test_add_and_search(self) -> None:
        store = QdrantVectorStore(dim=4, config=QdrantConfig(collection_name="test", path=self.path))
        self.addCleanup(store.client.close)
        vectors = np.eye(4, dtype="float32")
        store.add(ids=[0, 1, 2, 3], vectors=vectors)
        ids, scores = store.search([vectors[1]], k=2)
        self.assertEqual(ids[0][0], 1)
        self.assertGreaterEqual(scores[0][0], scores[0][1])


if __name__ == "__main__":
    unittest.main()
