"""High-level runner tying together frontier, fetcher, extractor, and scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Mapping, Optional, TYPE_CHECKING

from oddcrawler.config import load_app_config

from oddcrawler.agents import OddcrawlerPipeline, ScoreDecision
from oddcrawler.agents.cascade import CascadeDecision, TriageCascade
from oddcrawler.agents.pipeline import FetchResult
from oddcrawler.agents.triage import TriageOrchestrator
from oddcrawler.crawler.fetcher import Fetcher
from oddcrawler.crawler.frontier import Frontier
from oddcrawler.crawler.tor_connector import TorConnector
from oddcrawler.extractors.html_clean import HTMLExtractor
from oddcrawler.graph import GraphFeatureManager
from oddcrawler.llm import GeminiClient, GeminiConfigurationError
from oddcrawler.scoring.fusion import ScoringEngine
from oddcrawler.safety import IllegalContentDetector, IllegalDetection

if TYPE_CHECKING:
    from oddcrawler.runtime.failure_cache import FailureCache


@dataclass
class RunnerResult:
    url: str
    decision: ScoreDecision
    observation: Mapping[str, object]
    pipeline_result: Mapping[str, object]
    fetch_metrics: Optional[Mapping[str, object]] = None
    cascade_result: Optional[CascadeDecision] = None


class OddcrawlerRunner:
    """Coordinates a single-threaded crawl loop."""

    def __init__(
        self,
        *,
        config: Optional[Mapping[str, object]] = None,
        frontier: Optional[Frontier] = None,
        fetcher: Optional[Fetcher] = None,
        extractor: Optional[HTMLExtractor] = None,
        scoring: Optional[ScoringEngine] = None,
        pipeline: Optional[OddcrawlerPipeline] = None,
        analyst_client: Optional[GeminiClient] = None,
        flash_client: Optional[GeminiClient] = None,
        graph_manager: Optional[GraphFeatureManager] = None,
        failure_cache: Optional["FailureCache"] = None,
    ) -> None:
        self.config = dict(config) if config is not None else load_app_config()
        crawl_cfg = self.config.get("crawl", {}) if isinstance(self.config, Mapping) else {}

        self.frontier = frontier or Frontier()
        tor_cfg = crawl_cfg.get("tor", {}) if isinstance(crawl_cfg, Mapping) else {}
        self.tor_connector = self._build_tor_connector(crawl_cfg, tor_cfg)
        if fetcher is None:
            backoff_bounds = crawl_cfg.get("error_backoff_seconds")
            if isinstance(backoff_bounds, list) and len(backoff_bounds) >= 2:
                backoff_tuple = (float(backoff_bounds[0]), float(backoff_bounds[1]))
            else:
                backoff_tuple = (2.0, 10.0)
            fetcher = Fetcher(
                user_agent=str(crawl_cfg.get("user_agent", "Oddcrawler/0.1")),
                timeout=float(crawl_cfg.get("download_timeout_seconds", 20)),
                obey_robots=bool(crawl_cfg.get("obey_robots_txt", True)),
                per_host_requests_per_minute=int(crawl_cfg.get("per_host_requests_per_minute", 0) or 0),
                retries=int(crawl_cfg.get("retries", 1)),
                backoff_bounds=backoff_tuple,
                tor_connector=self.tor_connector,
            )
        self.fetcher = fetcher

        analyst = analyst_client
        if analyst is None:
            try:
                analyst = GeminiClient(model_key="analyst")
            except GeminiConfigurationError:
                analyst = None

        flash = flash_client
        if flash is None:
            try:
                flash = GeminiClient(model_key="extractor")
            except GeminiConfigurationError:
                flash = None

        self.extractor = extractor or HTMLExtractor(flash_client=flash)
        self.scoring = scoring or ScoringEngine()
        triage_cfg = self.config.get("triage", {}) if isinstance(self.config, Mapping) else {}
        prefilter_cfg = triage_cfg.get("prefilter")
        self.cascade = TriageCascade(config=triage_cfg.get("cascade"), prefilter_config=prefilter_cfg)

        if pipeline is None:
            triage = TriageOrchestrator(llm_client=analyst)
            pipeline = OddcrawlerPipeline(triage=triage)
        self.pipeline = pipeline
        triage_config = getattr(self.pipeline, "triage", None)
        storage_config = getattr(triage_config, "config", None) if triage_config else None
        self.graph_manager = graph_manager or GraphFeatureManager(storage_config=storage_config)
        safety_cfg = self.config.get("safety", {}) if isinstance(self.config, Mapping) else {}
        self.illegal_detector = IllegalContentDetector(safety_cfg)
        self.failure_cache = failure_cache

    def add_seeds(self, urls: Iterable[str]) -> None:
        if self.failure_cache:
            urls = [url for url in urls if not self.failure_cache.should_skip(url)]
        if not urls:
            return
        self.frontier.extend(urls, depth=0, score_hint=1.0)

    def step(self) -> Optional[RunnerResult]:
        fetch_result: Optional[FetchResult] = None
        url: Optional[str] = None
        while True:
            url = self.frontier.pop()
            if not url:
                return None
            if self.failure_cache and self.failure_cache.should_skip(url):
                continue
            fetch_result = self.fetcher.fetch(url)
            break

        assert fetch_result is not None

        fetch_metrics = self._build_fetch_metrics(fetch_result)
        pre_detection = self._scan_illegal_prefetch(fetch_result)
        if pre_detection.illegal:
            self.frontier.record_feedback(fetch_result.url, 0.0, "skip", cascade_skip=None)
            pipeline_result: Mapping[str, object] = {"illegal": True, "reason": pre_detection.reason}
            sanitized_observation = {
                "url": fetch_result.url,
                "fetched_at": fetch_result.fetched_at,
                "status": fetch_metrics.get("status"),
                "bytes_downloaded": fetch_metrics.get("bytes_downloaded"),
                "illegal_reason": pre_detection.reason,
                "fetch_metrics": fetch_metrics,
            }
            return RunnerResult(
                url=fetch_result.url,
                decision=ScoreDecision(
                    score=0.0,
                    action="skip",
                    thresholds_hit={},
                    reasons=[f"illegal content signal: {pre_detection.reason}"],
                ),
                observation=sanitized_observation,
                pipeline_result=pipeline_result,
                fetch_metrics=fetch_metrics,
                cascade_result=None,
            )

        cascade_decision = self.cascade.evaluate(
            {
                "url": fetch_result.url,
                "headers": fetch_result.headers,
                "body": fetch_result.body,
                "links": {"outbound": []},
            }
        )
        if cascade_decision.should_skip:
            reasons = [stage.reason for stage in cascade_decision.stages if stage.status == "skip" and stage.reason]
            cascade_reason = "; ".join(reason for reason in reasons if reason)
            decision = ScoreDecision(
                score=0.0,
                action="skip",
                thresholds_hit={},
                reasons=[f"cascade:{cascade_reason or 'early-skip'}"],
            )
            pipeline_result: Mapping[str, object] = {
                "cascade": cascade_decision.to_dict(),
                "observation_path": None,
            }
            observation = {
                "url": fetch_result.url,
                "fetched_at": fetch_result.fetched_at,
                "status": fetch_metrics.get("status"),
                "fetch_metrics": fetch_metrics,
                "cascade": cascade_decision.to_dict(),
            }
            self.frontier.record_feedback(
                fetch_result.url,
                0.0,
                decision.action,
                cascade_skip=cascade_decision.should_skip,
            )
            return RunnerResult(
                url=fetch_result.url,
                decision=decision,
                observation=observation,
                pipeline_result=pipeline_result,
                fetch_metrics=fetch_metrics,
                cascade_result=cascade_decision,
            )
        observation = self.extractor.extract(fetch_result)
        detection = self._scan_illegal(fetch_result, observation)
        if detection.illegal:
            if self.tor_connector:
                self.tor_connector.record_illegal(fetch_result.url, detection.reason)
            decision = ScoreDecision(
                score=0.0,
                action="skip",
                thresholds_hit={},
                reasons=[f"illegal content signal: {detection.reason}"],
            )
            pipeline_result: Mapping[str, object] = {"illegal": True, "reason": detection.reason}
            sanitized_observation: Mapping[str, object] = {
                "url": fetch_result.url,
                "fetched_at": fetch_result.fetched_at,
                "status": fetch_metrics.get("status"),
                "bytes_downloaded": fetch_metrics.get("bytes_downloaded"),
                "illegal_reason": detection.reason,
                "fetch_metrics": fetch_metrics,
            }
            self.frontier.record_feedback(
                fetch_result.url,
                0.0,
                decision.action,
                cascade_skip=cascade_decision.should_skip if cascade_decision else None,
            )
            return RunnerResult(
                url=url,
                decision=decision,
                observation=sanitized_observation,
                pipeline_result=pipeline_result,
                fetch_metrics=fetch_metrics,
            )

        self.pipeline.record_fetch(fetch_result)
        if self.graph_manager is not None:
            fetched_at = getattr(fetch_result, "fetched_at", "")
            status = int(getattr(fetch_result, "status", 0) or 0)
            self.graph_manager.enrich_observation(
                observation,
                fetched_at=fetched_at,
                status=status,
            )
        decision = self.scoring.evaluate(observation)
        if self.graph_manager is not None:
            self.graph_manager.record_score(fetch_result.url, decision.score, action=decision.action)

        observation["cascade"] = cascade_decision.to_dict()
        observation["fetch_metrics"] = fetch_metrics
        pipeline_result = self.pipeline.handle_scored_observation(observation, decision, finding=None)
        self.frontier.record_feedback(
            fetch_result.url,
            decision.score,
            decision.action,
            cascade_skip=cascade_decision.should_skip if cascade_decision else None,
        )

        return RunnerResult(
            url=url,
            decision=decision,
            observation=observation,
            pipeline_result=pipeline_result,
            fetch_metrics=fetch_metrics,
            cascade_result=cascade_decision,
        )

    def run(self, *, max_pages: Optional[int] = None) -> List[RunnerResult]:
        results: List[RunnerResult] = []
        processed = 0
        while max_pages is None or processed < max_pages:
            step_result = self.step()
            if step_result is None:
                break
            results.append(step_result)
            processed += 1
        return results

    def _scan_illegal(self, fetch_result: FetchResult, observation: Mapping[str, object]) -> IllegalDetection:
        text = ""
        extract = observation.get("extract")
        if isinstance(extract, Mapping):
            text = str(extract.get("text_excerpt") or "")
        if (not text) and getattr(fetch_result, "body", None):
            try:
                text = fetch_result.body.decode("utf-8", errors="ignore")
            except Exception:  # pragma: no cover - decoding fallback
                text = ""
        return self.illegal_detector.scan(text)

    def _scan_illegal_prefetch(self, fetch_result: FetchResult) -> IllegalDetection:
        text = ""
        if getattr(fetch_result, "body", None):
            try:
                text = fetch_result.body.decode("utf-8", errors="ignore")
            except Exception:
                text = ""
        return self.illegal_detector.scan(text)

    def _build_tor_connector(self, crawl_cfg: Mapping[str, object], tor_cfg: Mapping[str, object]) -> Optional[TorConnector]:
        allow_flag = bool(crawl_cfg.get("allow_tor_connector", False))
        enabled = bool(tor_cfg.get("enabled", allow_flag))
        if not enabled:
            return None

        return TorConnector(
            enabled=True,
            socks_host=str(tor_cfg.get("socks_host", "127.0.0.1")),
            socks_port=int(tor_cfg.get("socks_port", 9050) or 9050),
            control_port=_maybe_int(tor_cfg.get("control_port", 9051)),
            control_password=tor_cfg.get("control_password"),
            per_host_requests_per_minute=_maybe_int(tor_cfg.get("per_host_requests_per_minute")),
            global_requests_per_minute=_maybe_int(tor_cfg.get("global_requests_per_minute")),
            failure_block_minutes=int(tor_cfg.get("failure_block_minutes", 30) or 30),
            max_failures_per_host=int(tor_cfg.get("max_failures_per_host", 3) or 3),
            illegal_block_days=int(tor_cfg.get("illegal_block_days", 365) or 365),
            blocklist_path=tor_cfg.get("blocklist_path"),
            route_domains=tor_cfg.get("route_domains", []),
            route_onion_only=bool(tor_cfg.get("route_onion_only", True)),
        )

    @staticmethod
    def _build_fetch_metrics(fetch_result: FetchResult) -> Mapping[str, object]:
        status = fetch_result.status if fetch_result.status is not None else getattr(fetch_result, "status", None)
        duration_ms = (
            float(fetch_result.duration_ms) if fetch_result.duration_ms is not None else getattr(fetch_result, "duration_ms", None)
        )
        bytes_downloaded = fetch_result.bytes_downloaded if fetch_result.bytes_downloaded is not None else len(fetch_result.body)
        via_tor = bool(fetch_result.via_tor)

        metrics = {
            "status": int(status) if isinstance(status, (int, float)) else status,
            "duration_ms": float(duration_ms) if isinstance(duration_ms, (int, float)) else None,
            "bytes_downloaded": int(bytes_downloaded),
            "via_tor": via_tor,
            "fetched_at": fetch_result.fetched_at,
        }
        return metrics


__all__ = ["OddcrawlerRunner", "RunnerResult"]


def _maybe_int(value: object) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
