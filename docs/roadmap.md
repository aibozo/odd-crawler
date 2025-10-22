# Roadmap (subject to change)

### Phase A — Skeleton
- Repo scaffolding, docs, configs, schemas.
- Minimal seeds and a “finding record” generator.
- **Exit criteria**
  - Repository structure matches codemap skeleton and passes `scripts/dev_checklist.sh`.
  - Docs in `/docs` cover architecture, governance, and scoring with phase-specific notes.
  - At least one seed list ingested and producing a stub finding record.

### Phase B — MVP Crawler
- Scrapy-based spider obeying robots, polite fetching.
- Extract text with trafilatura; compute cheap features.
- Bloom/SimHash dedupe; basic Oddness fusion.
- Vector store + nearest-neighbor search.
- Gated Analyst LLM with structured outputs.
- Simple feed UI (optional, later).
- BERTopic summaries for interpretability (optional).
- **Exit criteria**
  - Frontier → fetcher → extractor → scoring loop runs end-to-end on a smoke test seed set.
  - Robots/ETag handling verified against two canary domains.
  - Oddness score persisted with feature breakdown; LLM gate configurable and exercised.
  - Dangerous-content breadcrumb flow tested with injected fixtures.

### Phase C — Graph & Topics
- Link-graph capture + cluster detection.
- HDBSCAN + UMAP for exploratory views.
- Topic modeling/drift views (optional).
- Link graph now persists via `storage/graph_store.py` and powers reporter neighborhoods.
- Reporter surfaces graph neighborhoods and topic drift summaries for weekly briefs.
- **Exit criteria**
  - Link graph persisted with per-page metadata and exposed to reporter.
  - Clustering pipeline produces reviewable clusters with metrics logged.
  - Topic drift reports rendered or exported for a sample crawl window.

### Phase D — Tor Connector (strictly opt-in)
- Stem-based connector with allowlists, budgets, and kill-switch.
- No storage of sensitive content; breadcrumbs only.
- Opted for blocklisting + illegal-content detector instead of allowlists to capture diverse small-web voices.
- Tor sessions share SOCKS proxies via Stem; blocklist persists to `var/oddcrawler/tor/blocklist.json` and budgets throttle requests.
- **Exit criteria**
  - Tor connector gated by config flag, persistent blocklist, and kill-switch test suite.
  - Separate rate/budget controls enforced and observable.
  - Compliance review signed off for onion handling (storage, logging, redaction).
