from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import tests._path  # noqa: F401

from oddcrawler.agents import FetchResult, OddcrawlerPipeline, ScoreDecision, TriageOrchestrator


class StubLLM:
    def __init__(self) -> None:
        self.calls = 0

    def generate_analyst_finding(self, observation, *, extra_context=None):
        self.calls += 1
        fetched_at = observation.get("fetched_at", "unknown")
        return {
            "url": observation.get("url"),
            "summary": "Stub summary",
            "why_flagged": ["stubbed"],
            "risk_tag": "unknown",
            "dangerous_content": {"present": True, "category": "other", "notes": "stub"},
            "confidence": 0.5,
            "observation_ref": f"observation:{fetched_at}:stub",
        }


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        base_dir = Path(self.tmpdir.name)
        self.config = {
            "base_dir": str(base_dir),
            "raw_html": {
                "enabled": True,
                "path": "raw",
                "ttl_days": 30,
            },
            "excerpts": {
                "enabled": True,
                "path": "excerpts",
                "max_chars": 64,
                "ttl_days": None,
            },
            "dangerous_breadcrumbs": {
                "enabled": True,
                "path": "dangerous",
                "max_excerpt_chars": 64,
                "sink": "local",
            },
            "salt_rotation": {"active_version": "2025Q1"},
        }

        self.stub_llm = StubLLM()
        triage = TriageOrchestrator(storage_config=self.config, llm_client=self.stub_llm)
        self.pipeline = OddcrawlerPipeline(triage=triage)

        self.fetch_result = FetchResult(
            url="https://example.org/page",
            url_hash="abcd",
            fetched_at="2025-03-01T00:00:00Z",
            headers={"content-type": "text/html"},
            body=b"<html>hello</html>",
        )

        self.observation = {
            "url": "https://example.org/page",
            "fetched_at": "2025-03-01T00:00:00Z",
            "hashes": {"url_sha256": "abcd"},
            "extract": {"text_excerpt": "Observation text"},
            "salt_version": "2025Q1",
        }

        self.finding = {
            "url": "https://example.org/page",
            "why_flagged": ["odd content"],
            "dangerous_content": {"present": True, "category": "other", "notes": "weird"},
        }

    def test_pipeline_records_raw_and_handles_scored_observation(self) -> None:
        self.pipeline.record_fetch(self.fetch_result)

        raw_dir = Path(self.config["base_dir"]) / "raw" / self.fetch_result.url_hash[:2]
        self.assertTrue(raw_dir.exists())
        files = list(raw_dir.glob("*.html"))
        self.assertTrue(files)

        decision = ScoreDecision(score=0.8, action="llm", thresholds_hit={"llm": 0.6})
        result = self.pipeline.handle_scored_observation(
            self.observation,
            decision,
            finding=None,
        )

        observation_path = result["observation_path"]
        self.assertIsNotNone(observation_path)
        assert observation_path is not None
        with Path(observation_path).open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertIn("extract", data)

        breadcrumb_dir = Path(self.config["base_dir"]) / "dangerous"
        self.assertTrue(list(breadcrumb_dir.glob("*.jsonl")))
        self.assertEqual(self.stub_llm.calls, 1)


if __name__ == "__main__":
    unittest.main()
