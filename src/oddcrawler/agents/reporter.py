"""Reporter surfaces graph neighborhoods and topic drift summaries."""

from __future__ import annotations

from typing import Iterable, List, Mapping, Optional, Sequence

import networkx as nx

from oddcrawler.storage import GraphStore, load_storage_config


class Reporter:
    """Generate human-readable summaries from stored crawl artifacts."""

    def __init__(self, storage_config: Optional[Mapping[str, object]] = None) -> None:
        self.config = storage_config or load_storage_config()
        self.graph_store = GraphStore(storage_config=self.config)

    # ------------------------------------------------------------------ #
    # Graph neighborhoods
    # ------------------------------------------------------------------ #
    def graph_neighborhoods(self, *, limit: int = 5, min_score: float = 0.0) -> List[dict]:
        """Return ego-centric neighborhoods for top odd pages."""
        graph = self.graph_store.graph
        if graph.number_of_nodes() == 0:
            return []

        ranked_nodes = sorted(
            graph.nodes,
            key=lambda node: (
                float(graph.nodes[node].get("last_score", 0.0)),
                float(graph.nodes[node].get("graph_score", 0.0)),
                graph.out_degree(node),
            ),
            reverse=True,
        )

        neighborhoods: List[dict] = []
        for node in ranked_nodes:
            if len(neighborhoods) >= limit:
                break
            node_data = graph.nodes[node]
            score = float(node_data.get("last_score") or node_data.get("graph_score") or 0.0)
            if score < min_score and len(neighborhoods) >= limit:
                continue

            ego = nx.ego_graph(graph, node, radius=1, undirected=False)
            neighbors = []
            for neighbor in ego.nodes:
                if neighbor == node:
                    continue
                edge_data = graph.get_edge_data(node, neighbor, {}) or {}
                neighbors.append(
                    {
                        "url": neighbor,
                        "edge_weight": int(edge_data.get("weight", 0)),
                        "reciprocal": graph.has_edge(neighbor, node),
                        "last_score": float(graph.nodes[neighbor].get("last_score", 0.0)),
                        "last_seen": graph.nodes[neighbor].get("last_seen"),
                    }
                )
            neighbors.sort(key=lambda item: item["last_score"], reverse=True)
            neighborhoods.append(
                {
                    "center": {
                        "url": node,
                        "title": node_data.get("title"),
                        "last_score": score,
                        "component_id": node_data.get("component_id"),
                        "component_size": node_data.get("component_size"),
                        "pagerank": node_data.get("pagerank"),
                        "webring_hits": node_data.get("webring_hits"),
                        "last_seen": node_data.get("last_seen"),
                    },
                    "neighbors": neighbors,
                }
            )

        return neighborhoods

    # ------------------------------------------------------------------ #
    # Topic drift summaries
    # ------------------------------------------------------------------ #
    @staticmethod
    def topic_drift_summary(
        previous_topics: Sequence[Mapping[str, object]],
        current_topics: Sequence[Mapping[str, object]],
        *,
        top_terms: int = 5,
    ) -> Mapping[str, List[dict]]:
        """Compute topic drift between two time windows."""
        prev_map = {
            topic["topic"]: Reporter._topic_terms(topic.get("representation", []), top_terms)
            for topic in previous_topics
            if "topic" in topic
        }
        curr_map = {
            topic["topic"]: Reporter._topic_terms(topic.get("representation", []), top_terms)
            for topic in current_topics
            if "topic" in topic
        }

        prev_counts = {topic["topic"]: int(topic.get("count", 0)) for topic in previous_topics if "topic" in topic}
        curr_counts = {topic["topic"]: int(topic.get("count", 0)) for topic in current_topics if "topic" in topic}

        previous_ids = set(prev_map)
        current_ids = set(curr_map)

        new_topics = current_ids - previous_ids
        retired_topics = previous_ids - current_ids
        shared_topics = current_ids & previous_ids

        drift: List[dict] = []
        for topic_id in sorted(shared_topics):
            prev_terms = prev_map[topic_id]
            curr_terms = curr_map[topic_id]
            overlap = len(prev_terms & curr_terms) / max(len(curr_terms), 1)
            drift.append(
                {
                    "topic": topic_id,
                    "overlap": round(overlap, 3),
                    "new_terms": sorted(curr_terms - prev_terms)[:top_terms],
                    "dropped_terms": sorted(prev_terms - curr_terms)[:top_terms],
                    "current_count": curr_counts.get(topic_id, 0),
                    "previous_count": prev_counts.get(topic_id, 0),
                }
            )

        new_topic_entries = []
        for topic_id in sorted(new_topics):
            terms = sorted(curr_map[topic_id])[:top_terms]
            new_topic_entries.append(
                {
                    "topic": topic_id,
                    "terms": terms,
                    "count": curr_counts.get(topic_id, 0),
                }
            )

        retired_topic_entries = []
        for topic_id in sorted(retired_topics):
            terms = sorted(prev_map[topic_id])[:top_terms]
            retired_topic_entries.append(
                {
                    "topic": topic_id,
                    "terms": terms,
                    "count": prev_counts.get(topic_id, 0),
                }
            )

        return {
            "updated_topics": drift,
            "new_topics": new_topic_entries,
            "retired_topics": retired_topic_entries,
        }

    @staticmethod
    def _topic_terms(
        representation: Iterable[object],
        top_terms: int,
    ) -> set[str]:
        terms: List[str] = []
        for item in representation:
            if isinstance(item, (list, tuple)) and item:
                terms.append(str(item[0]))
            else:
                terms.append(str(item))
            if len(terms) >= top_terms:
                break
        return set(terms)


__all__ = ["Reporter"]
