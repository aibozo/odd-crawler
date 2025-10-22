# Tor Connector

Oddcrawler ships with an optional Tor connector that routes requests through a local Tor instance using Stem. It is disabled by default.

## Enabling
1. Ensure Tor is running locally (default SOCKS `127.0.0.1:9050`, control port `9051`).
2. Update `config/default.yaml` or your override file:
   ```yaml
   crawl:
     allow_tor_connector: true
     tor:
       enabled: true
       socks_host: 127.0.0.1
       socks_port: 9050
       control_port: 9051
       control_password: null  # provide if Tor requires one
       per_host_requests_per_minute: 3
       global_requests_per_minute: 30
       failure_block_minutes: 30
       max_failures_per_host: 3
       illegal_block_days: 365
       blocklist_path: var/oddcrawler/tor/blocklist.json
       route_domains: []
       route_onion_only: true
   ```

With `route_onion_only: true`, only `.onion` domains (and those listed in `route_domains`) are proxied. Set it to `false` to force specific domains through Tor.

## Blocklist & budgets
- Budgets: per-host and global request caps enforce a minimum interval between requests. They apply **only** to Tor traffic.
- Failures: once a host produces `max_failures_per_host` consecutive errors, it is blocked for `failure_block_minutes` before retries resume.
- Illegal content: the illegal-content detector runs before any storage happens. When it triggers, the host is added to the blocklist for `illegal_block_days`, no storage occurs, and future requests are skipped.
- The blocklist persists to `var/oddcrawler/tor/blocklist.json`. Remove an entry manually only after a compliance review.

## Kill-switch & identity rotation
- `TorConnector.renew_identity()` sends a `NEWNYM` signal via Stem; wire it into operational tooling if you need manual rotation.
- Setting `crawl.allow_tor_connector: false` (or `tor.enabled: false`) fully disables the connector without additional code changes.

## Safety defaults
- Illegal content never reaches storage (raw, excerpt, or vector stores). Only minimal internal telemetry is kept to record the skip.
- Onion URLs are redacted in logs and downstream reports.
- Keep the local Tor instance patched and isolate it (no shared system-wide proxy) to minimize cross-traffic risk.

## Troubleshooting
- If requests fail with `TorPolicyError`, consult the blocklist JSON for the reason.
- Ensure `PySocks` and `stem` are installed (both are declared in `requirements.txt`).
- For control-port auth failures, set `control_password` to the Tor hashed password or configure cookie authentication.
