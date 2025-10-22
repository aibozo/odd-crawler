from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

import tests._path  # noqa: F401

from oddcrawler.agents.analyst import AnalystProcessingResult
from oddcrawler.agents.triage import ScoreDecision
from oddcrawler.crawler.fetcher import FetchHTTPError
from oddcrawler.crawler.frontier import Frontier
from oddcrawler.runtime import RunLoop
from oddcrawler.runner import RunnerResult


@dataclass
class StubRunner:
    results: List[RunnerResult]

    def __post_init__(self) -> None:
        self._index = 0
        self.seeded: List[str] = []

    def add_seeds(self, urls: Iterable[str]) -> None:
        self.seeded.extend(urls)

    def step(self) -> Optional[RunnerResult]:
        if self._index >= len(self.results):
            return None
        result = self.results[self._index]
        self._index += 1
        return result


class FaultyRunner:
    def __init__(self) -> None:
        self.called = 0

    def add_seeds(self, urls: Iterable[str]) -> None:  # pragma: no cover - trivial
        pass

    def step(self) -> Optional[RunnerResult]:
        self.called += 1
        if self.called == 1:
            raise RuntimeError("boom")
        return None


class RunnerWith404:
    def __init__(self, frontier: Frontier) -> None:
        self.frontier = frontier
        self.failure_cache = None  # type: ignore[assignment]
        self.calls = 0

    def add_seeds(self, urls: Iterable[str]) -> None:
        for url in urls:
            self.frontier.add(url)

    def step(self) -> Optional[RunnerResult]:
        url = self.frontier.pop()
        if not url:
            return None
        if self.failure_cache and self.failure_cache.should_skip(url):  # type: ignore[attr-defined]
            return None
        self.calls += 1
        if self.calls == 1:
            raise FetchHTTPError(404, url, "HTTP 404")
        return None


class RunLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.run_dir = Path(self.tmpdir.name) / "run"

    def _make_runner_results(self) -> List[RunnerResult]:
        decision1 = ScoreDecision(score=0.6, action="persist", thresholds_hit={"persist": 0.35}, reasons=["retro"])
        pipeline1 = {"observation_path": "obs1.json"}
        result1 = RunnerResult(
            url="https://example.com/a",
            decision=decision1,
            observation={"url": "https://example.com/a"},
            pipeline_result=pipeline1,
        )

        decision2 = ScoreDecision(score=0.92, action="llm", thresholds_hit={"llm": 0.6}, reasons=["odd cluster"])
        analyst_result = AnalystProcessingResult(
            finding={"observation_ref": "observation:123"},
            breadcrumb=None,
            observation_path="obs2.json",
        )
        pipeline2 = {
            "finding": {"observation_ref": "observation:123"},
            "analyst_result": analyst_result,
        }
        result2 = RunnerResult(
            url="https://example.com/b",
            decision=decision2,
            observation={"url": "https://example.com/b"},
            pipeline_result=pipeline2,
        )
        return [result1, result2]

    def test_run_loop_persists_metrics_and_events(self) -> None:
        frontier = Frontier()
        frontier.add("https://seed", priority=1.0)
        runner = StubRunner(results=self._make_runner_results())

        loop = RunLoop(
            runner=runner, frontier=frontier, run_dir=self.run_dir, checkpoint_interval=1, sleep_seconds=0.0
        )
        loop.run(seeds=["https://seed"], max_pages=2)

        telemetry_path = self.run_dir / "telemetry.jsonl"
        self.assertTrue(telemetry_path.exists())
        lines = [line.strip() for line in telemetry_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)

        metrics_path = self.run_dir / "metrics.json"
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        self.assertEqual(metrics["pages_processed"], 2)
        self.assertEqual(metrics["actions"]["persist"], 1)
        self.assertEqual(metrics["actions"]["llm"], 1)
        self.assertEqual(metrics["llm_calls"], 1)

        summary = json.loads((self.run_dir / "reports" / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["pages_processed"], 2)

        frontier_state = self.run_dir / "state" / "frontier.json"
        self.assertTrue(frontier_state.exists())

    def test_run_loop_logs_errors(self) -> None:
        frontier = Frontier()
        runner = FaultyRunner()
        loop = RunLoop(runner=runner, frontier=frontier, run_dir=self.run_dir, checkpoint_interval=1)
        loop.run(max_pages=1)

        metrics = json.loads((self.run_dir / "metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(metrics["errors"], 1)
        telemetry = (self.run_dir / "telemetry.jsonl").read_text(encoding="utf-8")
        self.assertIn("error", telemetry)

    def test_run_loop_records_404_failures(self) -> None:
        frontier = Frontier()
        runner = RunnerWith404(frontier)
        loop = RunLoop(runner=runner, frontier=frontier, run_dir=self.run_dir, checkpoint_interval=1)
        loop.run(seeds=["https://example.com/missing"], max_pages=1)

        # 404 should be cached and telemetry should log the event.
        failure_cache = loop.failure_cache
        self.assertTrue(failure_cache.should_skip("https://example.com/missing"))
        telemetry = (self.run_dir / "telemetry.jsonl").read_text(encoding="utf-8")
        self.assertIn("url_404", telemetry)
        metrics = json.loads((self.run_dir / "metrics.json").read_text(encoding="utf-8"))
        self.assertIn("example.com", metrics["failure_hosts"])
        summary = json.loads((self.run_dir / "reports" / "summary.json").read_text(encoding="utf-8"))
        self.assertTrue(summary["top_failure_hosts"])


if __name__ == "__main__":
    unittest.main()
