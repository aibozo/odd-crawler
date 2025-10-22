# Contributing

## Dev environment
- Python >= 3.10, `uv` or `pip` for deps.
- Optional GPU if you add heavy embedding models later.

## Style
- Black, isort, flake8 (add pre-commit later).
- **Conventional Commits** in PR titles.

## Tests
- Unit tests per module; integration tests for the pipeline.
- Keep synthetic fixtures for HTML/retro cases and encoded-text samples.

## Docs
- Update `/docs/*` and `/config/prompts/*` when behavior changes.
