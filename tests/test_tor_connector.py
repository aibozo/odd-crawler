from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

import tests._path  # noqa: F401

from oddcrawler.crawler.tor_connector import TorBlockedHost, TorConnector, TorPolicyError


class TorConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.blocklist_path = Path(self.tmpdir.name) / "blocklist.json"

    def _connector(self, **overrides):
        params = {
            "enabled": True,
            "socks_host": "127.0.0.1",
            "socks_port": 9050,
            "per_host_requests_per_minute": 0,
            "global_requests_per_minute": 0,
            "blocklist_path": self.blocklist_path,
            "route_domains": ["example.onion"],
            "route_onion_only": True,
            "sleep_func": lambda _: None,
        }
        params.update(overrides)
        return TorConnector(**params)

    def test_should_route_and_proxies(self) -> None:
        connector = self._connector()
        self.assertTrue(connector.should_route("http://mysite.onion/page"))
        self.assertFalse(connector.should_route("https://example.com"))
        proxies = connector.proxies
        self.assertIn("socks5h://127.0.0.1:9050", proxies.values())

    def test_illegal_block_persists(self) -> None:
        connector = self._connector()
        connector.record_illegal("http://mysite.onion/page", "illegal")
        with self.assertRaises(TorBlockedHost):
            connector.before_request("http://mysite.onion/page")

        # reload from disk to ensure persistence
        connector2 = self._connector()
        with self.assertRaises(TorBlockedHost):
            connector2.before_request("http://mysite.onion/page")

    def test_failure_block_releases(self) -> None:
        connector = self._connector(max_failures_per_host=1, failure_block_minutes=1)
        connector.record_failure("http://mysite.onion/page", reason="timeout")
        with self.assertRaises(TorPolicyError):
            connector.before_request("http://mysite.onion/page")


if __name__ == "__main__":
    unittest.main()

