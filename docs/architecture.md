# Architecture

Oddcrawler is a modular pipeline that *discovers*, *scores*, and *explains* odd corners of the web.
It is designed to be slow, polite, reproducible, and cheap to run.

## Components
- **Seeders**: files, curated lists, small‑web directories (see docs/research-seeds.md).
- **Frontier**: priority queue with exploration/exploitation (novelty, host budgets, historical yield).
- **Fetcher**: HTTP client (polite, retry/jitter) with optional JS rendering (off by default).
- **Tor connector**: optional Stem-managed SOCKS5 proxy with blocklist/backoff for onion domains.
- **Extractor**: trafilatura/readability adapters pull main text + metadata + comments.
- **Feature builders**: cheap HTML/URL/temporal signals → embeddings → anomaly/graph signals.
- **Scoring/Triage**: fuses features into a single *Oddness Score*; decides escalate/persist/skip.
- **Analyst (LLM)**: structured JSON report: summary, why‑flagged, tags, confidence, optional danger mark.
- **Reporter**: weekly digest, cluster briefs, and “neighborhood” maps.
- **Storage**: raw responses (short retention), text, vectors, and link graph.
- **Runtime loop**: `scripts/run_pipeline.py` wraps `OddcrawlerRunner` with persistent frontier state, cached failure lists (404 skipfile, 7-day TTL), telemetry, and checkpoints for long runs.
  - Configure TTL via `run_loop.failure_cache_seconds` in YAML if you need a different horizon.
- **Observability**: tracing, metrics, and cost monitoring.

### Event flow
```
Seeders -> Frontier -> Fetcher -> Extractor -> Feature builders ->
Scoring/Triage -> {Persist, Escalate LLM, or Skip} -> Reporter
                                 |
                                 +-> Storage (raw+text+features+graph)
```

## Pipeline contracts
- **Frontier → Fetcher**
  - Interface: `CrawlJob` object with `url`, `priority`, `budget_context`, `requested_at`.
  - Guarantees: idempotent dequeue (jobs return to queue on failure), host budgets enforced before emitting.
- **Fetcher → Extractor**
  - Interface: `FetchResult` containing `job_ref`, HTTP metadata, raw bytes, and `robots_state`.
  - Guarantees: respects per-host concurrency of 1 by default; retries use exponential backoff; returns structured error codes (timeout, robots-blocked, content-type-denied).
- **Extractor → Feature builders**
  - Interface: `Extraction` bundle with cleaned text, metadata, DOM signals, and normalized headers.
  - Guarantees: extractor redacts PII according to governance before handing off.
- **Feature builders → Scoring**
  - Interface: `FeatureSet` (dict of feature families) plus provenance (hashes, model versions).
  - Guarantees: all feature hooks are pure functions with deterministic output for reproducibility.
- **Scoring → Triage**
  - Interface: `ScoreDecision` with `score`, `reasons`, `thresholds_hit`, and recommended `action {skip,persist,llm}`.
  - Guarantees: scoring surfaces the feature contributions used; thresholds sourced from config snapshots.
- **Triage → Storage/Analyst**
  - Interface: orchestrates persistence of `observation`, optional `dangerous_breadcrumb`, and LLM escalation payloads.
  - Guarantees: failure to persist rolls back downstream actions; LLM calls invoked only when `action == llm`.

### Concurrency & resilience
- Frontier is single-writer, multi-reader safe; workers obtain jobs via lease with heartbeat.
- Fetch failures propagate structured errors to Frontier for backoff adjustment.
- Storage writes are idempotent and keyed by `(url_hash, fetched_at)`; retries overwrite safely.
- Analyst LLM client validates JSON before acknowledge; malformed outputs retry with bounded attempts.

## Prioritization
- **Novelty**: prefer new hosts and neighborhoods.
- **Yield**: bump seeds that historically produced high oddness (multi-armed bandit).
- **Politeness**: per-host caps, sleep windows, robots allow/deny.

## Dedupe & revisits
- **URL-level**: canonicalize, Bloom filter for “seen”.
- **Content-level**: SimHash/MinHash to drop near‑duplicates.
- **Revisit**: use ETag/Last‑Modified TTL; prioritize changed pages.

## Data stores
- Object store/WARC for raw responses (short TTL).
- Vector index for text embeddings (local Qdrant file by default; FAISS can be used for ad-hoc exports).
- Graph store backed by NetworkX (`storage/graph_store.py`) persisted locally with per-node metrics (pagerank, components, reciprocity).
- Postgres (or SQLite for MVP) for findings/metadata.

## Security & sandbox
- Enforce strict MIME types and treat all pages as untrusted.
- Strip/skip scripts; never execute third-party JS except in a headless sandbox when explicitly needed.
- Rate-limit Tor connector separately; maintain a persistent blocklist for abusive hosts and never store onion URLs unredacted outside compliance workflows.
- Illegal-content detector runs before persistence; flagged pages drop storage entirely and hosts move to the Tor blocklist.
