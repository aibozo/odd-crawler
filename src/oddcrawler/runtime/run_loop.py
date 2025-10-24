"""Long-running crawl loop with persistence and telemetry."""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, MutableMapping, Optional
from urllib.parse import urlsplit

from oddcrawler.agents.analyst import AnalystProcessingResult
from oddcrawler.agents.cascade import CascadeDecision, CascadeStageResult
from oddcrawler.agents.triage import ScoreDecision
from oddcrawler.crawler.fetcher import FetchError, FetchHTTPError
from oddcrawler.crawler.frontier import Frontier
from oddcrawler.runner import OddcrawlerRunner, RunnerResult
from oddcrawler.runtime.failure_cache import FailureCache


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class RunLoop:
    """Manages long-running crawl execution with checkpoints and telemetry."""

    def __init__(
        self,
        runner: OddcrawlerRunner,
        frontier: Frontier,
        run_dir: Path,
        *,
        checkpoint_interval: int = 25,
        sleep_seconds: float = 0.0,
        failure_cache: Optional[FailureCache] = None,
        failure_cache_seconds: Optional[int] = None,
    ) -> None:
        self.runner = runner
        self.frontier = frontier
        self.run_dir = Path(run_dir)
        self.checkpoint_interval = max(1, int(checkpoint_interval))
        self.sleep_seconds = max(0.0, float(sleep_seconds))

        self.state_dir = self.run_dir / "state"
        self.reports_dir = self.run_dir / "reports"
        self.telemetry_path = self.run_dir / "telemetry.jsonl"
        self.metrics_path = self.run_dir / "metrics.json"
        self.frontier_state_path = self.state_dir / "frontier.json"

        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        self.failure_cache = failure_cache or FailureCache(
            self.state_dir / "failures.json",
            expiry_seconds=failure_cache_seconds,
        )
        if getattr(self.runner, "failure_cache", None) is None:
            setattr(self.runner, "failure_cache", self.failure_cache)

        self.metrics = self._load_metrics()
        self._ensure_metric_buckets()
        self._reason_counts = Counter(self.metrics.get("reasons", {}))
        self.metrics["reasons"] = dict(self._reason_counts)
        self._failure_hosts = Counter(self.metrics.get("failure_hosts", {}))
        self._telemetry_handle = self.telemetry_path.open("a", encoding="utf-8")
        self._stop_requested = False
        self._processed_since_checkpoint = 0

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def request_stop(self) -> None:
        """Ask the loop to halt after the current iteration."""
        self._stop_requested = True

    def run(self, *, seeds: Optional[Iterable[str]] = None, max_pages: Optional[int] = None) -> None:
        """Run until exhausted, stop requested, or max_pages reached."""
        if seeds:
            seed_list = list(seeds)
            filtered = [url for url in seed_list if not self.failure_cache.should_skip(url)]
            skipped = len(seed_list) - len(filtered)
            if skipped:
                self._log_event(
                    {
                        "timestamp": _utc_now(),
                        "event": "seed_skipped",
                        "skipped_count": skipped,
                        "reason": "failure_cache",
                    }
                )
            if filtered:
                self.runner.add_seeds(filtered)
        processed = 0

        try:
            while not self._stop_requested and (max_pages is None or processed < max_pages):
                cached_before = len(self.failure_cache)
                try:
                    result = self.runner.step()
                except FetchHTTPError as exc:
                    if exc.status_code == 404:
                        self.failure_cache.record(exc.url, exc.status_code, "http_404")
                        host = urlsplit(exc.url).netloc.lower()
                        if host:
                            self._failure_hosts[host] += 1
                        if exc.url:
                            self.frontier.record_failure(exc.url, status_code=exc.status_code)
                        self._log_event(
                            {
                                "timestamp": _utc_now(),
                                "event": "url_404",
                                "url": exc.url,
                                "status": exc.status_code,
                                "host": host,
                            }
                        )
                        continue
                    if getattr(exc, "url", None):
                        self.frontier.record_failure(exc.url, status_code=exc.status_code)
                    self._record_error(exc)
                    continue
                except FetchError as exc:
                    url = getattr(exc, "url", None)
                    if url:
                        self.frontier.record_failure(url, reason=exc.__class__.__name__)
                    self._record_error(exc)
                    continue
                except Exception as exc:  # pragma: no cover - runtime resilience
                    self._record_error(exc)
                    continue

                if result is None:
                    break

                self._record_result(result)
                cached_after = len(self.failure_cache)
                if cached_after > cached_before:
                    self._log_event(
                        {
                            "timestamp": _utc_now(),
                            "event": "url_failure_cached",
                            "total_cached": cached_after,
                        }
                    )
                processed += 1
                self._processed_since_checkpoint += 1

                if self._processed_since_checkpoint >= self.checkpoint_interval:
                    self.checkpoint()

                if self.sleep_seconds:
                    time.sleep(self.sleep_seconds)
        finally:
            self.checkpoint()
            self._telemetry_handle.close()

    def checkpoint(self) -> None:
        """Persist frontier state and metrics to disk."""
        self.frontier.save(self.frontier_state_path)
        self.failure_cache.save()
        self._save_metrics()
        self._write_summary()
        self._telemetry_handle.flush()
        self._processed_since_checkpoint = 0

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _load_metrics(self) -> MutableMapping[str, object]:
        if self.metrics_path.exists():
            with self.metrics_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle) or {}
            if isinstance(data, dict):
                return data
        return {
            "run_started_at": _utc_now(),
            "last_updated_at": _utc_now(),
            "pages_processed": 0,
            "actions": {"skip": 0, "persist": 0, "llm": 0},
            "illegal_skipped": 0,
            "errors": 0,
            "llm_calls": 0,
            "total_score": 0.0,
            "reasons": {},
            "cached_failures": 0,
            "failure_hosts": {},
        }

    def _ensure_metric_buckets(self) -> None:
        timing = self.metrics.setdefault(
            "timing",
            {"total_runtime_seconds": 0.0, "crawl_rate_per_minute": 0.0, "crawl_rate_per_hour": 0.0},
        )
        timing.setdefault("total_runtime_seconds", 0.0)
        timing.setdefault("crawl_rate_per_minute", 0.0)
        timing.setdefault("crawl_rate_per_hour", 0.0)

        fetch_stats = self.metrics.setdefault(
            "fetch_stats",
            {
                "requests": 0,
                "total_bytes": 0,
                "total_duration_ms": 0.0,
                "average_duration_ms": 0.0,
                "average_kib_per_page": 0.0,
            },
        )
        fetch_stats.setdefault("requests", 0)
        fetch_stats.setdefault("total_bytes", 0)
        fetch_stats.setdefault("total_duration_ms", 0.0)
        fetch_stats.setdefault("average_duration_ms", 0.0)
        fetch_stats.setdefault("average_kib_per_page", 0.0)

        cost = self.metrics.setdefault(
            "cost",
            {
                "bandwidth_bytes": 0,
                "bandwidth_mib": 0.0,
                "bandwidth_kib_per_page": 0.0,
                "llm_calls": int(self.metrics.get("llm_calls", 0) or 0),
                "estimated_llm_usd": 0.0,
            },
        )
        cost.setdefault("bandwidth_bytes", 0)
        cost.setdefault("bandwidth_mib", 0.0)
        cost.setdefault("bandwidth_kib_per_page", 0.0)
        cost.setdefault("llm_calls", int(self.metrics.get("llm_calls", 0) or 0))
        cost.setdefault("estimated_llm_usd", 0.0)

        odd_hits = self.metrics.setdefault("odd_hits", {"total": 0, "ratio": 0.0})
        odd_hits.setdefault("total", 0)
        odd_hits.setdefault("ratio", 0.0)

    def _save_metrics(self) -> None:
        self.metrics["reasons"] = dict(self._reason_counts)
        self.metrics["last_updated_at"] = _utc_now()
        self.metrics["cached_failures"] = len(self.failure_cache)
        self.metrics["failure_hosts"] = dict(self._failure_hosts)
        self._ensure_metric_buckets()
        with self.metrics_path.open("w", encoding="utf-8") as handle:
            json.dump(self.metrics, handle, indent=2, sort_keys=True)

    def _write_summary(self) -> None:
        processed = self.metrics.get("pages_processed", 0) or 0
        total_score = float(self.metrics.get("total_score", 0.0) or 0.0)
        average_score = total_score / processed if processed else 0.0
        summary = {
            "run_started_at": self.metrics.get("run_started_at"),
            "last_updated_at": self.metrics.get("last_updated_at"),
            "pages_processed": processed,
            "actions": self.metrics.get("actions", {}),
            "illegal_skipped": self.metrics.get("illegal_skipped", 0),
            "errors": self.metrics.get("errors", 0),
            "llm_calls": self.metrics.get("llm_calls", 0),
            "average_score": round(average_score, 4),
            "frontier_size": len(self.frontier),
            "cached_failures": len(self.failure_cache),
            "crawl_rate_per_minute": self.metrics.get("timing", {}).get("crawl_rate_per_minute", 0.0),
            "crawl_rate_per_hour": self.metrics.get("timing", {}).get("crawl_rate_per_hour", 0.0),
            "average_fetch_duration_ms": self.metrics.get("fetch_stats", {}).get("average_duration_ms", 0.0),
            "average_kib_per_page": self.metrics.get("fetch_stats", {}).get("average_kib_per_page", 0.0),
            "bandwidth_mib": self.metrics.get("cost", {}).get("bandwidth_mib", 0.0),
            "bandwidth_kib_per_page": self.metrics.get("cost", {}).get("bandwidth_kib_per_page", 0.0),
            "odd_hits": self.metrics.get("odd_hits", {}).get("total", 0),
            "odd_hit_ratio": self.metrics.get("odd_hits", {}).get("ratio", 0.0),
            "cascade_skips": self.metrics.get("cascade", {}).get("skips", 0),
            "cascade_passes": self.metrics.get("cascade", {}).get("passes", 0),
            "top_reasons": sorted(
                self._reason_counts.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:10],
            "top_failure_hosts": sorted(
                self._failure_hosts.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:10],
        }
        summary_path = self.reports_dir / "summary.json"
        with summary_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, sort_keys=True)

    def _record_result(self, result: RunnerResult) -> None:
        decision = result.decision
        pipeline = result.pipeline_result

        event = {
            "timestamp": _utc_now(),
            "url": result.url,
            "action": decision.action,
            "score": round(float(decision.score), 6),
            "thresholds_hit": decision.thresholds_hit,
            "reasons": list(decision.reasons or []),
            "frontier_size": len(self.frontier),
        }

        fetch_metrics = result.fetch_metrics
        cascade_result = result.cascade_result
        if fetch_metrics is None and isinstance(result.observation, Mapping):
            obs_fetch = result.observation.get("fetch_metrics")
            if isinstance(obs_fetch, Mapping):
                fetch_metrics = obs_fetch
        if cascade_result is None and isinstance(result.observation, Mapping):
            obs_cascade = result.observation.get("cascade")
            if isinstance(obs_cascade, Mapping):
                cascade_result = CascadeDecision(
                    should_skip=bool(obs_cascade.get("should_skip", False)),
                    stages=[CascadeStageResult(**stage) for stage in obs_cascade.get("stages", []) if isinstance(stage, Mapping)],
                    final_reason=obs_cascade.get("final_reason"),
                )

        observation_path = None
        finding_ref = None
        llm_called = decision.action == "llm"
        illegal_flag = bool(pipeline.get("illegal")) if isinstance(pipeline, Mapping) else False

        if isinstance(pipeline, Mapping):
            observation_path = pipeline.get("observation_path") or observation_path
            finding = pipeline.get("finding")
            if isinstance(finding, Mapping):
                finding_ref = finding.get("observation_ref") or finding_ref
                llm_called = True
            analyst_result = pipeline.get("analyst_result")
            if isinstance(analyst_result, AnalystProcessingResult):
                finding_ref = finding_ref or analyst_result.finding.get("observation_ref")
                observation_path = observation_path or analyst_result.observation_path

        event["observation_path"] = observation_path
        event["finding_ref"] = finding_ref
        event["illegal"] = illegal_flag
        if fetch_metrics:
            duration_ms = fetch_metrics.get("duration_ms")
            bytes_downloaded = fetch_metrics.get("bytes_downloaded")
            status = fetch_metrics.get("status")
            via_tor = fetch_metrics.get("via_tor")
            if isinstance(duration_ms, (int, float)):
                event["fetch_duration_ms"] = round(float(duration_ms), 3)
            if isinstance(bytes_downloaded, (int, float)):
                event["bytes_downloaded"] = int(bytes_downloaded)
            if isinstance(status, (int, float)):
                event["status"] = int(status)
            if isinstance(via_tor, bool):
                event["via_tor"] = via_tor

        if cascade_result is not None:
            event["cascade"] = cascade_result.to_dict()

        self._log_event(event)
        self._update_metrics(
            decision,
            illegal_flag,
            llm_called,
            fetch_metrics=fetch_metrics,
            cascade=cascade_result,
        )

    def _record_error(self, exc: Exception) -> None:
        error_event = {
            "timestamp": _utc_now(),
            "event": "error",
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
        }
        self.metrics["errors"] = int(self.metrics.get("errors", 0)) + 1
        self._log_event(error_event)

    def _update_metrics(
        self,
        decision: ScoreDecision,
        illegal_flag: bool,
        llm_called: bool,
        *,
        fetch_metrics: Optional[Mapping[str, object]] = None,
        cascade: Optional["CascadeDecision"] = None,
    ) -> None:
        self.metrics["pages_processed"] = int(self.metrics.get("pages_processed", 0)) + 1
        actions = self.metrics.setdefault("actions", {"skip": 0, "persist": 0, "llm": 0})
        actions[decision.action] = int(actions.get(decision.action, 0)) + 1
        self.metrics["total_score"] = float(self.metrics.get("total_score", 0.0)) + float(decision.score)
        if illegal_flag:
            self.metrics["illegal_skipped"] = int(self.metrics.get("illegal_skipped", 0)) + 1
        if llm_called:
            self.metrics["llm_calls"] = int(self.metrics.get("llm_calls", 0)) + 1

        for reason in decision.reasons or []:
            self._reason_counts[reason] += 1

        if fetch_metrics:
            self._update_fetch_stats(fetch_metrics)
        if cascade:
            self._update_cascade_metrics(cascade)

        self._update_odd_hit_ratio()
        self._update_timing()
        self._update_costs()

    def _log_event(self, event: Mapping[str, object]) -> None:
        json.dump(event, self._telemetry_handle, ensure_ascii=False)
        self._telemetry_handle.write("\n")
        self._telemetry_handle.flush()

    def _update_fetch_stats(self, fetch_metrics: Mapping[str, object]) -> None:
        stats = self.metrics.setdefault(
            "fetch_stats",
            {
                "requests": 0,
                "total_bytes": 0,
                "total_duration_ms": 0.0,
                "average_duration_ms": 0.0,
                "average_kib_per_page": 0.0,
            },
        )

        stats["requests"] = int(stats.get("requests", 0)) + 1

        bytes_downloaded = fetch_metrics.get("bytes_downloaded")
        if isinstance(bytes_downloaded, (int, float)):
            stats["total_bytes"] = int(stats.get("total_bytes", 0)) + int(bytes_downloaded)

        duration_ms = fetch_metrics.get("duration_ms")
        if isinstance(duration_ms, (int, float)):
            stats["total_duration_ms"] = float(stats.get("total_duration_ms", 0.0)) + float(duration_ms)

        processed = int(self.metrics.get("pages_processed", 0)) or 0
        if processed > 0:
            total_duration = float(stats.get("total_duration_ms", 0.0))
            stats["average_duration_ms"] = round(total_duration / processed, 4)
            total_bytes = int(stats.get("total_bytes", 0))
            stats["average_kib_per_page"] = round(total_bytes / processed / 1024.0, 4)
        else:
            stats["average_duration_ms"] = 0.0
            stats["average_kib_per_page"] = 0.0

    def _update_odd_hit_ratio(self) -> None:
        actions = self.metrics.get("actions", {})
        persist = int(actions.get("persist", 0) or 0)
        llm = int(actions.get("llm", 0) or 0)
        processed = int(self.metrics.get("pages_processed", 0) or 0)

        odd_hits = self.metrics.setdefault("odd_hits", {"total": 0, "ratio": 0.0})
        odd_total = persist + llm
        odd_hits["total"] = odd_total
        odd_hits["ratio"] = round(odd_total / processed, 4) if processed else 0.0

    def _update_timing(self) -> None:
        timing = self.metrics.setdefault(
            "timing",
            {"total_runtime_seconds": 0.0, "crawl_rate_per_minute": 0.0, "crawl_rate_per_hour": 0.0},
        )
        start_ts = _parse_timestamp(self.metrics.get("run_started_at"))
        now = datetime.now(timezone.utc)
        elapsed_seconds = max((now - start_ts).total_seconds(), 0.0) if start_ts else 0.0
        processed = int(self.metrics.get("pages_processed", 0) or 0)
        rate_per_minute = (processed / (elapsed_seconds / 60.0)) if elapsed_seconds > 0 else 0.0
        timing["total_runtime_seconds"] = round(elapsed_seconds, 3)
        timing["crawl_rate_per_minute"] = round(rate_per_minute, 4)
        timing["crawl_rate_per_hour"] = round(rate_per_minute * 60.0, 4)

    def _update_costs(self) -> None:
        stats = self.metrics.get("fetch_stats", {})
        total_bytes = int(stats.get("total_bytes", 0) or 0)
        processed = int(self.metrics.get("pages_processed", 0) or 0)
        cost = self.metrics.setdefault(
            "cost",
            {
                "bandwidth_bytes": 0,
                "bandwidth_mib": 0.0,
                "bandwidth_kib_per_page": 0.0,
                "llm_calls": int(self.metrics.get("llm_calls", 0) or 0),
                "estimated_llm_usd": 0.0,
            },
        )
        cost["bandwidth_bytes"] = total_bytes
        cost["bandwidth_mib"] = round(total_bytes / (1024.0 * 1024.0), 4)
        cost["bandwidth_kib_per_page"] = round(total_bytes / processed / 1024.0, 4) if processed else 0.0
        cost["llm_calls"] = int(self.metrics.get("llm_calls", 0) or 0)
        cost.setdefault("estimated_llm_usd", 0.0)

    def _update_cascade_metrics(self, cascade: CascadeDecision) -> None:
        cascade_bucket = self.metrics.setdefault(
            "cascade",
            {
                "skips": 0,
                "passes": 0,
                "warns": 0,
                "stages": {},
                "overrides": {},
            },
        )
        stage_bucket = cascade_bucket.setdefault("stages", {})
        overrides = cascade_bucket.setdefault("overrides", {})
        for stage in cascade.stages:
            stage_info = stage_bucket.setdefault(stage.stage, {"pass": 0, "skip": 0, "warn": 0})
            if stage.status == "skip":
                stage_info["skip"] = int(stage_info.get("skip", 0)) + 1
            elif stage.status == "pass":
                stage_info["pass"] = int(stage_info.get("pass", 0)) + 1
            elif stage.status == "warn":
                stage_info["warn"] = int(stage_info.get("warn", 0)) + 1
                override_key = None
                metrics = stage.metrics or {}
                override_key = metrics.get("override")
                if override_key:
                    overrides[override_key] = int(overrides.get(override_key, 0)) + 1
        if cascade.should_skip:
            cascade_bucket["skips"] = int(cascade_bucket.get("skips", 0)) + 1
        else:
            cascade_bucket["passes"] = int(cascade_bucket.get("passes", 0)) + 1
        if any(stage.status == "warn" for stage in cascade.stages):
            cascade_bucket["warns"] = int(cascade_bucket.get("warns", 0)) + 1

__all__ = ["RunLoop"]
