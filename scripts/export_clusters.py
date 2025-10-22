#!/usr/bin/env python3
"""Export UMAP layout with HDBSCAN clusters for stored embeddings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict

import numpy as np

from oddcrawler.storage import FaissVectorStore, QdrantConfig, QdrantVectorStore
from oddcrawler.scoring import cluster_hdbscan, export_cluster_csv, reduce_umap


def load_metadata(path: Path | None) -> Dict[int, Dict[str, object]]:
    if not path:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if isinstance(raw, dict):
        return {int(k): v for k, v in raw.items() if isinstance(v, dict)}
    if isinstance(raw, list):
        result: Dict[int, Dict[str, object]] = {}
        for entry in raw:
            if isinstance(entry, dict) and "id" in entry:
                result[int(entry["id"])] = entry
        return result
    raise ValueError("Unsupported metadata format; expected dict or list of dicts")


def load_embeddings(artifact_dir: Path) -> tuple[list[int], np.ndarray]:
    meta_path = artifact_dir / "embedding_meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"Embedding metadata not found at {meta_path}")

    with meta_path.open("r", encoding="utf-8") as handle:
        metadata = json.load(handle)

    backend = metadata.get("backend", "qdrant")
    if backend == "qdrant":
        store = QdrantVectorStore(
            dim=None,
            config=QdrantConfig(
                collection_name=metadata.get("collection", "embeddings"),
                path=metadata.get("path"),
            ),
        )
        ids, vectors = store.get_all()
    elif backend == "faiss":
        store = FaissVectorStore.load(artifact_dir / "vectors.index")
        ids, vectors = store.get_all()
    else:
        raise ValueError(f"Unsupported backend '{backend}' in embedding metadata")

    return list(ids), np.asarray(vectors, dtype="float32")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export UMAP + HDBSCAN clustering for embeddings")
    parser.add_argument("artifact_dir", type=Path, help="Directory passed to EmbeddingIndexer.save")
    parser.add_argument("output", type=Path, help="Destination CSV file")
    parser.add_argument("--metadata", type=Path, help="Optional JSON file mapping id -> metadata")
    parser.add_argument("--components", type=int, default=2, help="Number of UMAP components (default: 2)")
    parser.add_argument("--min-cluster-size", type=int, default=5, help="HDBSCAN min_cluster_size (default: 5)")
    args = parser.parse_args()

    artifact_dir = args.artifact_dir
    ids, vectors = load_embeddings(artifact_dir)
    if len(ids) == 0:
        print("No vectors available; nothing to export.")
        return

    layout = reduce_umap(vectors, n_components=args.components)
    labels = cluster_hdbscan(vectors, min_cluster_size=args.min_cluster_size)
    metadata = load_metadata(args.metadata) if args.metadata else {}
    export_cluster_csv(args.output, ids, layout, labels, metadata=metadata)
    print(f"Exported {len(ids)} points to {args.output}")


if __name__ == "__main__":
    main()
