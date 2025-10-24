from __future__ import annotations

import unittest

import tests._path  # noqa: F401

from oddcrawler.crawler.frontier import Frontier, FrontierSettings


class FrontierSchedulerTests(unittest.TestCase):
    def test_ucb_prioritizes_high_reward_host(self) -> None:
        settings = FrontierSettings(
            weight_host_budget=0.0,
            weight_novelty=0.0,
            weight_bandit=1.0,
            weight_oddity=0.0,
            depth_penalty=0.0,
            host_refill_seconds=0.0,
            host_token_capacity=5.0,
            host_penalty_seconds=0.0,
            cross_domain_bonus=0.0,
            bandit_initial=0.5,
            bandit_exploration=0.3,
        )
        frontier = Frontier(settings=settings)
        frontier.add("https://b.test/1")
        frontier.add("https://a.test/1")

        first = frontier.pop()
        self.assertIsNotNone(first)
        assert first is not None
        frontier.record_feedback(first, score=0.1, action="skip")

        second = frontier.pop()
        self.assertIsNotNone(second)
        assert second is not None
        frontier.record_feedback(second, score=0.9, action="persist")

        frontier.add("https://b.test/2")
        frontier.add("https://a.test/2")

        next_url = frontier.pop()
        self.assertIsNotNone(next_url)
        assert next_url is not None
        self.assertTrue(next_url.startswith("https://a.test"))

    def test_failure_backoff_defers_host(self) -> None:
        settings = FrontierSettings(
            weight_host_budget=1.0,
            weight_novelty=0.0,
            weight_bandit=0.0,
            weight_oddity=0.0,
            depth_penalty=0.0,
            host_refill_seconds=0.0,
            host_token_capacity=5.0,
            host_penalty_seconds=0.0,
            failure_cooldown_seconds=30.0,
            cross_domain_bonus=0.0,
        )
        frontier = Frontier(settings=settings)
        frontier.add("https://a.test/1")
        frontier.add("https://b.test/1")

        first = frontier.pop()
        self.assertIsNotNone(first)
        assert first is not None
        frontier.record_failure(first, status_code=429)

        frontier.add("https://a.test/2")
        frontier.add("https://b.test/2")

        next_url = frontier.pop()
        self.assertIsNotNone(next_url)
        assert next_url is not None
        self.assertTrue(next_url.startswith("https://b.test"))

    def test_depth_penalty_prefers_shallow_urls(self) -> None:
        settings = FrontierSettings(
            weight_host_budget=0.0,
            weight_novelty=0.0,
            weight_bandit=0.0,
            weight_oddity=1.0,
            depth_penalty=0.2,
            host_refill_seconds=0.0,
            host_token_capacity=5.0,
            host_penalty_seconds=0.0,
            cross_domain_bonus=0.0,
        )
        frontier = Frontier(settings=settings)
        frontier.add("https://depth.test/root", depth=0, score_hint=0.8)
        frontier.add("https://depth.test/deep", depth=4, score_hint=0.8)

        next_url = frontier.pop()
        self.assertEqual(next_url, "https://depth.test/root")


if __name__ == "__main__":
    unittest.main()
