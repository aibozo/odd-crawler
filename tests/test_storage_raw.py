from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import yaml

import tests._path  # noqa: F401

from oddcrawler.storage.raw_store import write_observation_excerpt, write_raw_response
from scripts.purge_storage import purge_storage


class RawStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.base_dir = Path(self.tmpdir.name)
        self.config = {
            "base_dir": str(self.base_dir),
            "raw_html": {"enabled": True, "path": "raw_html", "ttl_days": 30},
            "excerpts": {"enabled": True, "path": "excerpts", "max_chars": 32, "ttl_days": None},
            "dangerous_breadcrumbs": {"enabled": False},
        }

        self.observation = {
            "url": "https://example.org",
            "fetched_at": "2025-03-01T00:00:00Z",
            "hashes": {"url_sha256": "aabb"},
            "extract": {"text_excerpt": "x" * 100},
        }

    def test_write_raw_response_creates_files(self) -> None:
        result = write_raw_response(
            "aabb",
            content=b"<html>ok</html>",
            headers={"content-type": "text/html"},
            fetched_at="2025-03-01T00:00:00Z",
            config=self.config,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.html_path.exists())
        self.assertTrue(result.meta_path.exists())
        with result.meta_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data["url_hash"], "aabb")

    def test_write_observation_excerpt_truncates_text(self) -> None:
        path = write_observation_excerpt(self.observation, config=self.config)
        self.assertIsNotNone(path)
        assert path is not None
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertLessEqual(len(data["extract"]["text_excerpt"]), 32)

    def test_purge_deletes_expired_raw_files(self) -> None:
        result = write_raw_response(
            "aabb",
            content=b"<html>ok</html>",
            headers={"content-type": "text/html"},
            fetched_at="2025-03-01T00:00:00Z",
            config=self.config,
        )
        assert result is not None
        old_time = time.time() - (45 * 24 * 3600)
        os.utime(result.html_path, (old_time, old_time))
        os.utime(result.meta_path, (old_time, old_time))

        config_path = self.base_dir / "storage.yaml"
        config_data = {
            "version": 1,
            "base_dir": str(self.base_dir),
            "raw_html": {"enabled": True, "path": "raw_html", "ttl_days": 30},
            "excerpts": {"enabled": True, "path": "excerpts", "ttl_days": None},
            "vectors": {"enabled": False, "path": "vectors", "ttl_days": None},
            "graphs": {"enabled": False, "path": "graphs", "ttl_days": None},
            "dangerous_breadcrumbs": {"enabled": False, "path": "dangerous", "ttl_days": None},
        }
        with config_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(config_data, handle)

        purge_storage(config_path, dry_run=False)
        self.assertFalse(result.html_path.exists())
        self.assertFalse(result.meta_path.exists())


if __name__ == "__main__":
    unittest.main()
