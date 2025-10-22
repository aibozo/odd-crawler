#!/usr/bin/env python3
"""Long-running Oddcrawler pipeline with checkpoints and telemetry."""

from __future__ import annotations

import argparse
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from oddcrawler.config import load_app_config
from oddcrawler.crawler.frontier import Frontier
from oddcrawler.runtime import RunLoop
from oddcrawler.runner import OddcrawlerRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Oddcrawler with persistent state and telemetry.")
    parser.add_argument("--config", type=Path, default=Path("config/default.yaml"), help="Path to config YAML.")
    parser.add_argument(
        "--seeds",
        type=Path,
        help="Optional seeds file (JSON). Defaults to config seeds.file.",
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        help="Directory to write checkpoints and telemetry (default: var/runs/<timestamp>).",
    )
    parser.add_argument("--max-pages", type=int, help="Optional maximum number of pages to process.")
    parser.add_argument(
        "--checkpoint-interval",
        type=int,
        default=25,
        help="Persist frontier/metrics every N pages (default: 25).",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Optional sleep between pages to slow the crawl (default: 0).",
    )
    return parser.parse_args()


def load_seed_urls(path: Path) -> List[str]:
    if not path.exists():
        return []
    data = path.read_text(encoding="utf-8")
    import json

    payload = json.loads(data)
    hosts = payload.get("hosts", [])
    return [entry.get("url") for entry in hosts if isinstance(entry, dict) and entry.get("url")]


def default_run_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("var") / "runs" / stamp


def main() -> None:
    args = parse_args()
    config_path = args.config
    config = load_app_config(config_path)

    run_dir = args.run_dir or default_run_dir()
    run_dir = run_dir.resolve()

    run_loop_cfg = config.get("run_loop", {}) if isinstance(config, dict) else {}
    failure_cache_seconds = run_loop_cfg.get("failure_cache_seconds")

    seeds_file = args.seeds
    if seeds_file is None:
        seeds_cfg = config.get("seeds", {})
        seeds_path = Path(seeds_cfg.get("file", "examples/seeds.json"))
    else:
        seeds_path = seeds_file
    seeds = [url for url in load_seed_urls(seeds_path) if url]

    frontier_state_path = run_dir / "state" / "frontier.json"
    if frontier_state_path.exists():
        frontier = Frontier.load(frontier_state_path)
        resumed = True
    else:
        frontier = Frontier()
        resumed = False

    runner = OddcrawlerRunner(config=config, frontier=frontier)
    loop = RunLoop(
        runner=runner,
        frontier=frontier,
        run_dir=run_dir,
        checkpoint_interval=args.checkpoint_interval,
        sleep_seconds=args.sleep_seconds,
        failure_cache_seconds=failure_cache_seconds,
    )

    def handle_signal(signum, frame):  # pragma: no cover - signal handling
        print(f"\n[{datetime.now(timezone.utc).isoformat()}] Signal {signum} received; stopping at next checkpoint.")
        loop.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, handle_signal)

    if not resumed and not seeds:
        print("No seeds provided and no saved frontier state found; nothing to do.")
        return

    if not resumed:
        print(f"Starting new run in {run_dir}.")
    else:
        print(f"Resuming run in {run_dir}.")

    if seeds:
        print(f"Loaded {len(seeds)} seed(s) from {seeds_path}.")

    loop.run(seeds=seeds, max_pages=args.max_pages)

    print(f"Run complete. Telemetry: {loop.telemetry_path}")
    print(f"Summary: {loop.reports_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
