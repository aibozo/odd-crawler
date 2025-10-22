"""Persistent link graph storage built on top of NetworkX."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import networkx as nx

from urllib.parse import urlsplit

from oddcrawler.storage.config import load_storage_config, resolve_section_path

# Maximum number of anchor texts we keep per edge to avoid unbounded growth.
_ANCHOR_HISTORY = 5
# Maximum items stored in score history per node.
_SCORE_HISTORY = 10


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class OutboundLink:
    url: str
    anchor_text: str
    rel: Sequence[str]
    found_at: str


class GraphStore:
    """Local storage helper for the crawl link graph."""

    def __init__(
        self,
        storage_config: Optional[Mapping[str, object]] = None,
        *,
        graph_path: Optional[Path] = None,
    ) -> None:
        self.config = storage_config or load_storage_config()
        if graph_path is None:
            graphs_dir = resolve_section_path("graphs", dict(self.config))
            graphs_dir.mkdir(parents=True, exist_ok=True)
            graph_path = graphs_dir / "link_graph.json"
        self.graph_path = graph_path
        self.graph = nx.DiGraph()
        self._pagerank_cache: Optional[Mapping[str, float]] = None
        self._pagerank_dirty = True
        self._load()

    # --------------------------------------------------------------------- #
    # Persistence helpers
    # --------------------------------------------------------------------- #
    def _load(self) -> None:
        if self.graph_path.exists():
            with self.graph_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            self.graph = nx.node_link_graph(data, directed=True, multigraph=False, edges="links")
        else:
            self.graph = nx.DiGraph()

    def persist(self) -> None:
        data = nx.node_link_data(self.graph, edges="links")
        tmp_path = self.graph_path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        tmp_path.replace(self.graph_path)

    # --------------------------------------------------------------------- #
    # Graph mutation and metrics
    # --------------------------------------------------------------------- #
    def record_page(
        self,
        source_url: str,
        *,
        fetched_at: str,
        status: int,
        title: str,
        links: Iterable[OutboundLink],
        webring_hits: int = 0,
    ) -> Mapping[str, float | int | str | bool]:
        """Upsert node metadata and outbound edges for a crawled page."""
        node = self._ensure_node(source_url)
        node["last_seen"] = fetched_at
        node.setdefault("first_seen", fetched_at)
        node["observations"] = int(node.get("observations", 0)) + 1
        node["status"] = int(status)
        if title:
            node["title"] = title[:200]
        node["webring_hits"] = int(node.get("webring_hits", 0)) + int(webring_hits)

        processed_links: List[OutboundLink] = []
        for link in links:
            if link.url == source_url:
                continue
            processed_links.append(link)
            self._record_edge(source_url, link)

        node["outbound_count"] = len(processed_links)
        node["outbound_domains"] = len({urlsplit(link.url).netloc for link in processed_links})

        self._pagerank_dirty = True
        metrics = self._compute_metrics(source_url, webring_hits=webring_hits)
        self.persist()
        return metrics

    def update_score(self, url: str, score: float, *, action: str) -> None:
        """Persist the latest scoring decision for a node."""
        if url not in self.graph:
            return
        node = self.graph.nodes[url]
        history = deque(node.get("score_history", []), maxlen=_SCORE_HISTORY)
        history.append({"score": float(score), "action": action})
        node["score_history"] = list(history)
        node["last_score"] = float(score)
        node["last_action"] = action
        self.persist()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _ensure_node(self, url: str) -> MutableMapping[str, object]:
        if url not in self.graph:
            self.graph.add_node(
                url,
                url=url,
                first_seen=None,
                last_seen=None,
                observations=0,
                title="",
                status=None,
                webring_hits=0,
                outbound_count=0,
                outbound_domains=0,
                last_score=0.0,
            )
        return self.graph.nodes[url]

    def _record_edge(self, source_url: str, link: OutboundLink) -> None:
        self._ensure_node(link.url)
        edge_data = self.graph.get_edge_data(source_url, link.url, default={})
        weight = int(edge_data.get("weight", 0)) + 1
        anchor_texts: List[str] = list(edge_data.get("anchor_texts", []))
        if link.anchor_text:
            if link.anchor_text not in anchor_texts:
                anchor_texts.append(link.anchor_text)
            anchor_texts = anchor_texts[-_ANCHOR_HISTORY:]

        rels = set(edge_data.get("rel", []))
        rels.update(link.rel)

        self.graph.add_edge(
            source_url,
            link.url,
            weight=weight,
            last_seen=link.found_at,
            anchor_texts=anchor_texts,
            rel=sorted(rels),
        )

    def _compute_metrics(self, url: str, *, webring_hits: int) -> Mapping[str, float | int | str | bool]:
        if url not in self.graph:
            return {}

        g = self.graph
        out_deg = g.out_degree(url)
        in_deg = g.in_degree(url)
        reciprocity = len(set(g.successors(url)).intersection(g.predecessors(url)))
        weak_components = list(nx.weakly_connected_components(g))
        component_id = ""
        component_size = 1
        density = 0.0
        for component in weak_components:
            if url in component:
                component_size = len(component)
                component_id = _component_identifier(component)
                if component_size > 1:
                    density = nx.density(g.subgraph(component).to_undirected())
                break

        pagerank = self._pagerank().get(url, 0.0)
        high_score_neighbors = 0
        total_neighbors = 0
        for neighbor in g.successors(url):
            total_neighbors += 1
            neighbor_score = _safe_float(g.nodes[neighbor].get("last_score"))
            if neighbor_score >= 0.35:
                high_score_neighbors += 1
        odd_neighbor_ratio = (high_score_neighbors / total_neighbors) if total_neighbors else 0.0

        # Graph contribution score: heuristics emphasising webrings + tightly-knit components
        score = 0.0
        if webring_hits:
            score += min(0.4, 0.2 + 0.1 * webring_hits)
        score += min(out_deg / 15.0, 0.2)
        score += min(reciprocity / 5.0, 0.15)
        score += min(component_size / 12.0, 0.15)
        score += min(pagerank * 5.0, 0.1)
        score += min(odd_neighbor_ratio * 0.2, 0.2)
        score = min(score, 1.0)

        node = g.nodes[url]
        node["pagerank"] = pagerank
        node["component_id"] = component_id
        node["component_size"] = component_size
        node["component_density"] = density
        node["reciprocal_links"] = reciprocity
        node["odd_neighbor_ratio"] = odd_neighbor_ratio
        node["graph_score"] = score

        return {
            "score": score,
            "out_degree": out_deg,
            "in_degree": in_deg,
            "reciprocal_links": reciprocity,
            "component_id": component_id,
            "component_size": component_size,
            "component_density": density,
            "pagerank": pagerank,
            "odd_neighbor_ratio": odd_neighbor_ratio,
            "has_webring": bool(node.get("webring_hits")),
            "webring_hits": int(node.get("webring_hits", 0)),
        }

    def _pagerank(self) -> Mapping[str, float]:
        if not self._pagerank_dirty and self._pagerank_cache is not None:
            return self._pagerank_cache
        if self.graph.number_of_nodes() == 0:
            self._pagerank_cache = {}
        else:
            try:
                self._pagerank_cache = nx.pagerank(self.graph, alpha=0.85, max_iter=100)
            except nx.PowerIterationFailedConvergence:
                # Fall back to uniform distribution if convergence fails.
                uniform = 1.0 / max(self.graph.number_of_nodes(), 1)
                self._pagerank_cache = {node: uniform for node in self.graph.nodes}
        self._pagerank_dirty = False
        return self._pagerank_cache or {}


def _component_identifier(nodes: Iterable[str]) -> str:
    ordered = sorted(nodes)
    joined = "|".join(ordered)
    # A lightweight deterministic identifier.
    return hex(abs(hash(joined)) % (1 << 32))[2:]


__all__ = ["GraphStore", "OutboundLink"]
