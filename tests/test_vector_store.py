from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

import tests._path  # noqa: F401

from oddcrawler.storage import FaissVectorStore


class VectorStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.index_path = Path(self.tmpdir.name) / "vectors.index"

    def test_add_and_search(self) -> None:
        store = FaissVectorStore(dim=4)
        vectors = np.array(
            [
                [0.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [1.0, 0.0, 0.0, 0.0],
            ],
            dtype="float32",
        )
        store.add(vectors, ids=[10, 11, 12])
        ids, distances = store.search([[0.0, 1.0, 0.0, 0.0]], k=2)
        self.assertEqual(ids[0][0], 11)
        self.assertLess(distances[0][0], distances[0][1])

    def test_save_and_load(self) -> None:
        store = FaissVectorStore(dim=2)
        store.add([[0.1, 0.2], [0.2, 0.3]], ids=[1, 2])
        store.save(self.index_path)

        reloaded = FaissVectorStore.load(self.index_path)
        ids, _ = reloaded.search([[0.1, 0.2]], k=1)
        self.assertEqual(ids[0][0], 1)


if __name__ == "__main__":
    unittest.main()
