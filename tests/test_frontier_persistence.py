from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import tests._path  # noqa: F401

from oddcrawler.crawler.frontier import Frontier, FrontierSettings


class FrontierPersistenceTests(unittest.TestCase):
    def test_frontier_save_and_load_roundtrip(self) -> None:
        settings = FrontierSettings(host_refill_seconds=0.0, host_token_capacity=10.0, host_penalty_seconds=0.0)
        frontier = Frontier(settings=settings)
        urls = [
            ("https://example.com/a", 0.5),
            ("https://example.com/b", 0.8),
            ("https://example.com/c", 0.1),
        ]
        for url, priority in urls:
            frontier.add(url, priority=priority)

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        state_path = Path(tmpdir.name) / "frontier.json"
        frontier.save(state_path)

        loaded = Frontier.load(state_path, settings=settings)
        seen_urls = set()
        popped = []
        while True:
            url = loaded.pop()
            if url is None:
                break
            popped.append(url)
            seen_urls.add(url)
            loaded.record_feedback(url, score=0.5, action="persist", cascade_skip=False)

        self.assertGreater(len(popped), 0)
        self.assertTrue(seen_urls.issubset({u for u, _ in urls}))

    def test_frontier_load_invalid(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        state_path = Path(tmpdir.name) / "frontier.json"
        state_path.write_text("[]", encoding="utf-8")
        with self.assertRaises(ValueError):
            Frontier.load(state_path)


if __name__ == "__main__":
    unittest.main()
