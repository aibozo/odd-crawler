from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tests._path  # noqa: F401

from oddcrawler.runtime.failure_cache import FailureCache


class FailureCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.cache_path = Path(self.tmpdir.name) / "failures.json"

    def test_should_skip_and_persist(self) -> None:
        cache = FailureCache(self.cache_path, expiry_seconds=None)
        cache.record("https://example.com/missing", 404, "http_404")
        self.assertTrue(cache.should_skip("https://example.com/missing"))
        cache.save()

        cache2 = FailureCache(self.cache_path, expiry_seconds=None)
        self.assertTrue(cache2.should_skip("https://example.com/missing"))

    def test_expiry_removes_entry(self) -> None:
        cache = FailureCache(self.cache_path, expiry_seconds=1)
        cache.record("https://example.com/missing", 404, "http_404")
        entry = cache.entries()["https://example.com/missing"]
        past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        entry.last_recorded_at = past
        cache.save()

        cache2 = FailureCache(self.cache_path, expiry_seconds=1)
        self.assertFalse(cache2.should_skip("https://example.com/missing"))
        self.assertEqual(len(cache2), 0)


if __name__ == "__main__":
    unittest.main()

