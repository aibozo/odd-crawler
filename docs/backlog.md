# Backlog Scratchpad (living)

> Use this as a staging area for issues. When ready, move to your tracker of choice.
- **Phase A — Skeleton** (align with roadmap exit criteria)
  - [x] `scripts/dev_checklist.sh`: ensure docs updated and config validated before merge.
  - [x] Draft “dangerous-content” reporting handler (non-public sink) aligned with governance.

- **Phase B — MVP Crawler** (align with roadmap exit criteria)
  - [x] Implement `utils/canonical.py` with RFC3986-ish normalization + tests.
  - [x] `utils/dedupe.py`: Bloom filter wrapper + SimHash; configurable thresholds.
  - [x] `crawler/fetcher.py`: polite client + robots + ETag/Last-Modified support.
  - [x] `extractors/html_clean.py`: trafilatura adapter + comment extraction toggle.
  - [x] `scoring/embeddings.py`: SBERT embedder + FAISS index; nearest neighbors.
  - [x] `scoring/fusion.py`: initial weights + sigmoid score; config-driven gates.
  - [x] `agents/analyst.py`: schema-validated LLM client; retries on invalid JSON.
  - [x] `storage/raw_store.py`: write raw HTML + headers + short TTL policy.
  - [x] `storage/vector_store.py`: lightweight FAISS wrapper.

**Nice-to-have**
- [x] HDBSCAN + UMAP visualization export.
- [x] BERTopic topic summaries (interpretability).
- [x] Qdrant or Milvus backend adapter.

**Phase C — Graph & Topics**
- [x] Capture and persist link graph (extract outbound links, store adjacency/metadata).
- [x] Implement graph analytics and clustering metrics for stored graph.
- [x] Extend reporter to surface graph neighborhoods and topic drift summaries.

**Phase D — Tor Connector (opt-in)**
- [x] Implement Stem-based Tor connector with strict blocklisting (no allowlist) and controller integration.
- [x] Add per-host Tor rate/budget controls with kill-switch and observability hooks.
- [x] Review storage/logging pathways to ensure onion/illegal content is dropped before persistence.

- **Phase E — Oddity Pipeline Refresh**
  - [x] Capture baseline crawl metrics (rate, cost, odd-hit %) and document instrumentation updates in `docs/observability.md`.
  - [x] Redesign frontier scheduler with priority scoring (host politeness, novelty, oddity priors, depth penalties) and bandit host allocation.
  - [ ] Tune frontier weights/cooldowns via telemetry replay and document recommended defaults.
  - [x] Implement staged triage cascade (HEAD/byte-range probe, fingerprints, regex skim, SimHash, cheap classifier, embedding gate) with decision logging.
  - [ ] Benchmark cascade false-negative rate on curated odd pages; adjust weights/keywords accordingly.
  - [ ] Refit cascade logistic weights with expanded crawl telemetry (≥100 pages) and document overrides vs. skip ratios.
  - [ ] Add anchor-density features and low-cost keyword embedding gate to cascade classifier; update config with new weights.
  - [ ] Extend frontier feedback to down-rank hosts with persistent low-density skip ratio (>90% after overrides).
  - [ ] Create cascade validation script/notebook to re-run synthetic + 300-seed crawls and report odd-hit vs. skip outcomes automatically.
  - [ ] Expand oddity feature extraction (lexical, structural, platform fingerprints) and add representative unit tests.
  - [ ] Train and wire a lightweight LR/XGB model for boring vs promising classification; document retraining workflow in `docs/scoring.md`.
  - [ ] Curate mainstream vs weird embedding galleries; integrate ANN distance contrast into scoring config.
  - [ ] Add forum/webring detectors and link-promotion rules; capture extractor profile requirements in `/profiles/` docs.
  - [ ] Stand up active-learning review loop (export queue, nightly retrain script) and note cadence in `docs/backlog.md` + `docs/roadmap.md`.
  - [ ] Audit safety/compliance impacts (robots, dangerous content handling) and update `docs/data-governance.md` as needed.
  - [ ] Extend telemetry/event schema with stage + score breakdowns; surface dashboards/checks in `docs/observability.md`.
