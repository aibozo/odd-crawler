# CODEMAP — Planned Module Layout

```
src/oddcrawler/
  crawler/
    frontier.py        # priority queues, budgets, bandit policy
    fetcher.py         # polite HTTP client, robots, retries
    tor_connector.py   # optional, behind allowlists and kill-switch
  extractors/
    html_clean.py      # trafilatura/readability adapters
    feature_hooks.py   # DOM/URL/temporal signal extraction
  scoring/
    embeddings.py      # sentence-transformers, vector index client
    anomaly.py         # HDBSCAN/IsolationForest utilities
    fusion.py          # Oddness Score fusion & calibration
  storage/
    raw_store.py       # raw/headers/WARC writing
    vector_store.py    # FAISS/Qdrant/Milvus adapters
    graph_store.py     # adjacency capture + NetworkX helpers
    schemas.py         # pydantic models for observation/finding
  agents/
    triage.py          # escalate/skip decisions
    analyst.py         # structured LLM client + validation
    reporter.py        # digest builders
  utils/
    canonical.py       # RFC3986-ish URL normalization
    dedupe.py          # Bloom/SimHash/MinHash helpers
    headers.py         # ETag/Last-Modified helpers
```

**Implementation notes**
- Keep each module testable in isolation.
- Avoid heavy dependencies in `agents/*`; route providers via a thin adapter.
- All public functions should have docstrings with examples.
