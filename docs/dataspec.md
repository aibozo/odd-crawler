# Data Specification

## Entities

### `observation`
One fetch event for a URL.
```json
{
  "url": "https://example.net/page.html",
  "url_canonical": "https://example.net/page.html",
  "fetched_at": "2025-10-22T12:34:56Z",
  "status": 200,
  "headers": {"etag": "W/"abc"", "last-modified": "Mon, 01 Jan 1990 00:00:00 GMT"},
  "hashes": {"url_sha1": "...", "content_simhash": "..."},
  "extract": {
    "lang": "en",
    "title": "Example",
    "text_excerpt": "First 500 chars...",
    "token_count": 1234
  },
  "features": {
    "html_retro": {"marquee":1,"blink":0,"tables_for_layout":1,"gif_bg":0},
    "url_weird": {"base64_param": false, "cgi_bin": false, "tilde_home": true},
    "semantic": {"nn_dist": 0.24, "seed_neighbors": ["seed/arg_01","seed/retro_04"]},
    "anomaly": {"hdbscan_noise": 0.7},
    "graph": {"webring_widget": 1, "outdeg": 8, "indeg_est": 1}
  },
  "prelim_score": 0.74,
  "storage_policy": "excerpt-only",
  "salt_version": "2025Q1"
}
```

### `finding`
LLM-structured analysis of an observation (only when escalated).
```json
{
  "url": "https://example.net/page.html",
  "summary": "Short neutral summary...",
  "why_flagged": [
    "webring widget in footer",
    "retro HTML (<marquee>, table layout)"
  ],
  "risk_tag": "harmless-retro",
  "dangerous_content": {"present": false, "category": "none", "notes": ""},
  "confidence": 0.77,
  "observation_ref": "observation:2025-10-22T12:34:56Z:abcd"
}
```

### `report_entry`
Digest material (weekly).

### `dangerous_breadcrumb`
Minimal record stored when dangerous content is suspected.
```json
{
  "url_hash": "sha256:abcd...",
  "observed_at": "2025-10-22T12:34:56Z",
  "category": "extremist",
  "reason": "LLM analyst flagged violent recruitment language",
  "excerpt_redacted": "[REDACTED] ... recruitment slogans ...",
  "source": "analyst",
  "salt_version": "2025Q1"
}
```

## JSON Schemas
- See `/config/prompts/analyst_schema.json` for `finding` schema.
- Define `observation` schema in code using `pydantic` (mirrors the example above).
- Define `dangerous_breadcrumb` schema in code and ensure storage layer validates against it.

## Pseudonymization
- Identifiers (author handles, forum IDs) are **never** stored raw.
- Store `pseudonym` and a salted one-way hash for dedupe. Keys are rotated and stored separately.
- Include the `salt_version` string on every record to support rotation audits.
