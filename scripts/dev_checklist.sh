#!/usr/bin/env bash
set -euo pipefail
echo "== Oddcrawler Dev Checklist =="
echo "1) Docs changed? Ensure /docs updated and config bumped if needed."
echo "2) Schemas changed? Validate JSON with /config/prompts/analyst_schema.json."
echo "3) Lints/tests pass? (add pre-commit later)"
echo "4) PR links to /docs/backlog.md items?"
