"""Priority frontier with bandit scheduling and host politeness controls."""

from __future__ import annotations

import heapq
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit


@dataclass
class FrontierSettings:
    """Configuration knobs for the priority frontier."""

    weight_host_budget: float = 0.35
    weight_novelty: float = 0.25
    weight_bandit: float = 0.25
    weight_oddity: float = 0.15
    depth_penalty: float = 0.05
    novelty_decay: float = 6.0
    min_priority: float = 0.05
    max_priority: float = 1.0
    cross_domain_bonus: float = 0.05
    host_token_capacity: float = 1.0
    host_refill_seconds: float = 10.0
    host_penalty_seconds: float = 1.0
    failure_cooldown_seconds: float = 45.0
    bandit_initial: float = 0.6
    bandit_exploration: float = 0.25
    oddity_baseline: float = 0.5
    cascade_skip_threshold: float = 0.8
    cascade_penalty: float = 0.15
    cascade_min_observations: int = 5

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any] | None = None,
        *,
        crawl: Mapping[str, Any] | None = None,
    ) -> "FrontierSettings":
        cfg = dict(config or {})
        weights_cfg = cfg.get("weights", {})
        crawl_cfg = crawl or {}
        per_host_rpm = float(crawl_cfg.get("per_host_requests_per_minute", 0) or 0)
        if per_host_rpm > 0:
            refill_seconds = 60.0 / per_host_rpm
        else:
            refill_seconds = float(cfg.get("host_refill_seconds", cls.host_refill_seconds))
        failure_cooldown = float(cfg.get("failure_cooldown_seconds", max(refill_seconds * 3.0, cls.failure_cooldown_seconds)))
        return cls(
            weight_host_budget=float(weights_cfg.get("host_budget", cls.weight_host_budget)),
            weight_novelty=float(weights_cfg.get("novelty", cls.weight_novelty)),
            weight_bandit=float(weights_cfg.get("bandit", cls.weight_bandit)),
            weight_oddity=float(weights_cfg.get("oddity_prior", cls.weight_oddity)),
            depth_penalty=float(cfg.get("depth_penalty", cls.depth_penalty)),
            novelty_decay=float(cfg.get("novelty_decay", cls.novelty_decay)),
            min_priority=float(cfg.get("min_priority", cls.min_priority)),
            max_priority=float(cfg.get("max_priority", cls.max_priority)),
            cross_domain_bonus=float(cfg.get("cross_domain_bonus", cls.cross_domain_bonus)),
            host_token_capacity=float(cfg.get("host_token_capacity", cls.host_token_capacity)),
            host_refill_seconds=float(cfg.get("host_refill_seconds", refill_seconds if refill_seconds > 0 else cls.host_refill_seconds)),
            host_penalty_seconds=float(cfg.get("host_penalty_seconds", cls.host_penalty_seconds)),
            failure_cooldown_seconds=failure_cooldown,
            bandit_initial=float(cfg.get("bandit_initial", cls.bandit_initial)),
            bandit_exploration=float(cfg.get("bandit_exploration", cls.bandit_exploration)),
            oddity_baseline=float(cfg.get("oddity_baseline", cls.oddity_baseline)),
            cascade_skip_threshold=float(cfg.get("cascade_skip_threshold", cls.cascade_skip_threshold)),
            cascade_penalty=float(cfg.get("cascade_penalty", cls.cascade_penalty)),
            cascade_min_observations=int(cfg.get("cascade_min_observations", cls.cascade_min_observations)),
        )


@dataclass(order=True)
class FrontierJob:
    """Heap entry for crawl jobs."""

    priority: float
    order: int
    host: str = field(compare=False)
    url: str = field(compare=False)
    depth: int = field(default=0, compare=False)
    discovered_from: Optional[str] = field(default=None, compare=False)
    metadata: Dict[str, Any] = field(default_factory=dict, compare=False)
    available_at: float = field(default=0.0, compare=False)


