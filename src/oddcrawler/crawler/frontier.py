"""Simple in-memory crawl frontier."""

from __future__ import annotations

import heapq
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional


_COUNTER = 0


@dataclass(order=True)
class FrontierJob:
    priority: float
    order: int = field(compare=True)
    url: str = field(compare=False)


class Frontier:
    """Priority queue frontier with basic dedupe."""

    def __init__(self) -> None:
        self._heap: List[FrontierJob] = []
        self._seen: set[str] = set()
        self._order = 0

    def add(self, url: str, priority: float = 0.0) -> None:
        if url in self._seen:
            return
        self._seen.add(url)
        job = FrontierJob(priority=-priority, order=self._order, url=url)
        self._order += 1
        heapq.heappush(self._heap, job)

    def extend(self, urls: Iterable[str], priority: float = 0.0) -> None:
        for url in urls:
            self.add(url, priority=priority)

    def pop(self) -> Optional[str]:
        if not self._heap:
            return None
        job = heapq.heappop(self._heap)
        return job.url

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._heap)

    # ------------------------------------------------------------------ #
    # Persistence helpers
    # ------------------------------------------------------------------ #
    def export_state(self) -> dict:
        """Return a JSON-serializable snapshot of the frontier."""
        return {
            "order": self._order,
            "seen": sorted(self._seen),
            "heap": [
                {"priority": job.priority, "order": job.order, "url": job.url}
                for job in self._heap
            ],
        }

    @classmethod
    def from_state(cls, state: dict) -> Frontier:
        """Create a frontier from a previously exported state."""
        frontier = cls()
        frontier._order = int(state.get("order", 0))
        seen = state.get("seen", [])
        if isinstance(seen, list):
            frontier._seen = set(str(url) for url in seen if url)
        heap_entries = state.get("heap", [])
        jobs: List[FrontierJob] = []
        if isinstance(heap_entries, list):
            for entry in heap_entries:
                if not isinstance(entry, dict):
                    continue
                url = entry.get("url")
                if not url:
                    continue
                priority = float(entry.get("priority", 0.0))
                order = int(entry.get("order", frontier._order))
                jobs.append(FrontierJob(priority=priority, order=order, url=str(url)))
        frontier._heap = jobs
        heapq.heapify(frontier._heap)
        return frontier

    def save(self, path: Path) -> None:
        """Persist the current frontier state to disk."""
        data = self.export_state()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)

    @classmethod
    def load(cls, path: Path) -> Frontier:
        """Load a frontier state from disk."""
        path = Path(path)
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("Frontier state must be a JSON object")
        return cls.from_state(data)


__all__ = ["Frontier"]
