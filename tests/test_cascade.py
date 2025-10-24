from __future__ import annotations

import unittest

import tests._path  # noqa: F401

from oddcrawler.agents.cascade import CascadeDecision, TriageCascade


class CascadeTests(unittest.TestCase):
    def setUp(self) -> None:
        cascade_config = {
            "max_content_length": 500000,
            "min_content_length": 0,
            "snippet_bytes": 2048,
            "classifier_threshold": 0.25,
            "boring_keywords": ["insurance"],
        }
        prefilter_config = {"enabled": False}
        self.cascade = TriageCascade(config=cascade_config, prefilter_config=prefilter_config)

    def test_cascade_skips_boring_keyword(self) -> None:
        body = b"<html><body>We sell insurance policies and mortgage quotes every day.</body></html>"
        fetch_result = {"url": "https://boring.example", "headers": {"Content-Type": "text/html"}, "body": body}
        decision = self.cascade.evaluate(fetch_result)
        self.assertIsInstance(decision, CascadeDecision)
        self.assertTrue(decision.should_skip)
        self.assertTrue(any(stage.reason and "keyword" in stage.reason for stage in decision.stages))

    def test_cascade_passes_retro_page(self) -> None:
        body = b"<html><body><marquee>Odd zone</marquee><p>Long retro diary entry with webring badges and handcrafted ASCII art.</p></body></html>"
        fetch_result = {"url": "https://odd.example", "headers": {"Content-Type": "text/html"}, "body": body}
        decision = self.cascade.evaluate(fetch_result)
        self.assertFalse(decision.should_skip)

    def test_low_density_retro_triggers_warn_override(self) -> None:
        cascade = TriageCascade(
            config={
                "min_text_density": 0.02,
                "retro_override_score": 0.2,
                "snippet_bytes": 4096,
                "odd_keywords": ["webring"],
                "boring_keywords": [],
                "min_content_length": 0,
            },
            prefilter_config={"enabled": False},
        )
        body = b"<html><body><marquee>Odd</marquee><p>tiny retro webring</p></body></html>"
        decision = cascade.evaluate({"url": "https://retro.example", "headers": {"Content-Type": "text/html"}, "body": body})
        self.assertFalse(decision.should_skip)
        structure_stage = next(stage for stage in decision.stages if stage.stage == "structure")
        self.assertIn(structure_stage.status, {"warn", "pass"})


if __name__ == "__main__":
    unittest.main()
