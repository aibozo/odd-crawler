from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import tests._path  # noqa: F401

from oddcrawler.storage.compliance import maybe_record_breadcrumb


class ComplianceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.base_dir = Path(self.tmpdir.name)

        self.config = {
            "base_dir": str(self.base_dir),
            "dangerous_breadcrumbs": {
                "enabled": True,
                "path": "dangerous",
                "max_excerpt_chars": 32,
                "sink": "local",
                "ttl_days": None,
            },
            "salt_rotation": {"active_version": "2025Q1"},
        }

        self.finding = {
            "url": "https://example.net/post",
            "why_flagged": ["violent rhetoric detected"],
            "dangerous_content": {"present": True, "category": "violent", "notes": "explicit calls"},
        }

        self.observation = {
            "url": "https://example.net/post",
            "fetched_at": "2025-02-01T00:00:00Z",
            "hashes": {"url_sha256": "deadbeef"},
            "extract": {"text_excerpt": "Lorem ipsum dolor sit amet " * 4},
            "salt_version": "2025Q1",
        }

    def test_maybe_record_breadcrumb_persists_file(self) -> None:
        breadcrumb = maybe_record_breadcrumb(self.finding, observation=self.observation, config=self.config)
        self.assertIsNotNone(breadcrumb)
        assert breadcrumb is not None
        self.assertEqual(breadcrumb.url_hash, "deadbeef")
        self.assertEqual(breadcrumb.category, "violent")
        self.assertEqual(breadcrumb.reason, "explicit calls")
        self.assertEqual(breadcrumb.salt_version, "2025Q1")
        self.assertIsNotNone(breadcrumb.excerpt_redacted)
        self.assertLessEqual(len(breadcrumb.excerpt_redacted or ""), 32)
        self.assertIsNotNone(breadcrumb.observed_at.tzinfo)

        expected_file = Path(self.base_dir, "dangerous", breadcrumb.observed_at.date().isoformat() + ".jsonl")
        self.assertTrue(expected_file.exists())

        with expected_file.open("r", encoding="utf-8") as handle:
            line = handle.readline().strip()
        data = json.loads(line)
        self.assertEqual(data["url_hash"], "deadbeef")
        self.assertEqual(data["salt_version"], "2025Q1")
        self.assertIn("observed_at", data)

    def test_maybe_record_breadcrumb_skips_without_flag(self) -> None:
        finding = {
            "url": "https://example.net/post",
            "dangerous_content": {"present": False, "category": "none", "notes": ""},
        }
        breadcrumb = maybe_record_breadcrumb(finding, observation=self.observation, config=self.config)
        self.assertIsNone(breadcrumb)

        output_dir = Path(self.base_dir, "dangerous")
        self.assertFalse(output_dir.exists())


if __name__ == "__main__":
    unittest.main()
