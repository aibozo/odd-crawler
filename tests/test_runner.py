from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

import tests._path  # noqa: F401

from oddcrawler.agents.pipeline import FetchResult
from oddcrawler.agents import OddcrawlerPipeline, TriageOrchestrator
from oddcrawler.runner import OddcrawlerRunner


class StubLLM:
    def __init__(self) -> None:
        self.calls = 0

    def generate_analyst_finding(self, observation, *, extra_context=None):
        self.calls += 1
        fetched_at = observation.get("fetched_at", "unknown")
        return {
            "url": observation.get("url"),
            "summary": "Runner stub summary",
            "why_flagged": ["stubbed"],
            "risk_tag": "unknown",
            "dangerous_content": {"present": False, "category": "none", "notes": ""},
            "confidence": 0.7,
            "observation_ref": f"observation:{fetched_at}:stub",
        }


@dataclass
class StubFetcher:
    body: bytes

    def fetch(self, url: str) -> FetchResult:
        result = FetchResult(
            url=url,
            url_hash="stubhash",
            fetched_at="2025-03-01T00:00:00Z",
            headers={"content-type": "text/html"},
            body=self.body,
        )
        result.status = 200  # type: ignore[attr-defined]
        return result


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        base_dir = Path(self.tmpdir.name)

        storage_config = {
            "base_dir": str(base_dir),
            "raw_html": {"enabled": True, "path": "raw", "ttl_days": 30},
            "excerpts": {"enabled": True, "path": "excerpts", "max_chars": 64, "ttl_days": None},
            "dangerous_breadcrumbs": {"enabled": True, "path": "dangerous", "max_excerpt_chars": 64, "sink": "local"},
            "salt_rotation": {"active_version": "2025Q1"},
        }
        self.stub_llm = StubLLM()
        triage = TriageOrchestrator(storage_config=storage_config, llm_client=self.stub_llm)
        pipeline = OddcrawlerPipeline(triage=triage)

        document = """
        <html>
          <head><title>Retro</title></head>
          <body>
            <marquee>Welcome to my page</marquee>
            <p>This page is odd.</p>
          </body>
        </html>
        """.encode("utf-8")
        self.runner = OddcrawlerRunner(pipeline=pipeline, fetcher=StubFetcher(document))

    def test_runner_produces_results(self) -> None:
        self.runner.add_seeds(["https://example.org/page"])
        results = self.runner.run(max_pages=1)
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertGreaterEqual(result.decision.score, 0.5)
        self.assertIn(result.decision.action, {"persist", "llm"})

        raw_dir = Path(self.runner.pipeline.triage.config["base_dir"]) / "raw" / "st"
        self.assertTrue(raw_dir.exists())

        observation_path = result.pipeline_result["observation_path"]
        self.assertIsNotNone(observation_path)
        with Path(observation_path).open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertIn("features", data)
        if result.decision.action == "llm":
            self.assertEqual(self.stub_llm.calls, 1)
        else:
            self.assertEqual(self.stub_llm.calls, 0)

    def test_runner_blocks_illegal_content(self) -> None:
        other_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(other_tmp.cleanup)
        base_dir = Path(other_tmp.name)
        storage_config = {
            "base_dir": str(base_dir),
            "raw_html": {"enabled": True, "path": "raw", "ttl_days": 30},
            "excerpts": {"enabled": True, "path": "excerpts", "max_chars": 64, "ttl_days": None},
            "dangerous_breadcrumbs": {
                "enabled": True,
                "path": "dangerous",
                "max_excerpt_chars": 64,
                "sink": "local",
            },
            "salt_rotation": {"active_version": "2025Q1"},
        }
        pipeline = OddcrawlerPipeline(triage=TriageOrchestrator(storage_config=storage_config, llm_client=self.stub_llm))
        document = """
        <html><body>
            This forum distributes child sexual abuse material illegally.
        </body></html>
        """.encode("utf-8")
        runner = OddcrawlerRunner(
            pipeline=pipeline,
            fetcher=StubFetcher(document),
            config={
                "crawl": {},
                "safety": {
                    "illegal_content": {"keywords": ["child sexual abuse"], "min_keyword_matches": 1}
                },
            },
        )
        runner.add_seeds(["http://mysite.onion/illegal"])
        results = runner.run(max_pages=1)
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertTrue(result.pipeline_result.get("illegal"))
        self.assertEqual(result.decision.action, "skip")
        raw_dir = base_dir / "raw"
        self.assertFalse(raw_dir.exists())


if __name__ == "__main__":
    unittest.main()
