# AGENTS.md — Oddcrawler Agent Playbook

**Mission:** Build and run an ethical explorer that discovers and explains the “small & strange web.”
Surface interesting/odd content, *explain why it was flagged*, and keep costs & risks low.

## Environment Setup
- Use Python 3.10+ with a project-local virtualenv: `python3 -m venv .venv && source .venv/bin/activate`.
- Install dependencies inside that venv with `pip install -r requirements.txt` (add new packages there and update the file).
- Always run Python commands via the venv interpreter, e.g. `.venv/bin/python -m unittest ...`.

## Core rules (always)
1. **Respect `robots.txt` and site Terms**. If unsure, skip. Document decisions in PRs.
2. **Do not collect or publish PII.** Redact names, emails, faces, and exact addresses by default.
3. **Avoid minor‑prone sites** and content containing or targeting minors. If detected, drop immediately.
4. **No illegal content, full stop.** If a page appears illegal/abusive, log a minimal hashed pointer and do not persist the content. Escalate via reporting flow.
5. **Be slow and polite.** Low rate per host; exponential backoff; identify as Oddcrawler in UA.
6. **Reproducibility over cleverness.** Every finding has features + evidence + a clear rationale.
7. **Cost discipline.** LLM calls are gated and budget‑capped; prefer cheap features first.
8. **Explain changes.** Any change to architecture, thresholds, or storage must update the docs and the changelog.

## High‑level workflow
- **Frontier** pulls seeds → prioritizes with novelty/oddness priors → obeys per‑host budgets.
- **Fetcher** retrieves HTML (JS fallback when necessary), records headers, ETag/Last‑Modified.
- **Extractor** gets main text + metadata and flags retro/URL/linguistic signals.
- **Scoring** fuses signals → *Oddness Score*. If ≥ `llm_gate_threshold`, call Analyst LLM.
- **Analyst** writes a structured JSON finding with summary, why‑flagged, risk tag, and confidence.
- **Reporter** aggregates weekly digest + cluster briefs.
- **Storage** retains raw HTML short-term; text/features long-term; vectors/graph for exploration.
  - Embedding vectors persist to a local Qdrant file at `var/oddcrawler/vectors/qdrant.db` by default.

## Lightweight codemap
See **docs/codemap.md** for the full plan. Short version:
```
src/oddcrawler/
  crawler/    # frontier + polite fetching (+ optional Tor connector)
  extractors/ # trafilatura/readability adapters + feature hooks
  scoring/    # heuristics, embeddings, anomaly, fusion
  storage/    # raw/WARC, vector index, graph
  agents/     # triage/summarizer/reporter orchestration
  utils/      # canonicalize URLs, Bloom/SimHash/MinHash, ETag helpers
```

## Keeping context up‑to‑date
- **Single source of truth** for design is in `/docs`. When behavior changes, update docs in the same PR.
- Maintain `/docs/backlog.md` (what’s planned) and `/docs/roadmap.md` (when we intend to deliver).
- When you finish a task, immediately update `/docs/backlog.md` so it reflects the current status (check off completed items, add follow-ups).
- Add a brief **changelog entry** in PR description. The Release Manager will roll them up into tagged releases.
- Every LLM prompt or schema change → bump a minor version in `/config/prompts/` and note in PR.

## Git & branch model
- Default branch: `main` (protected). Feature branches: `feat/*`, fixes `fix/*`, chores `chore/*`.
- **Conventional Commits** style: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
- Pull Requests must:
  - Link to at least one task in `/docs/backlog.md`.
  - Include **doc updates** if behavior/interfaces changed.
  - Pass **dev checklist** (`scripts/dev_checklist.sh`).

## Dangerous content marking (twofold mode)
- If suspected dangerous content is encountered, **do not persist full text**. Store a minimal record:
  - `url_hash`, `observed_at`, `category`, short `reason`, and an optional 200‑char excerpt with redactions.
- The Analyst LLM outputs a `dangerous_content` object per the JSON schema in `/config/prompts/analyst_schema.json`.
- Reporting destinations/configurable handlers are defined in `/docs/compliance.md` (never public posts).

## Anonymization (tracked pseudonyms)
- Use **keyed HMAC‑SHA256** with a private salt to derive stable pseudonyms from identifiers (e.g., usernames).
- Example: `pseudo = BASE32(HMAC_SHA256(salt, identifier))[:12]`.
- Never log the raw identifier; store only the pseudonym and a one‑way hash of the identifier for dedupe.
- Rotate the salt on a schedule; maintain a key‑rotation map stored separately and access‑controlled.

## Experiments
- Use **docs/experiments.md** as a scratchpad. For each experiment capture:
  - Hypothesis, parameters (thresholds, model choices), datasets/seeds, metrics, and decision.
  - Summarize results in **/docs/roadmap.md** if they change default config.

## Where to find things
- Architecture → **docs/architecture.md**
- Score/Features → **docs/scoring.md**
- Data Schemas → **docs/dataspec.md**
- Dedupe & Revisit → **docs/cache.md**
- Safety & Governance → **docs/data-governance.md**, **docs/compliance.md**
- Prompts & Schemas → **docs/llm-prompts.md**
- Observability → **docs/observability.md**
- Telemetry Dashboard roadmap → **docs/dashboard.md**
- Big codemap → **docs/codemap.md**

## Helpful scripts
- `.venv/bin/python scripts/run_pipeline.py [--run-dir var/runs/<name>]` — long-running crawl with on-disk checkpoints, metrics, and telemetry.
- `.venv/bin/python scripts/update_blocklist.py --source var/oddcrawler/safety/urlhaus.txt --output config/safety/blocklist_hosts.txt` — rebuild the malware host blocklist (documented in `docs/data-governance.md`).
- `.venv/bin/python scripts/export_clusters.py <embedding_artifact_dir> clusters.csv` — generate UMAP/HDBSCAN layouts from saved embeddings.
- `.venv/bin/python scripts/topic_summary.py <documents.jsonl> topics.json` — produce BERTopic summaries for interpretability.
- `.venv/bin/python scripts/dashboard_api.py` — run the local telemetry API (set `dashboard.blocklist.auto_refresh` in config to keep the URLhaus blocklist fresh while the UI is open).
- Link graph artifacts live at `var/oddcrawler/graphs/link_graph.json`; instantiate `oddcrawler.agents.reporter.Reporter` inside the venv to surface graph neighborhoods and topic drift summaries for briefs.
- Tor connector is optional: see `docs/tor-connector.md` for enabling via config and managing the blocklist (`var/oddcrawler/tor/blocklist.json`). Illegal-content hits auto-block hosts and skip storage, so review that list before re-enabling.
- Each run directory contains `telemetry.jsonl` (page events), `metrics.json`, `reports/summary.json`, and `state/frontier.json`/`state/failures.json` for crash-safe resumes and cached 404s (failure entries expire after ~7 days).

never tell the user to run a command/make a patch unless its not an option within the codex sandbox. the agent should always apply patches, never instruct to apply patches. the only thing the user should be instructed to edit is .env for keys. 
