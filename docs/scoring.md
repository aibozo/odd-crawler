# Oddness Score & Gating

We combine cheap signals with moderate-cost ML and use LLMs sparingly.

## Feature families
1. **HTML retro signals**
   - `<blink>`, `<marquee>`, `<font>`, `<center>`, framesets, table-based layout, guestbooks, webrings.
   - Animated GIF counters, 88x31 buttons, tiled backgrounds.
2. **URL/infra signals**
   - Long query strings with base64/hex, `cgi-bin/`, `/~user` homepages, suspicious key names.
   - HTTP only, self-signed certs, very old copyright years vs. recent content.
3. **Semantic similarity**
   - Sentence-Transformer embeddings; nearest neighbors to curated “odd” seed set.
4. **Anomaly/outlierness**
   - HDBSCAN noise probability; IsolationForest score; lexical rarity.
5. **Graph/neighborhood**
  - Low indegree, webring membership, tight cluster with other odd pages.
  - Features include out/in-degree, reciprocity, component size/density, PageRank, and ratio of odd neighbors.
6. **Coded language cues (signals-only)**
   - Acrostic likelihood, ROT13/base64 blobs, homoglyph overuse, numeric key repetitions.

## Fusion
A simple, interpretable fusion works well:

```
raw =  w1*retro_html + w2*url_weird + w3*semantic + w4*anomaly + w5*graph + b
score = sigmoid(raw)
```

Start with weights from heuristics; refine via small labeled sets (active learning).

## Gates & actions
- `score < persist_threshold`  → log a tiny breadcrumb, no LLM.
- `persist_threshold ≤ score < llm_gate_threshold` → persist minimal record + vector; no LLM.
- `score ≥ llm_gate_threshold` → call Analyst LLM (JSON schema), store full finding.
- `score ≥ alert_threshold` → flag for weekly digest.

## Default thresholds & config
- `persist_threshold = 0.35`, `llm_gate_threshold = 0.60`, `alert_threshold = 0.80` (tunable).
- Stored in `/config/scoring.yaml` alongside feature weights and model version hashes.
- Every scoring decision writes `thresholds_hit` into the `ScoreDecision`, enabling audits.
- Changes to thresholds require a doc update (this file) and a changelog entry summarizing rationale.

## Calibration
- Keep a validation set from multiple neighborhoods (retro-art, paranormal, ARG, fringe).
- Monitor drift: if “odd” becomes too common, raise gates or tighten features.
- Calibration workflow:
  1. Sample labeled crawl windows monthly; ensure at least 20 findings per domain cohort.
  2. Recompute feature contributions offline and compare ROC/AUC vs. previous month.
  3. Adjust weights/thresholds in a branch, run `scripts/calibrate_scoring.py` (planned) to emit suggested parameters.
  4. Replay a canary crawl to verify LLM call volume change ≤10% before merging.
- Observability hooks emit `scoring_gate_hits`, `scoring_llm_calls`, and `llm_budget_remaining` metrics; thresholds must trigger alerts when drift > 2σ over rolling 7-day windows.
