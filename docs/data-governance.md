# Data Governance & Safety

## Goals
- Preserve user privacy and legal compliance.
- Avoid collecting minors’ content and sensitive PII.
- Mark potentially dangerous content for controlled reporting.

## Storage responsibilities
- **`storage/raw_store.py`**: writes raw HTML/WARC blobs behind a config flag. Applies a default 30-day TTL, enforces MIME allowlist, and skips persistence when governance rules require excerpt-only mode.
- **`storage/vector_db.py` / `storage/vector_store.py`**: persist embeddings to a local Qdrant file (default) or alternative store after PII scrubbing.
- **`storage/graph_store.py`**: persist derived edges only after PII scrubbing.
- **`agents/triage.py`**: decides whether a page is stored as full observation, excerpt-only, or dropped; ensures compliance metadata (pseudonym salt version, redaction flags) is attached.
- **`storage/compliance.py`**: records `dangerous_breadcrumb` entries with hashed URL, category, timestamp, and redacted 200-char excerpt.
- Configuration switches live under `/config/storage.yaml`; any change must update TTL or retention notes here and in the changelog.
- Malware/abuse blocklists live in `config/safety/`. The crawler enforces `blocklist_hosts.txt` before fetching, logs every skip, resolves the actual peer IP, and surfaces per-host/IP counts in telemetry even if DNS is poisoned mid-flight.
- `crawl.blocklist_refresh_seconds` controls how frequently the fetcher reloads `blocklist_hosts.txt` at runtime so scheduler jobs can update the list without restarting the crawl.
- `dashboard.blocklist.*` governs the telemetry service refresh cadence (auto-refresh toggle, interval, max hosts, and source URL) so operators can keep URLhaus data fresh while monitoring runs.
- Hosts explicitly allowlisted for insecure TLS fetches are still recorded, but the fetcher marks the response as `transport="insecure_text_only"` and skips raw HTML persistence so only redacted excerpts ever persist.
- Storage paths derived from that config resolve relative to the repo root by default (`var/oddcrawler/...`) so governance reviews can locate persisted artifacts quickly.

## Pseudonymization (tracked & stable)
- Compute `pseudonym = BASE32(HMAC_SHA256(secret_salt, identifier))[:12]`.
- Never log the raw `identifier`. Keep `hash(identifier)` (with a different salt) for dedupe only.
- Rotate `secret_salt` periodically; maintain a separate encrypted key map for rotation windows.
- Rotation cadence: quarterly by default; track active salt IDs in a secure secrets store and include the `salt_version` on persisted records.

## PII minimization
- Default: store **only text excerpts** (not entire pages) unless whitelisted.
- Strip emails, phone numbers, GPS/addresses, and faces from excerpts.
- Purge images by default to reduce implicit PII.
- Enforced by extractor hooks that redact before `FeatureSet` generation; raw_store double-checks with regex-based filters prior to writing.

## Minor-safety
- Maintain blocklists of domains/paths known to host or target minors.
- If minor-related content is detected: **drop immediately**, log breadcrumb only, and mark `dangerous_content.category = "other"` with notes `"minor-safety"`. Never persist text.

## Dangerous content marking
- Categories: `self-harm`, `illegal-trade`, `adult`, `extremist`, `violent`, `other`.
- If detected:
  - Do **not** persist full text or media.
  - Keep `url_hash`, time, and a redacted, <=200-char excerpt if necessary for internal triage.
  - Do not share publicly; route only to private, authorized reporting channels.
- Breadcrumb records live alongside observations with a shared ID; analyst LLM outputs must set `dangerous_content.present = true` and trigger the breadcrumb writer.

## Tor/onion
- Tor crawling is **off by default** and requires an explicit config flag. We route through a Stem-managed SOCKS proxy with per-host/global rate limits and a persistent blocklist.
- Illegal content detector runs before persistence; if triggered, the host is blocklisted long-term and no raw/excerpt data is written (only minimal internal telemetry).
- Never store onion URLs/plaintext externally without redaction. No illegal content—full stop.

## Retention
- Raw HTML/screenshots: short TTL (e.g., 30 days).
- Text excerpts and features: long-term, provided they are PII-free.
- Any flagged dangerous pages: keep only minimal breadcrumbs.
- Retention policies are enforced by `scripts/purge_storage.py` and must be logged to observability dashboards.
