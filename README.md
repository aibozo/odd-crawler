# Oddcrawler

> **Strange‑web cartographer.** Oddcrawler explores niche, low‑traffic parts of the web (optionally Tor) and
surfaces pages with unusual aesthetics, encoded chatter, or “odd” community signals — then explains *why* they were flagged.

## What’s here

- A documentation‑first repo so an autonomous/dev agent can get productive immediately.
- Safety/ethics guardrails (robots, PII minimization, minor‑safety, illegal‑content blocks).
- Architecture, data schema, scoring design, and experiment scratchpads.
- Lightweight Python package scaffolding (`src/oddcrawler`) you can flesh out later.

## Quick start (docs first)
1. Read **AGENTS.md** for mission, rules, and operating procedures.
2. See **docs/architecture.md** and **docs/scoring.md** to understand the pipeline and Oddness Score.
3. Check **docs/data-governance.md** for anonymization and safety.
4. Open **docs/roadmap.md** and **docs/backlog.md** to pick tasks.
5. Configure **config/default.yaml** (budgets, thresholds, seeds) and adjust **examples/seeds.json**.
6. Create a virtualenv and install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
7. Copy `.env.example` to `.env` and set `GEMINI_API_KEY` for Gemini access (the `.env` file stores secrets only).

> ⚠️ **Legal & ethical**: Respect `robots.txt` and site Terms at all times. Do not collect PII or illegal/abusive material.
Tor crawling is strictly opt‑in with allowlists and heightened safeguards. See **docs/compliance.md**.

## Repository layout
```
odd-crawler/
├─ AGENTS.md                    # The agent’s playbook + working agreements
├─ README.md
├─ LICENSE
├─ pyproject.toml               # Minimal project metadata; expand as you add code
├─ requirements.txt             # Suggested libs; trim/expand as needed
├─ .gitignore
├─ config/
│  ├─ default.yaml              # Configurable thresholds, budgets, and policies
│  └─ prompts/                  # Structured prompts the agent can use
├─ docs/
│  ├─ architecture.md           # Full architecture spec
│  ├─ scoring.md                # Features + Oddness Score + gating
│  ├─ dataspec.md               # JSON Schemas for findings and observations
│  ├─ cache.md                  # Dedupe, canonicalization, Bloom/SimHash/MinHash, revisits
│  ├─ data-governance.md        # Pseudonymization, minor-safety, dangerous-content marking
│  ├─ compliance.md             # Robots/ToS, legal, Tor rules (strict)
│  ├─ llm-prompts.md            # Structured prompt specs and JSON schema
│  ├─ observability.md          # Metrics, tracing, cost controls
│  ├─ research-seeds.md         # Where to look (safe sources)
│  ├─ codemap.md                # Detailed code map (planned)
│  ├─ contributing.md           # Contribution guidelines
│  ├─ roadmap.md                # Milestones and deliverables
│  └─ backlog.md                # Task backlog scratchpad
├─ examples/
│  ├─ seeds.json                # Starter seed list (safe)
│  └─ config.sample.yaml
├─ src/
│  └─ oddcrawler/
│     ├─ __init__.py
│     ├─ __main__.py
│     ├─ crawler/               # Frontier + fetchers (future code)
│     ├─ extractors/            # HTML/text extraction
│     ├─ scoring/               # Feature builders + oddness model
│     ├─ storage/               # WARC/raw store + vectors + graph
│     ├─ agents/                # Orchestration + LLM steps
│     └─ utils/                 # Canonicalization, hashing, helpers
└─ scripts/
   ├─ make_finding_example.py   # Generates a demo finding record
   ├─ dev_checklist.sh          # Dev checklist for PRs
   ├─ export_clusters.py        # UMAP + HDBSCAN export from saved embeddings
   └─ topic_summary.py          # BERTopic summaries from a document set
```

## Status
- **2025-10-22**: Documentation skeleton + config seeds + minimal package structure.