class Frontier:
    """Priority queue frontier with novelty heuristics and bandit scheduling."""

    def __init__(self, settings: Optional[FrontierSettings] = None) -> None:
        self.settings = settings or FrontierSettings()
        self._heap: List[FrontierJob] = []
        self._delay_heap: List[Tuple[float, int, FrontierJob]] = []
        self._seen: set[str] = set()
        self._order = 0
        self._host_stats: Dict[str, Dict[str, Any]] = {}
        self._host_buckets: Dict[str, Dict[str, float]] = {}
        self._host_backoff: Dict[str, float] = {}
        self._host_hints: Dict[str, float] = {}
        self._host_cascade_stats: Dict[str, Dict[str, int]] = {}
        self._total_pulls = 0
        self._inflight: Dict[str, FrontierJob] = {}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def add(
        self,
        url: str,
        *,
        depth: int = 0,
        discovered_from: Optional[str] = None,
        priority: Optional[float] = None,
        score_hint: Optional[float] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if not url:
            return
        if url in self._seen:
            return
        host = urlsplit(url).netloc.lower()
        if not host:
            return
        self._seen.add(url)

        meta = dict(metadata or {})
        meta.setdefault("depth", depth)
        if discovered_from:
            meta["discovered_from"] = discovered_from
        if score_hint is not None:
            hint_value = max(0.0, min(1.0, float(score_hint)))
            meta["score_hint"] = hint_value
            current_hint = self._host_hints.get(host)
            if current_hint is None or hint_value > current_hint:
                self._host_hints[host] = hint_value

        computed_priority = float(priority) if priority is not None else self._compute_priority(host, depth, meta)
        computed_priority = max(self.settings.min_priority, min(self.settings.max_priority, computed_priority))

        job = FrontierJob(
            priority=-computed_priority,
            order=self._order,
            host=host,
            url=url,
            depth=depth,
            discovered_from=discovered_from,
            metadata=meta,
        )
        self._order += 1
        heapq.heappush(self._heap, job)

    def extend(
        self,
        items: Iterable[Any],
        *,
        depth: int = 0,
        discovered_from: Optional[str] = None,
        score_hint: Optional[float] = None,
    ) -> None:
        for item in items:
            if isinstance(item, str):
                self.add(item, depth=depth, discovered_from=discovered_from, score_hint=score_hint)
                continue
            if isinstance(item, Mapping):
                url = item.get("url")
                if not url:
                    continue
                meta = dict(item)
                meta.pop("url", None)
                self.add(
                    str(url),
                    depth=int(meta.pop("depth", depth) or depth),
                    discovered_from=meta.pop("discovered_from", discovered_from),
                    score_hint=meta.pop("score_hint", score_hint),
                    metadata=meta,
                )
                continue
            if isinstance(item, Sequence) and len(item) == 2:
                url, meta = item
                if not isinstance(meta, Mapping):
                    continue
                self.add(
                    str(url),
                    depth=int(meta.get("depth", depth) or depth),
                    discovered_from=meta.get("discovered_from", discovered_from),
                    score_hint=meta.get("score_hint", score_hint),
                    metadata=meta,
                )

    def pop(self) -> Optional[str]:
        self._promote_ready_jobs()
        while self._heap:
            job = heapq.heappop(self._heap)
            host = job.host
            if not host:
                self._inflight[job.url] = job
                return job.url
            if self._consume_host_token(host):
                self._inflight[job.url] = job
                return job.url
            ready_at = self._next_available_time(host)
            job.available_at = ready_at
            heapq.heappush(self._delay_heap, (ready_at, job.order, job))
            self._promote_ready_jobs()
        return None

    def record_feedback(
        self,
        url: str,
        score: float,
        action: str,
        *,
        timestamp: Optional[float] = None,
        cascade_skip: Optional[bool] = None,
    ) -> None:
        if not url:
            return
        job = self._inflight.pop(url, None)
        host = urlsplit(url).netloc.lower()
        if not host:
            return
        now = timestamp or time.time()
        stats = self._host_stats.setdefault(
            host,
            {"pulls": 0, "reward_sum": 0.0, "hits": 0, "failures": 0, "last_score": 0.0},
        )
        stats["pulls"] = int(stats.get("pulls", 0)) + 1
        reward = max(0.0, min(1.0, float(score)))
        stats["reward_sum"] = float(stats.get("reward_sum", 0.0)) + reward
        stats["last_score"] = reward
        stats["last_action"] = action
        stats["updated_at"] = now
        if action in {"persist", "llm"}:
            stats["hits"] = int(stats.get("hits", 0)) + 1
        self._total_pulls += 1
        current_hint = self._host_hints.get(host)
        if current_hint is None or reward > current_hint:
            self._host_hints[host] = reward
        bucket = self._ensure_bucket(host)
        bucket["updated_at"] = now
        if job and job.metadata.get("score_hint") is None:
            job.metadata["score_hint"] = reward
        if cascade_skip is not None:
            cascade_stats = self._host_cascade_stats.setdefault(host, {"passes": 0, "skips": 0})
            key = "skips" if cascade_skip else "passes"
            cascade_stats[key] = int(cascade_stats.get(key, 0)) + 1

    def record_failure(self, url: str, *, status_code: Optional[int] = None, reason: Optional[str] = None) -> None:
        if not url:
            return
        self._inflight.pop(url, None)
        host = urlsplit(url).netloc.lower()
        if not host:
            return
        now = time.time()
        stats = self._host_stats.setdefault(
            host,
            {"pulls": 0, "reward_sum": 0.0, "hits": 0, "failures": 0},
        )
        stats["failures"] = int(stats.get("failures", 0)) + 1
        stats["last_failure"] = now
        if status_code is not None:
            code_map = stats.setdefault("status_counts", {})
            key = str(status_code)
            code_map[key] = int(code_map.get(key, 0)) + 1
        if reason:
            stats["last_failure_reason"] = reason
        cooldown = self.settings.failure_cooldown_seconds
        self._host_backoff[host] = max(self._host_backoff.get(host, 0.0), now + cooldown)
        bucket = self._ensure_bucket(host)
        bucket["tokens"] = 0.0
        bucket["updated_at"] = now

    def get_metadata(self, url: str) -> Optional[Mapping[str, Any]]:
        job = self._inflight.get(url)
        if job:
            return dict(job.metadata)
        return None

    def __len__(self) -> int:  # pragma: no cover - trivial accessor
        return len(self._heap) + len(self._delay_heap)

    # ------------------------------------------------------------------ #
    # Persistence helpers
    # ------------------------------------------------------------------ #
    def export_state(self) -> dict:
        return {
            "order": self._order,
            "seen": sorted(self._seen),
            "heap": [self._serialize_job(job) for job in self._heap],
            "delayed": [
                {"available_at": available, "order": order, "job": self._serialize_job(job)}
                for available, order, job in self._delay_heap
            ],
            "host_stats": self._host_stats,
            "host_buckets": self._host_buckets,
            "host_backoff": self._host_backoff,
            "host_hints": self._host_hints,
            "host_cascade": self._host_cascade_stats,
            "total_pulls": self._total_pulls,
            "settings": self.settings.__dict__,
        }

    @classmethod
    def from_state(cls, state: dict, *, settings: Optional[FrontierSettings] = None) -> Frontier:
        stored_settings = state.get("settings")
        settings_obj = settings
        if settings_obj is None:
            if isinstance(stored_settings, dict):
                try:
                    settings_obj = FrontierSettings(**stored_settings)
                except TypeError:
                    settings_obj = FrontierSettings.from_config(stored_settings)
            if settings_obj is None:
                settings_obj = FrontierSettings()
        frontier = cls(settings=settings_obj)
        frontier._order = int(state.get("order", 0))
        seen = state.get("seen", [])
        if isinstance(seen, list):
            frontier._seen = set(str(url) for url in seen if url)

        heap_entries = state.get("heap", [])
        if isinstance(heap_entries, list):
            for entry in heap_entries:
                if not isinstance(entry, dict):
                    continue
                job = frontier._deserialize_job(entry)
                if job.url:
                    frontier._heap.append(job)
        heapq.heapify(frontier._heap)

        delayed_entries = state.get("delayed", [])
        if isinstance(delayed_entries, list):
            for entry in delayed_entries:
                if not isinstance(entry, dict):
                    continue
                job_data = entry.get("job")
                if not isinstance(job_data, dict):
                    continue
                job = frontier._deserialize_job(job_data)
                available = float(entry.get("available_at", job.available_at or 0.0))
                order = int(entry.get("order", job.order))
                job.available_at = available
                frontier._delay_heap.append((available, order, job))
        heapq.heapify(frontier._delay_heap)

        frontier._host_stats = {
            str(host): dict(data) for host, data in (state.get("host_stats", {}) or {}).items()
        }
        frontier._host_buckets = {
            str(host): {
                "tokens": float(value.get("tokens", frontier.settings.host_token_capacity)),
                "updated_at": float(value.get("updated_at", time.time())),
            }
            for host, value in (state.get("host_buckets", {}) or {}).items()
        }
        frontier._host_backoff = {str(host): float(value) for host, value in (state.get("host_backoff", {}) or {}).items()}
        frontier._host_hints = {str(host): float(value) for host, value in (state.get("host_hints", {}) or {}).items()}
        frontier._host_cascade_stats = {
            str(host): {"passes": int(stats.get("passes", 0)), "skips": int(stats.get("skips", 0))}
            for host, stats in (state.get("host_cascade", {}) or {}).items()
            if isinstance(stats, Mapping)
        }
        frontier._total_pulls = int(state.get("total_pulls", 0))
        frontier._inflight.clear()
        return frontier

    def save(self, path: Path) -> None:
        data = self.export_state()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)

    @classmethod
    def load(cls, path: Path, *, settings: Optional[FrontierSettings] = None) -> Frontier:
        path = Path(path)
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("Frontier state must be a JSON object")
        return cls.from_state(data, settings=settings)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _promote_ready_jobs(self) -> None:
        now = time.time()
        while self._delay_heap and self._delay_heap[0][0] <= now:
            _, _, job = heapq.heappop(self._delay_heap)
            heapq.heappush(self._heap, job)

    def _consume_host_token(self, host: str) -> bool:
        now = time.time()
        bucket = self._ensure_bucket(host)
        self._refill_tokens(host, now)
        backoff_until = self._host_backoff.get(host, 0.0)
        if backoff_until > now:
            return False
        if bucket["tokens"] >= 1.0:
            bucket["tokens"] -= 1.0
            bucket["updated_at"] = now
            return True
        return False

    def _next_available_time(self, host: str) -> float:
        now = time.time()
        bucket = self._ensure_bucket(host)
        self._refill_tokens(host, now)
        tokens = bucket.get("tokens", self.settings.host_token_capacity)
        deficit = max(0.0, 1.0 - tokens)
        wait = deficit * self.settings.host_refill_seconds
        backoff_until = self._host_backoff.get(host, 0.0)
        if backoff_until > now + wait:
            wait = backoff_until - now
        return now + max(wait, self.settings.host_penalty_seconds)

    def _ensure_bucket(self, host: str) -> Dict[str, float]:
        bucket = self._host_buckets.get(host)
        if bucket is None:
            bucket = {"tokens": self.settings.host_token_capacity, "updated_at": time.time()}
            self._host_buckets[host] = bucket
        return bucket

    def _refill_tokens(self, host: str, now: Optional[float] = None) -> None:
        now = now or time.time()
        bucket = self._ensure_bucket(host)
        if self._host_backoff.get(host, 0.0) > now:
            bucket["tokens"] = 0.0
            bucket["updated_at"] = now
            return
        if self.settings.host_refill_seconds <= 0:
            bucket["tokens"] = self.settings.host_token_capacity
            bucket["updated_at"] = now
            return
        elapsed = max(0.0, now - bucket.get("updated_at", now))
        if elapsed <= 0:
            return
        refill = elapsed / self.settings.host_refill_seconds
        bucket["tokens"] = min(self.settings.host_token_capacity, bucket.get("tokens", 0.0) + refill)
        bucket["updated_at"] = now

    def _compute_priority(self, host: str, depth: int, metadata: Mapping[str, Any]) -> float:
        host_budget = self._host_budget_score(host)
        novelty = self._novelty_score(host)
        bandit = self._bandit_score(host)
        oddity = self._oddity_prior_score(host, metadata)
        score = (
            self.settings.weight_host_budget * host_budget
            + self.settings.weight_novelty * novelty
            + self.settings.weight_bandit * bandit
            + self.settings.weight_oddity * oddity
        )
        score -= self.settings.depth_penalty * max(depth, 0)
        cascade_penalty = self._cascade_penalty(host)
        if cascade_penalty:
            score -= cascade_penalty
        discovered_from = metadata.get("discovered_from")
        if discovered_from:
            from_host = urlsplit(str(discovered_from)).netloc.lower()
            if from_host and from_host != host:
                score += self.settings.cross_domain_bonus
        return score

    def _host_budget_score(self, host: str) -> float:
        self._refill_tokens(host)
        if host in self._host_backoff and self._host_backoff[host] > time.time():
            return 0.0
        bucket = self._host_buckets.get(host)
        if not bucket:
            return 1.0
        tokens = bucket.get("tokens", self.settings.host_token_capacity)
        return max(0.0, min(1.0, tokens / max(self.settings.host_token_capacity, 1.0)))

    def _novelty_score(self, host: str) -> float:
        stats = self._host_stats.get(host)
        if not stats:
            return 1.0
        pulls = float(stats.get("pulls", 0))
        if pulls <= 0:
            return 1.0
        decay = max(self.settings.novelty_decay, 1.0)
        return max(0.1, math.exp(-pulls / decay))

    def _bandit_score(self, host: str) -> float:
        stats = self._host_stats.get(host)
        if not stats or int(stats.get("pulls", 0)) == 0:
            return self.settings.bandit_initial
        pulls = max(1, int(stats["pulls"]))
        total = max(1, self._total_pulls)
        reward_sum = float(stats.get("reward_sum", 0.0))
        avg_reward = max(0.0, min(1.0, reward_sum / pulls))
        exploration = self.settings.bandit_exploration * math.sqrt(math.log(total) / pulls)
        return max(0.0, min(1.0, avg_reward + exploration))

    def _oddity_prior_score(self, host: str, metadata: Mapping[str, Any]) -> float:
        stats = self._host_stats.get(host)
        values: List[float] = []
        if stats and int(stats.get("pulls", 0)) > 0:
            reward_sum = float(stats.get("reward_sum", 0.0))
            pulls = max(1, int(stats["pulls"]))
            values.append(max(0.0, min(1.0, reward_sum / pulls)))
        hint = metadata.get("score_hint")
        if hint is not None:
            values.append(max(0.0, min(1.0, float(hint))))
        host_hint = self._host_hints.get(host)
        if host_hint is not None:
            values.append(max(0.0, min(1.0, float(host_hint))))
        if not values:
            values.append(self.settings.oddity_baseline)
        return max(0.0, min(1.0, max(values)))

    def _serialize_job(self, job: FrontierJob) -> dict:
        return {
            "priority": job.priority,
            "order": job.order,
            "host": job.host,
            "url": job.url,
            "depth": job.depth,
            "discovered_from": job.discovered_from,
            "metadata": job.metadata,
            "available_at": job.available_at,
        }

    def _deserialize_job(self, entry: Mapping[str, Any]) -> FrontierJob:
        priority = float(entry.get("priority", 0.0))
        order = int(entry.get("order", self._order))
        host = str(entry.get("host") or "")
        url = str(entry.get("url") or "")
        depth = int(entry.get("depth", 0))
        discovered_from = entry.get("discovered_from")
        metadata = dict(entry.get("metadata", {}))
        available_at = float(entry.get("available_at", 0.0))
        return FrontierJob(
            priority=priority,
            order=order,
            host=host,
            url=url,
            depth=depth,
            discovered_from=discovered_from,
            metadata=metadata,
            available_at=available_at,
        )

    def _cascade_penalty(self, host: str) -> float:
        stats = self._host_cascade_stats.get(host)
        if not stats:
            return 0.0
        total = int(stats.get("passes", 0)) + int(stats.get("skips", 0))
        if total < self.settings.cascade_min_observations:
            return 0.0
        skip_ratio = int(stats.get("skips", 0)) / total
        if skip_ratio <= self.settings.cascade_skip_threshold:
            return 0.0
        excess = skip_ratio - self.settings.cascade_skip_threshold
        scale = max(1e-6, 1.0 - self.settings.cascade_skip_threshold)
        penalty = (excess / scale) * self.settings.cascade_penalty
        return min(self.settings.cascade_penalty, max(0.0, penalty))


__all__ = ["Frontier", "FrontierJob", "FrontierSettings"]
