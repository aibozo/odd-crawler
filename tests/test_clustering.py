from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

import tests._path  # noqa: F401

from oddcrawler.scoring import cluster_hdbscan, export_cluster_csv, reduce_umap


class ClusteringTests(unittest.TestCase):
    def test_reduce_umap_shape(self) -> None:
        data = np.random.RandomState(0).rand(10, 4).astype("float32")
        layout = reduce_umap(data, n_components=2, random_state=0)
        self.assertEqual(layout.shape, (10, 2))

    def test_cluster_hdbscan_identifies_cluster(self) -> None:
        rng = np.random.default_rng(42)
        cluster_a = rng.normal(loc=0.0, scale=0.1, size=(20, 4))
        cluster_b = rng.normal(loc=5.0, scale=0.1, size=(20, 4))
        data = np.vstack([cluster_a, cluster_b]).astype("float32")
        labels = cluster_hdbscan(data, min_cluster_size=5, min_samples=1)
        unique = set(labels)
        self.assertGreaterEqual(len(unique - {-1}), 2)

    def test_export_cluster_csv(self) -> None:
        ids = [1, 2, 3]
        layout = np.array([[0.1, 0.2], [0.2, 0.3], [0.3, 0.4]], dtype="float32")
        labels = [0, 0, 1]
        metadata = {1: {"title": "a"}, 2: {"title": "b"}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clusters.csv"
            export_cluster_csv(path, ids, layout, labels, metadata=metadata)
            with path.open("r", encoding="utf-8") as handle:
                content = handle.read()
        self.assertIn("id,x,y,cluster,title", content.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
