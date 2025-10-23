from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import tests._path  # noqa: F401

from oddcrawler.prefilter import PrefilterEngine


def build_observation(text: str, outbound_urls: list[str] | None = None, token_count: int = 120) -> dict:
    return {
        "url": "https://example.com/page",
        "extract": {
            "text_excerpt": text,
            "token_count": token_count,
        },
        "links": {
            "outbound": [{"url": url} for url in (outbound_urls or [])]
        },
    }


class PrefilterTests(unittest.TestCase):
    def test_prefilter_flags_low_tokens(self) -> None:
        engine = PrefilterEngine(config={"enabled": True, "heuristics": {"min_token_count": 50}})
        decision = engine.evaluate(build_observation("short text", token_count=20))
        self.assertTrue(decision.should_skip)
        self.assertIn("token_count<50", decision.reasons[0])

    def test_prefilter_keyword_match(self) -> None:
        engine = PrefilterEngine(config={"enabled": True, "heuristics": {"boring_keywords": ["insurance"]}})
        decision = engine.evaluate(build_observation("This insurance policy covers everything."))
        self.assertTrue(decision.should_skip)
        self.assertTrue(any("keyword:insurance" in reason for reason in decision.reasons))

    def test_prefilter_same_domain_ratio(self) -> None:
        engine = PrefilterEngine(config={"enabled": True, "heuristics": {"max_same_domain_outbound_ratio": 0.5}})
        outbound = [
            "https://example.com/about",
            "https://example.com/contact",
            "https://other.com/page",
        ]
        decision = engine.evaluate(build_observation("Lots of internal links", outbound_urls=outbound))
        self.assertTrue(decision.should_skip)
        self.assertIn("outbound_same_domain", decision.reasons)

    def test_prefilter_disabled_bails_out(self) -> None:
        engine = PrefilterEngine(config={"enabled": False})
        decision = engine.evaluate(build_observation("any text"))
        self.assertFalse(decision.should_skip)
        self.assertEqual(decision.reasons, [])

    def test_prefilter_loads_yaml_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "prefilter.yaml"
            path.write_text(
                "enabled: true\nheuristics:\n  min_token_count: 10\n  boring_keywords: insurance, mortgage\n",
                encoding="utf-8",
            )
            engine = PrefilterEngine(config_path=path)
        decision = engine.evaluate(build_observation("insurance coverage", token_count=5))
        self.assertTrue(decision.should_skip)
        self.assertTrue(any(reason.startswith("token_count<10") for reason in decision.reasons))
        self.assertTrue(any("keyword:insurance" in reason for reason in decision.reasons))

    def test_prefilter_coerces_numeric_values(self) -> None:
        engine = PrefilterEngine(
            config={"enabled": True, "heuristics": {"min_token_count": "40", "max_same_domain_outbound_ratio": "0.75"}}
        )
        decision = engine.evaluate(build_observation("short", token_count=30))
        self.assertTrue(decision.should_skip)
        self.assertIn("token_count<40", decision.reasons[0])

    def test_prefilter_invalid_embedding_config_raises(self) -> None:
        with self.assertRaises(ValueError):
            PrefilterEngine(config={"embedding": {"odd_centroids": ["not-a-vector"]}})


if __name__ == "__main__":
    unittest.main()
