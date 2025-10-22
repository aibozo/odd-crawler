from __future__ import annotations

import json
from pathlib import Path

from .runner import OddcrawlerRunner


def load_seed_urls(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    hosts = payload.get("hosts", [])
    return [entry.get("url") for entry in hosts if isinstance(entry, dict) and entry.get("url")]


def main() -> None:
    seeds_path = Path("examples/seeds.json")
    seeds = [url for url in load_seed_urls(seeds_path) if url]
    if not seeds:
        print("No seeds available. Add URLs to examples/seeds.json.")
        return

    runner = OddcrawlerRunner()
    runner.add_seeds(seeds[:3])
    results = runner.run(max_pages=1)
    for result in results:
        print(f"Processed {result.url} -> score {result.decision.score:.2f} ({result.decision.action})")


if __name__ == "__main__":
    main()
