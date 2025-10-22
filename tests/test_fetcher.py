from __future__ import annotations

import time
import unittest
from typing import Dict, Tuple
from urllib.parse import urlparse

import requests

import tests._path  # noqa: F401

from oddcrawler.crawler.fetcher import FetchError, Fetcher, RobotsDisallowed


class FakeResponse:
    def __init__(self, url: str, status_code: int, content: bytes = b"", headers: Dict[str, str] | None = None) -> None:
        self.url = url
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code} for {self.url}")


class FakeSession:
    def __init__(self, responses: Dict[str, FakeResponse], fail_first: bool = False) -> None:
        self.responses = responses
        self.fail_first = fail_first
        self.calls: Dict[str, int] = {}

    def get(self, url: str, headers: Dict[str, str], timeout: float):
        self.calls[url] = self.calls.get(url, 0) + 1
        if self.fail_first and self.calls[url] == 1 and "page" in url:
            raise requests.RequestException("temporary failure")
        if url not in self.responses:
            raise requests.RequestException(f"unexpected URL {url}")
        return self.responses[url]


class FetcherTests(unittest.TestCase):
    def test_robots_disallow(self) -> None:
        robots_body = b"User-agent: *\nDisallow: /blocked"
        session = FakeSession(
            {
                "https://example.com/robots.txt": FakeResponse("https://example.com/robots.txt", 200, robots_body),
            }
        )
        fetcher = Fetcher(session=session, obey_robots=True)
        with self.assertRaises(RobotsDisallowed):
            fetcher.fetch("https://example.com/blocked/page")

    def test_rate_limit_sleep_called(self) -> None:
        robots_body = b"User-agent: *\nAllow: /"
        responses = {
            "https://example.com/robots.txt": FakeResponse("https://example.com/robots.txt", 200, robots_body),
            "https://example.com/page": FakeResponse(
                "https://example.com/page", 200, b"<html><body>hi</body></html>", {"content-type": "text/html"}
            ),
        }
        sleep_calls: list[float] = []

        def fake_sleep(duration: float) -> None:
            sleep_calls.append(duration)

        session = FakeSession(responses)
        fetcher = Fetcher(
            session=session,
            obey_robots=True,
            per_host_requests_per_minute=60,
            sleep_func=fake_sleep,
        )
        fetcher.fetch("https://example.com/page")
        fetcher.fetch("https://example.com/page")
        self.assertTrue(sleep_calls)
        self.assertGreaterEqual(sleep_calls[0], 0.9)

    def test_retry_with_backoff(self) -> None:
        robots_body = b"User-agent: *\nAllow: /"
        responses = {
            "https://example.com/robots.txt": FakeResponse("https://example.com/robots.txt", 200, robots_body),
            "https://example.com/page": FakeResponse(
                "https://example.com/page", 200, b"<html><body>hi</body></html>", {"content-type": "text/html"}
            ),
        }
        sleep_calls: list[float] = []

        def fake_sleep(duration: float) -> None:
            sleep_calls.append(duration)

        session = FakeSession(responses, fail_first=True)
        fetcher = Fetcher(
            session=session,
            obey_robots=True,
            retries=1,
            backoff_bounds=(5, 5),
            sleep_func=fake_sleep,
        )
        fetcher.fetch("https://example.com/page")
        self.assertEqual(len(sleep_calls), 1)
        self.assertEqual(sleep_calls[0], 5)


if __name__ == "__main__":
    unittest.main()
