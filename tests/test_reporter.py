from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import tests._path  # noqa: F401

from oddcrawler.agents.reporter import Reporter
from oddcrawler.graph import GraphFeatureManager


class ReporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        base_dir = Path(self.tmpdir.name)
        self.config = {
            "base_dir": str(base_dir),
            "graphs": {"enabled": True, "path": "graphs"},
        }
        self.manager = GraphFeatureManager(storage_config=self.config)

    def test_graph_neighborhoods_returns_data(self) -> None:
        observation = {
            "url": "https://example.com/odd",
            "features": {"graph": {"webring_hits": 1}},
            "links": {
                "outbound": [
                    {
                        "url": "https://example.com/friend",
                        "anchor_text": "Odd friend",
                        "rel": [],
                        "found_at": "2025-03-03T00:00:00Z",
                    }
                ]
            },
            "extract": {"title": "Odd page"},
        }
        friend = {
            "url": "https://example.com/friend",
            "features": {"graph": {"webring_hits": 0}},
            "links": {"outbound": []},
            "extract": {"title": "Friend"},
        }
        self.manager.enrich_observation(observation, fetched_at="2025-03-03T00:00:00Z", status=200)
        self.manager.record_score("https://example.com/odd", 0.9, action="llm")
        self.manager.enrich_observation(friend, fetched_at="2025-03-03T01:00:00Z", status=200)
        self.manager.record_score("https://example.com/friend", 0.4, action="persist")

        reporter = Reporter(storage_config=self.config)
        neighborhoods = reporter.graph_neighborhoods(limit=2)
        self.assertTrue(neighborhoods)
        center = neighborhoods[0]["center"]
        self.assertIn("component_id", center)
        self.assertGreaterEqual(len(neighborhoods[0]["neighbors"]), 0)

    def test_topic_drift_summary(self) -> None:
        prev = [
            {"topic": 1, "representation": [("retro", 0.2), ("webring", 0.1)], "count": 5},
            {"topic": 2, "representation": [("paranormal", 0.3)], "count": 3},
        ]
        curr = [
            {"topic": 1, "representation": [("retro", 0.25), ("small web", 0.15)], "count": 7},
            {"topic": 3, "representation": [("arg", 0.2)], "count": 4},
        ]
        drift = Reporter.topic_drift_summary(prev, curr, top_terms=3)
        self.assertEqual(len(drift["updated_topics"]), 1)
        self.assertEqual(drift["updated_topics"][0]["topic"], 1)
        self.assertTrue(drift["new_topics"])
        self.assertTrue(drift["retired_topics"])


if __name__ == "__main__":
    unittest.main()

