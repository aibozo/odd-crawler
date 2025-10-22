"""Stem-powered Tor connector with per-host budgets and blocklisting."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional
from urllib.parse import urlsplit

try:
    from stem import Signal
    from stem.control import Controller  # type: ignore
except Exception:  # pragma: no cover - stem optional at runtime
    Controller = None  # type: ignore[assignment]
    Signal = None  # type: ignore[assignment]


class TorPolicyError(Exception):
    """Raised when Tor policy prevents a request."""


class TorBlockedHost(TorPolicyError):
    """Raised when a host is permanently blocked."""


class TorBudgetExceeded(TorPolicyError):
    """Raised when budgets or kill-switch prevent a request."""


@dataclass(frozen=True)
class BlockEntry:
    host: str
    blocked_until: Optional[str]
    reason: str

    def is_active(self, *, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if self.blocked_until is None:
            return True
        try:
            unblock_at = datetime.fromisoformat(self.blocked_until)
        except ValueError:
            return True
        return unblock_at > now


class TorConnector:
    """Manage Tor routing, budgets, and illegal content safeguards."""

    def __init__(
        self,
        *,
        enabled: bool,
        socks_host: str = "127.0.0.1",
        socks_port: int = 9050,
        control_port: Optional[int] = 9051,
        control_password: Optional[str] = None,
        per_host_requests_per_minute: Optional[int] = None,
        global_requests_per_minute: Optional[int] = None,
        failure_block_minutes: int = 30,
        max_failures_per_host: int = 3,
        illegal_block_days: int = 365,
        blocklist_path: Path | str | None = None,
        route_domains: Iterable[str] | None = None,
        route_onion_only: bool = True,
        sleep_func=time.sleep,
    ) -> None:
        self.enabled = enabled
        self.socks_host = socks_host
        self.socks_port = int(socks_port)
        self.control_port = control_port
        self.control_password = control_password
        self.failure_block_minutes = max(failure_block_minutes, 1)
        self.max_failures_per_host = max(max_failures_per_host, 1)
        self.illegal_block_days = max(illegal_block_days, 1)
        self.route_onion_only = route_onion_only
        self.route_domains = {domain.lower() for domain in route_domains or []}

        self.per_host_interval = (
            60.0 / per_host_requests_per_minute if per_host_requests_per_minute and per_host_requests_per_minute > 0 else 0.0
        )
        self.global_interval = (
            60.0 / global_requests_per_minute if global_requests_per_minute and global_requests_per_minute > 0 else 0.0
        )

        self.sleep = sleep_func
        self.host_last_request: Dict[str, float] = {}
        self.global_last_request: float = 0.0
        self.host_failures: Dict[str, int] = {}

        default_blocklist = Path("var/oddcrawler/tor/blocklist.json")
        self.blocklist_path = Path(blocklist_path) if blocklist_path else default_blocklist
        if not self.blocklist_path.parent.exists():
            self.blocklist_path.parent.mkdir(parents=True, exist_ok=True)
        self.blocklist: Dict[str, BlockEntry] = {}
        self._load_blocklist()

        self._controller = None
        if self.enabled and Controller and self.control_port:
            try:
                controller = Controller.from_port(port=self.control_port)
                if self.control_password:
                    controller.authenticate(password=self.control_password)
                else:
                    controller.authenticate()
                self._controller = controller
            except Exception:
                self._controller = None

    # ------------------------------------------------------------------ #
    # Public interface
    # ------------------------------------------------------------------ #
    def should_route(self, url: str) -> bool:
        if not self.enabled:
            return False
        host = urlsplit(url).netloc.lower()
        if host.endswith(".onion"):
            return True
        if self.route_onion_only:
            return host in self.route_domains
        if self.route_domains and host in self.route_domains:
            return True
        return False

    @property
    def proxies(self) -> Dict[str, str]:
        return {
            "http": f"socks5h://{self.socks_host}:{self.socks_port}",
            "https": f"socks5h://{self.socks_host}:{self.socks_port}",
        }

    def before_request(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        self._ensure_not_blocked(host)
        self._enforce_budgets(host)

    def record_success(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        now = time.time()
        self.host_last_request[host] = now
        self.global_last_request = now
        if host in self.host_failures:
            self.host_failures.pop(host, None)

    def record_failure(self, url: str, reason: str | None = None) -> None:
        host = urlsplit(url).netloc.lower()
        failures = self.host_failures.get(host, 0) + 1
        self.host_failures[host] = failures
        if failures >= self.max_failures_per_host:
            until = datetime.now(timezone.utc) + timedelta(minutes=self.failure_block_minutes)
            self._block_host(
                host,
                reason or "excessive_failures",
                blocked_until=until,
            )
            self.host_failures.pop(host, None)

    def record_illegal(self, url: str, reason: str) -> None:
        host = urlsplit(url).netloc.lower()
        until = datetime.now(timezone.utc) + timedelta(days=self.illegal_block_days)
        reason_text = f"illegal:{reason}" if reason else "illegal:detected"
        self._block_host(host, reason_text, blocked_until=until)

    def renew_identity(self) -> bool:
        if not self._controller or not Signal:  # pragma: no cover - depends on runtime tor
            return False
        try:
            self._controller.signal(Signal.NEWNYM)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _enforce_budgets(self, host: str) -> None:
        now = time.time()
        if self.per_host_interval > 0:
            last = self.host_last_request.get(host)
            if last:
                wait = self.per_host_interval - (now - last)
                if wait > 0:
                    self.sleep(wait)
        if self.global_interval > 0 and self.global_last_request:
            wait = self.global_interval - (now - self.global_last_request)
            if wait > 0:
                self.sleep(wait)

    def _ensure_not_blocked(self, host: str) -> None:
        entry = self.blocklist.get(host)
        if not entry:
            return
        if entry.is_active():
            if str(entry.reason).startswith("illegal"):
                raise TorBlockedHost(f"Host blocked permanently due to illegal content: {host}")
            raise TorBudgetExceeded(f"Host temporarily blocked: {host}")
        # expired entry cleanup
        self.blocklist.pop(host, None)
        self._persist_blocklist()

    def _block_host(self, host: str, reason: str, *, blocked_until: Optional[datetime]) -> None:
        until_str = blocked_until.astimezone(timezone.utc).isoformat() if blocked_until else None
        entry = BlockEntry(host=host, blocked_until=until_str, reason=reason)
        self.blocklist[host] = entry
        self._persist_blocklist()

    def _load_blocklist(self) -> None:
        if not self.blocklist_path.exists():
            return
        try:
            with self.blocklist_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError):
            data = []
        now = datetime.now(timezone.utc)
        for item in data or []:
            host = str(item.get("host", "")).lower()
            if not host:
                continue
            entry = BlockEntry(
                host=host,
                blocked_until=item.get("blocked_until"),
                reason=str(item.get("reason") or "unknown"),
            )
            if entry.is_active(now=now):
                self.blocklist[host] = entry

    def _persist_blocklist(self) -> None:
        payload: list[dict[str, Any]] = []
        for entry in self.blocklist.values():
            payload.append(
                {
                    "host": entry.host,
                    "blocked_until": entry.blocked_until,
                    "reason": entry.reason,
                }
            )
        tmp_path = self.blocklist_path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        tmp_path.replace(self.blocklist_path)


__all__ = ["TorConnector", "TorPolicyError", "TorBlockedHost", "TorBudgetExceeded", "BlockEntry"]
