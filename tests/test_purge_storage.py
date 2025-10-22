from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

import yaml

import tests._path  # noqa: F401

from scripts.purge_storage import purge_storage


class PurgeStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name)
        self.config_dir = self.root / "config"
        self.config_dir.mkdir()
        self.storage_root = self.root / "storage"
        self.storage_root.mkdir()

        self.config_path = self.config_dir / "storage.yaml"
        config = {
            "version": 1,
            "base_dir": str(self.storage_root),
            "raw_html": {"enabled": True, "path": "raw_html", "ttl_days": 30},
            "excerpts": {"enabled": True, "path": "excerpts", "ttl_days": None},
            "vectors": {"enabled": False, "path": "vectors", "ttl_days": None},
            "graphs": {"enabled": False, "path": "graphs", "ttl_days": None},
            "dangerous_breadcrumbs": {"enabled": True, "path": "dangerous", "ttl_days": 90},
        }
        with self.config_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(config, handle)

        self.raw_html = self.storage_root / "raw_html"
        self.raw_html.mkdir()
        self.excerpts = self.storage_root / "excerpts"
        self.excerpts.mkdir()
        self.dangerous = self.storage_root / "dangerous"
        self.dangerous.mkdir()

        self.old_file = self.raw_html / "old.html"
        self.old_file.write_text("old", encoding="utf-8")
        past = time.time() - (40 * 24 * 3600)  # 40 days ago
        os.utime(self.old_file, (past, past))

        self.new_file = self.raw_html / "new.html"
        self.new_file.write_text("new", encoding="utf-8")

    def test_dry_run_lists_targets_without_deleting(self) -> None:
        results = purge_storage(self.config_path, dry_run=True)
        raw_html_result = next(res for res in results if res.section == "raw_html")
        self.assertIn(self.old_file, raw_html_result.removed)
        self.assertIn("ttl_unset", {res.skipped_reason for res in results if res.section == "excerpts"})
        self.assertTrue(self.old_file.exists())
        self.assertTrue(self.new_file.exists())

    def test_purge_removes_expired_files(self) -> None:
        results = purge_storage(self.config_path, dry_run=False)
        raw_html_result = next(res for res in results if res.section == "raw_html")
        self.assertIn(self.old_file, raw_html_result.removed)
        self.assertFalse(self.old_file.exists())
        self.assertTrue(self.new_file.exists())
        dangerous_result = next(res for res in results if res.section == "dangerous_breadcrumbs")
        self.assertEqual(dangerous_result.removed, [])


if __name__ == "__main__":
    unittest.main()
