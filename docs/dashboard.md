# Telemetry Dashboard Plan

## Goals
- Provide a live view of long-running crawl health (requests, actions, errors, frontier depth).
- Surface Gemini usage: per-model token spend, hourly cost ceilings, cap hits.
- Make persistent reports easy to review: link to summaries, excerpts, graph artifacts.
- Collapse telemetry from multiple run directories into one UI for operators.

## Data sources
| Source | Path | Refresh cadence | Notes |
|--------|------|-----------------|-------|
| Run summary | `var/runs/*/reports/summary.json` | periodic (15–30 s) | Contains high-level counters and new `llm_usage`, `llm_hourly_cap_hits`. |
| Metrics | `var/runs/*/metrics.json` | periodic | Includes cumulative action counters, last wait time, cap hit count. |
| Telemetry stream | `var/runs/*/telemetry.jsonl` | tail/live | Append-only page-level events; drive live timeline. |
| Frontier state | `var/runs/*/state/frontier.json` | on-demand | For estimating queue depth and resume points. |
| Artifacts | `var/runs/*/reports`, `var/oddcrawler/excerpts`, `config/var/oddcrawler/graphs` | on-click | Linked out from UI for deep dives. |

## Proposed data model
We can normalize the JSON files in-memory and expose a unified API (or static bundles) with:

```jsonc
{
  "runs": [
    {
      "run_id": "20251022T155322Z",
      "path": "var/runs/long-test",
      "started_at": "2025-10-22T15:53:22.068679+00:00",
      "last_updated_at": "...",
      "pages_processed": 20,
      "actions": {"persist": 9, "llm": 11, "skip": 0},
      "llm_usage": {
        "gemini-2.5-pro": {
          "prompt_tokens": 9204,
          "completion_tokens": 3686,
          "cached_tokens": 0,
          "prompt_cost_usd": 0.011505,
          "completion_cost_usd": 0.03686,
          "cache_cost_usd": 0.0
        },
        "...": {}
      },
      "hourly_cost": {
        "limit_usd": 10.0,
        "last_wait_seconds": 0.0,
        "cap_hits": 0
      },
      "top_reasons": [["possible webring membership", 12]],
      "links": {
        "summary": "var/runs/long-test/reports/summary.json",
        "metrics": "var/runs/long-test/metrics.json",
        "telemetry": "var/runs/long-test/telemetry.jsonl",
        "frontier": "var/runs/long-test/state/frontier.json"
      }
    }
  ]
}
```

For the live stream, expose a websocket (or polling endpoint) returning tail entries:

```json
{
  "timestamp": "...",
  "run_id": "...",
  "url": "...",
  "action": "llm",
  "score": 0.60,
  "reasons": ["possible webring membership"],
  "context_size_tokens": 4800,   // optional derived metric
  "frontier_size": 14
}
```

## UI layout
1. **Overview tab**
   - Run selector (all active runs).
   - KPI cards: pages/hour, success rate, frontier depth, LLM hourly spend vs limit.
   - Time-series charts: `pages_processed`, `actions` per minute, `llm_cost_usd` (stacked).
2. **Live telemetry tab**
   - Scrollable event log (action, score, reasons, context tokens).
   - Graph of recent scores / decisions.
   - Filter by action or reason.
3. **Reports & artifacts tab**
   - Table of runs with links to summary, metrics, excerpts folder, graph JSON.
   - Download buttons for telemetry/log bundles.
4. **LLM usage tab**
   - Per-model token/cost charts.
   - Hourly cap indicator (time to cap, last wait).
   - Context window stats (avg findings length, summarizer fallback count).

## Implementation notes
- **Ingestion**: a lightweight FastAPI (or Starlette) service can watch run directories and expose `/runs`, `/runs/{id}/telemetry`, `/runs/{id}/artifacts`.
  - MVP service lives at `oddcrawler.dashboard.service`. Launch with `.venv/bin/python scripts/dashboard_api.py` (serves on `127.0.0.1:8100`).
- **Frontend**: React/Vite or Svelte kit; use websockets for live tail (fallback to polling).
  - `dashboard/ui/index.html` is a static stub wired to mock data as a starting point. Replace the fetch endpoint with the live API once the service is running.
  - Open the stub in a browser while the API is running; it will attempt to reach `http://127.0.0.1:8100`. If unreachable it falls back to the bundled mock data.
- **Run control**: POST `/runs/start` accepts `{run_dir?, max_pages?, sleep_seconds?, config?}` and launches `scripts/run_pipeline.py`. POST `/runs/{run_id}/stop` terminates the associated process. GET `/runs/active` lists currently running processes.
- **Blocklist hygiene**: GET `/maintenance/blocklist/status` reports the last refresh, host count, and any errors. POST `/maintenance/blocklist/refresh` forces a pull from URLhaus and rewrites `config/safety/blocklist_hosts.txt`. When `dashboard.blocklist.auto_refresh` is enabled in `config/default.yaml`, a background daemon refreshes every `dashboard.blocklist.refresh_seconds` seconds while the dashboard API is running.
- UI’s Overview tab exposes a single “Start Run” button (defaults to repo settings) and a list of active runs with “Stop” buttons that call `/runs/{id}/stop`. Controls only work when the API is reachable; status bar reflects errors/fallback to mock data.
- **Cost tracking**: reuse `GeminiClient.cost_in_window(3600)` to plot actual spend vs cap.
- **Deployment**: run alongside crawler on localhost; ensure no PII leaves the machine.
- **Security**: if exposed remotely, add basic auth + CORS restrictions; otherwise local-only.

## Open questions / follow-ups
- How to aggregate historical runs (prune old directories vs append to database)?
- Do we need alerting (email/slack) when hourly cap hits or LLM model errors spike?
- Should we persist telemetry to SQLite/Postgres for long-term analytics?

Document owners: crawling/observability team. Update this plan as the dashboard evolves.
