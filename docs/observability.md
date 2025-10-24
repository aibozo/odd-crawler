# Observability & Cost Controls

## Metrics
- Baseline (run artifact `metrics.json`): crawl_rate_per_minute/hour, average fetch duration, bandwidth bytes/MiB, odd_hit ratio, cascade gate throughput (passes/skips/warns + override counts), and LLM call totals (`timing`, `fetch_stats`, `cost`, `odd_hits`, `cascade` buckets).
- Crawl: requests/sec, success rate, median/95p latency, robots-denied count.
- Frontier: queue size, per-host budgets, exploration/exploitation fractions.
- Extraction: text length, failure rate.
- Scoring: feature distributions, gate hit rates, threshold drift (`persist`, `llm`, `alert`) with current config version.
- LLM: calls/min, cost/day, validation failures, average tokens, budget utilization vs. caps.
- Storage: WARC/HTML volume, vector count, graph edges, raw-store TTL purge counts.
- Safety: PII redactions, dangerous-content hit rate, breadcrumb writes by category.
- Failures: per-host 404 counts (from `top_failure_hosts`) to prune dead seeds.

## Tracing
- Emit spans: fetch → extract → features → score → LLM → persist.
- Include URL hashes only (no PII) in traces.
- Attach scoring thresholds and `salt_version` as span attributes for compliance audits.

## Budgets
- Global daily LLM cost cap and RPM cap.
- Per-domain LLM budget to avoid a single site draining tokens.
- Metrics `llm_budget_remaining` and `llm_budget_breach` alert when <10% remaining or when exceeded.
- Scoring module must respect `llm_gate_threshold` from config; any live override requires incident annotation in the dashboard.

## Local telemetry snapshots
- Use `scripts/run_pipeline.py` for long-lived runs. Each invocation persists:
  - `telemetry.jsonl` — per-page events with scores, actions, frontier depth, and fetch stats (duration ms, bytes, TOR flag).
  - `metrics.json` — cumulative counters (actions, illegal skips, LLM calls, errors) plus baseline buckets (`timing`, `fetch_stats`, `cost`, `odd_hits`, `cascade`) for rate/cost/oddity recall tracking. Cascade metrics now include per-stage pass/skip/warn counts and override tallies (token, retro, anchor, keyword).
  - `reports/summary.json` — derived stats (average score, top reasons, queue size).
  - `state/frontier.json` — serialized queue to resume after crashes or planned pauses.
  - `state/failures.json` — cached hard failures (e.g., HTTP 404) to avoid re-crawling dead nodes; entries expire after 7 days by default.
- These on-disk artifacts feed into higher-level dashboards; ship them or ingest directly after each run.
