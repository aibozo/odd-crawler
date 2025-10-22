"""Runtime helper to keep the link graph in sync with observations."""

from __future__ import annotations

from typing import Mapping, MutableMapping, Optional

from oddcrawler.storage.graph_store import GraphStore, OutboundLink


class GraphFeatureManager:
    """Updates the persistent link graph and emits per-page metrics."""

    def __init__(
        self,
        storage_config: Optional[Mapping[str, object]] = None,
        *,
        store: Optional[GraphStore] = None,
    ) -> None:
        self.store = store or GraphStore(storage_config=storage_config)

    def enrich_observation(
        self,
        observation: MutableMapping[str, object],
        *,
        fetched_at: str,
        status: int,
    ) -> MutableMapping[str, object]:
        """Record outbound links and update graph-driven features."""
        links_section = observation.get("links") or {}
        outbound = links_section.get("outbound", []) if isinstance(links_section, Mapping) else []
        outbound_links: list[OutboundLink] = []
        for item in outbound:
            if not isinstance(item, Mapping):
                continue
            url = str(item.get("url") or "")
            if not url:
                continue
            anchor = str(item.get("anchor_text") or "")[:160]
            rel = item.get("rel") or []
            if isinstance(rel, str):
                rel_tokens = [rel]
            elif isinstance(rel, (list, tuple)):
                rel_tokens = [str(token) for token in rel]
            else:
                rel_tokens = []
            found_at = str(item.get("found_at") or fetched_at)
            outbound_links.append(OutboundLink(url=url, anchor_text=anchor, rel=tuple(rel_tokens), found_at=found_at))

        features = observation.setdefault("features", {})
        graph_features = features.setdefault("graph", {})
        webring_hits = int(graph_features.get("webring_hits") or 0)

        title = ""
        extract = observation.get("extract")
        if isinstance(extract, Mapping):
            title = str(extract.get("title") or "")

        url = str(observation.get("url") or "")
        if not url:
            return observation

        metrics = self.store.record_page(
            url,
            fetched_at=fetched_at,
            status=status,
            title=title,
            links=outbound_links,
            webring_hits=webring_hits,
        )
        if isinstance(metrics, Mapping):
            graph_features.update(metrics)
        return observation

    def record_score(self, url: str, score: float, *, action: str) -> None:
        self.store.update_score(url, score, action=action)


__all__ = ["GraphFeatureManager"]
