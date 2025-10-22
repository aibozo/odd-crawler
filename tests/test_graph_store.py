from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import tests._path  # noqa: F401

from oddcrawler.graph import GraphFeatureManager
from oddcrawler.storage import GraphStore, OutboundLink


class GraphStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        base_dir = Path(self.tmpdir.name)
        self.config = {
            "base_dir": str(base_dir),
            "graphs": {"enabled": True, "path": "graphs"},
        }

    def test_record_page_writes_graph_and_metrics(self) -> None:
        store = GraphStore(storage_config=self.config)
        out_link = OutboundLink(
            url="https://example.org/neighbor",
            anchor_text="Join my webring",
            rel=(),
            found_at="2025-03-01T00:00:00Z",
        )
        metrics = store.record_page(
            "https://example.org/page",
            fetched_at="2025-03-01T00:00:00Z",
            status=200,
            title="Example Page",
            links=[out_link],
            webring_hits=1,
        )
        self.assertGreater(metrics["score"], 0.0)
        store.update_score("https://example.org/page", 0.7, action="persist")

        graph_file = Path(self.config["base_dir"]) / "graphs" / "link_graph.json"
        self.assertTrue(graph_file.exists())

    def test_manager_enriches_observation(self) -> None:
        manager = GraphFeatureManager(storage_config=self.config)
        observation = {
            "url": "https://example.net/home",
            "features": {"graph": {"webring_hits": 1}},
            "links": {
                "outbound": [
                    {
                        "url": "https://example.net/neighbor",
                        "anchor_text": "Webring neighbor",
                        "rel": [],
                        "found_at": "2025-03-02T00:00:00Z",
                    }
                ]
            },
            "extract": {"title": "Home"},
        }

        enriched = manager.enrich_observation(
            observation,
            fetched_at="2025-03-02T00:00:00Z",
            status=200,
        )
        graph_features = enriched["features"]["graph"]
        self.assertGreaterEqual(graph_features["out_degree"], 0)
        self.assertIn("pagerank", graph_features)
        manager.record_score("https://example.net/home", 0.8, action="llm")


if __name__ == "__main__":
    unittest.main()

