from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import tests._path  # noqa: F401

from oddcrawler.agents.triage import ScoreDecision
from oddcrawler.agents.cascade import CascadeDecision, CascadeStageResult
from oddcrawler.crawler.frontier import Frontier
from oddcrawler.runner import RunnerResult
from oddcrawler.runtime.run_loop import RunLoop


class StubRunner:
    def __init__(self, result: RunnerResult) -> None:
        self._result = result
        self._emitted = False
        self.failure_cache = None

    def add_seeds(self, urls) -> None:  # pragma: no cover - seeds unused in test
        pass

    def step(self):
        if not self._emitted:
            self._emitted = True
            return self._result
        return None


class RunLoopMetricsTests(unittest.TestCase):
    def test_run_loop_updates_baseline_metrics(self) -> None:
        fetch_metrics = {
            "status": 200,
            "duration_ms": 120.0,
            "bytes_downloaded": 2048,
            "via_tor": False,
            "fetched_at": "2025-03-01T00:00:00Z",
        }
        decision = ScoreDecision(score=0.6, action="persist", thresholds_hit={"persist": 0.3}, reasons=["retro"])
        observation = {"url": "https://example.org", "fetch_metrics": fetch_metrics}
        pipeline_result = {"observation_path": None}
        cascade = CascadeDecision(
            should_skip=False,
            stages=[CascadeStageResult(stage="classifier", status="pass")],
            final_reason=None,
        )

        runner_result = RunnerResult(
            url="https://example.org",
            decision=decision,
            observation=observation,
            pipeline_result=pipeline_result,
            fetch_metrics=fetch_metrics,
            cascade_result=cascade,
        )

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        run_dir = Path(tmpdir.name) / "run"

        runner = StubRunner(runner_result)
        frontier = Frontier()

        loop = RunLoop(runner=runner, frontier=frontier, run_dir=run_dir, checkpoint_interval=1)
        loop.run(seeds=[], max_pages=1)

        metrics = loop.metrics
        self.assertEqual(metrics["pages_processed"], 1)
        self.assertEqual(metrics["fetch_stats"]["requests"], 1)
        self.assertEqual(metrics["fetch_stats"]["total_bytes"], 2048)
        self.assertEqual(metrics["odd_hits"]["total"], 1)
        self.assertEqual(metrics["odd_hits"]["ratio"], 1.0)
        self.assertEqual(metrics["cost"]["bandwidth_bytes"], 2048)
        self.assertIn("crawl_rate_per_minute", metrics["timing"])


if __name__ == "__main__":
    unittest.main()
