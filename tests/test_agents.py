from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import tests._path  # noqa: F401

from oddcrawler.agents import AnalystResultProcessor, ScoreDecision, TriageOrchestrator


class StubLLM:
    def __init__(self, template: dict) -> None:
        self.template = template
        self.calls = 0

    def generate_analyst_finding(self, observation, *, extra_context=None):
        self.calls += 1
        result = dict(self.template)
        result.setdefault("url", observation.get("url"))
        fetched_at = observation.get("fetched_at", "unknown")
        result.setdefault("observation_ref", f"observation:{fetched_at}:stub")
        return result


class AnalystProcessorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        base_dir = Path(self.tmpdir.name)
        self.config = {
            "base_dir": str(base_dir),
            "excerpts": {"enabled": True, "path": "excerpts", "max_chars": 64, "ttl_days": None},
            "dangerous_breadcrumbs": {
                "enabled": True,
                "path": "dangerous",
                "max_excerpt_chars": 64,
                "sink": "local",
            },
            "salt_rotation": {"active_version": "2025Q1"},
        }

        self.stub_llm = StubLLM(
            {
                "url": "https://example.org/page",
                "summary": "Stub analyst summary",
                "why_flagged": ["stub"],
                "risk_tag": "unknown",
                "dangerous_content": {"present": False, "category": "none", "notes": ""},
                "confidence": 0.9,
            }
        )

        self.finding = {
            "url": "https://example.org/page",
            "why_flagged": ["bad things"],
            "dangerous_content": {"present": True, "category": "violent", "notes": "harmful"},
        }

        self.observation = {
            "url": "https://example.org/page",
            "fetched_at": "2025-03-01T00:00:00Z",
            "hashes": {"url_sha256": "ff00"},
            "extract": {"text_excerpt": "This is a long excerpt that should be truncated."},
            "salt_version": "2025Q1",
        }

    def test_process_records_breadcrumb_and_observation(self) -> None:
        processor = AnalystResultProcessor(storage_config=self.config, llm_client=self.stub_llm)
        result = processor.process(self.finding, observation=self.observation)

        self.assertIsNotNone(result.breadcrumb)
        self.assertIsNotNone(result.observation_path)
        assert result.observation_path is not None

        observation_file = Path(result.observation_path)
        self.assertTrue(observation_file.exists())
        with observation_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertIn("extract", data)
        self.assertTrue(len(data["extract"]["text_excerpt"]) <= 64)

        breadcrumb_dir = Path(self.config["base_dir"]) / "dangerous"
        files = list(breadcrumb_dir.glob("*.jsonl"))
        self.assertTrue(files)


class TriageOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        base_dir = Path(self.tmpdir.name)
        self.config = {
            "base_dir": str(base_dir),
            "excerpts": {"enabled": True, "path": "excerpts", "max_chars": 64, "ttl_days": None},
            "dangerous_breadcrumbs": {
                "enabled": True,
                "path": "dangerous",
                "max_excerpt_chars": 64,
                "sink": "local",
            },
            "salt_rotation": {"active_version": "2025Q1"},
        }
        self.stub_llm = StubLLM(
            {
                "summary": "Stub analyst summary",
                "why_flagged": ["stubbed"],
                "risk_tag": "unknown",
                "dangerous_content": {"present": True, "category": "other", "notes": "stub"},
                "confidence": 0.8,
            }
        )

        self.observation = {
            "url": "https://example.org/page",
            "fetched_at": "2025-03-01T00:00:00Z",
            "hashes": {"url_sha256": "ff00"},
            "extract": {"text_excerpt": "Observation excerpt text."},
            "salt_version": "2025Q1",
        }

        self.finding = {
            "url": "https://example.org/page",
            "why_flagged": ["bad things"],
            "dangerous_content": {"present": True, "category": "violent", "notes": "harmful"},
        }

    def test_handle_decision_persists_observation_and_invokes_analyst(self) -> None:
        orchestrator = TriageOrchestrator(storage_config=self.config, llm_client=self.stub_llm)
        decision = ScoreDecision(score=0.9, action="llm", thresholds_hit={"llm": 0.6})
        result = orchestrator.handle_decision(decision, observation=self.observation, finding=None)

        obs_path = result["observation_path"]
        self.assertIsNotNone(obs_path)
        assert obs_path is not None
        self.assertTrue(Path(obs_path).exists())

        analyst_result = result["analyst_result"]
        self.assertIsNotNone(analyst_result)
        assert analyst_result is not None
        self.assertIsNotNone(analyst_result.breadcrumb)

    def test_handle_decision_skip_does_not_call_analyst(self) -> None:
        orchestrator = TriageOrchestrator(storage_config=self.config, llm_client=self.stub_llm)
        decision = ScoreDecision(score=0.2, action="skip", thresholds_hit={})
        result = orchestrator.handle_decision(decision, observation=self.observation)

        self.assertIsNone(result["analyst_result"])


if __name__ == "__main__":
    unittest.main()
