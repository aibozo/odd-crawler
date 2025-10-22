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
