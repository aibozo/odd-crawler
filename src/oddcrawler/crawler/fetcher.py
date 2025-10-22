"""Polite HTTP fetcher with robots/rate limiting support."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

import requests

from oddcrawler.agents.pipeline import FetchResult
from oddcrawler.crawler.tor_connector import TorConnector, TorPolicyError


class FetchError(Exception):
    """Raised when fetching a URL fails."""


class FetchHTTPError(FetchError):
    """Raised when HTTP status codes indicate failure."""

    def __init__(self, status_code: int, url: str, message: str) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.url = url


class RobotsDisallowed(FetchError):
    """Raised when robots.txt disallows a URL."""


class Fetcher:
    """Thin wrapper around `requests` that prepares `FetchResult` objects."""

    def __init__(
        self,
        *,
        user_agent: str = "Oddcrawler/0.1",
        timeout: float = 20.0,
        obey_robots: bool = True,
        per_host_requests_per_minute: Optional[int] = None,
        retries: int = 1,
        backoff_bounds: Optional[tuple[float, float]] = None,
        session: Optional[requests.Session] = None,
        sleep_func=time.sleep,
        tor_connector: Optional[TorConnector] = None,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.user_agent = user_agent
        self.obey_robots = obey_robots
        self.per_host_requests_per_minute = per_host_requests_per_minute
        self.min_interval = (
            60.0 / per_host_requests_per_minute if per_host_requests_per_minute and per_host_requests_per_minute > 0 else 0.0
        )
        self.retries = max(retries, 0)
        if backoff_bounds:
            self.backoff_bounds = (float(backoff_bounds[0]), float(backoff_bounds[1]))
        else:
            self.backoff_bounds = (1.0, 5.0)
        self.sleep = sleep_func
        self.robots_cache: Dict[str, Optional[RobotFileParser]] = {}
        self.last_request_at: Dict[str, float] = {}
        self.tor_connector = tor_connector

    def fetch(self, url: str) -> FetchResult:
        parsed = urlparse(url)
        host = parsed.netloc.lower()

        if self.obey_robots and not self._is_allowed(url, host):
            raise RobotsDisallowed(f"Blocked by robots.txt: {url}")

        attempt = 0
        last_error: Optional[requests.RequestException] = None
        proxies: Optional[Dict[str, str]] = None
        using_tor = False
        tor_connector = self.tor_connector if self.tor_connector and self.tor_connector.should_route(url) else None
        if tor_connector:
            try:
                tor_connector.before_request(url)
                proxies = tor_connector.proxies
                using_tor = True
            except TorPolicyError as exc:
                raise FetchError(str(exc)) from exc

        while attempt <= self.retries:
            try:
                self._enforce_rate_limit(host)
                request_kwargs = {
                    "headers": {"User-Agent": self.user_agent},
                    "timeout": self.timeout,
                }
                if proxies:
                    request_kwargs["proxies"] = proxies
                response = self.session.get(url, **request_kwargs)
                response.raise_for_status()
                fetched_at = datetime.now(timezone.utc).isoformat()
                url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
                result = FetchResult(
                    url=url,
                    url_hash=url_hash,
                    fetched_at=fetched_at,
                    headers=dict(response.headers),
                    body=response.content,
                )
                result.status = response.status_code  # type: ignore[attr-defined]
                self.last_request_at[host] = time.time()
                if using_tor:
                    tor_connector.record_success(url)
                return result
            except requests.RequestException as exc:
                if isinstance(exc, requests.HTTPError) and exc.response is not None:
                    last_error = FetchHTTPError(exc.response.status_code, url, str(exc))
                else:
                    last_error = FetchError(str(exc))
                attempt += 1
                if using_tor:
                    tor_connector.record_failure(url, reason=exc.__class__.__name__)
                if attempt > self.retries:
                    break
                self._backoff(attempt)

        if isinstance(last_error, FetchError):
            raise last_error
        raise FetchError(str(last_error) if last_error else f"Unable to fetch {url}")

    def _is_allowed(self, url: str, host: str) -> bool:
        parser = self._get_robot_parser(host, url)
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)

    def _get_robot_parser(self, host: str, url: str) -> Optional[RobotFileParser]:
        if host in self.robots_cache:
            return self.robots_cache[host]

        parser = RobotFileParser()
        robots_url = urljoin(f"{urlparse(url).scheme}://{host}", "/robots.txt")
        try:
            response = self.session.get(robots_url, headers={"User-Agent": self.user_agent}, timeout=self.timeout)
            if response.status_code >= 400:
                parser = None
            else:
                parser.parse(response.text.splitlines())
        except requests.RequestException:
            parser = None

        self.robots_cache[host] = parser
        return parser

    def _enforce_rate_limit(self, host: str) -> None:
        if self.min_interval <= 0:
            return
        last = self.last_request_at.get(host)
        if last is None:
            return
        now = time.time()
        wait = self.min_interval - (now - last)
        if wait > 0:
            self.sleep(wait)

    def _backoff(self, attempt: int) -> None:
        low, high = self.backoff_bounds
        delay = min(high, low + (high - low) * (attempt - 1) / max(self.retries, 1))
        if delay > 0:
            self.sleep(delay)


__all__ = ["Fetcher", "FetchError", "FetchHTTPError", "RobotsDisallowed"]
