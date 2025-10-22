# Compliance & Operational Policy (Non‑legal)

> This document is not legal advice. Follow local laws and each site’s Terms.

## Robots/ToS
- Always honor `robots.txt` and site Terms. If disallowed: **skip**.
- Identify with a descriptive UA and contact email.
- Use per‑host rate limits and exponential backoff on errors.

## Sensitive content
- No collection of illegal or abusive material. If encountered, do not persist content; only minimal breadcrumb metadata.

## Requests from site owners
- Provide a clear contact path. On verified removal requests, delete associated records and honor future blocks.

## Tor
- Only crawl allowlisted onion services with clear, legal content. Apply stricter budgets and never store sensitive material.
- Keep an immediate kill‑switch for Tor connector.

## Auditing
- Every finding must be reproducible with: URL, timestamp, headers, content hashes, and the feature explanation.
