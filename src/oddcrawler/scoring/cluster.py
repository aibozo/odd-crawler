"""Clustering and visualization helpers using UMAP and HDBSCAN."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import hdbscan
import numpy as np
import umap


def reduce_umap(vectors: np.ndarray, *, n_components: int = 2, random_state: int = 42, **kwargs) -> np.ndarray:
    reducer = umap.UMAP(n_components=n_components, random_state=random_state, **kwargs)
    return reducer.fit_transform(vectors)


def cluster_hdbscan(
    vectors: np.ndarray,
    *,
    min_cluster_size: int = 5,
    min_samples: int | None = None,
    metric: str = "euclidean",
    **kwargs,
) -> np.ndarray:
    clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size, min_samples=min_samples, metric=metric, **kwargs)
    return clusterer.fit_predict(vectors)


def export_cluster_csv(
    output_path: Path | str,
    ids: Sequence[int],
    layout: np.ndarray,
    labels: Sequence[int],
    metadata: Mapping[int, Mapping[str, object]] | None = None,
) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["id", "x", "y", "cluster"]
    extra_keys: list[str] = []
    if metadata:
        extra_keys = sorted({key for entry in metadata.values() for key in entry.keys()})
        fieldnames.extend(extra_keys)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for idx, (vector_id, point, label) in enumerate(zip(ids, layout, labels)):
            row = {
                "id": vector_id,
                "x": float(point[0]),
                "y": float(point[1]),
                "cluster": int(label),
            }
            if metadata and vector_id in metadata:
                for key in extra_keys:
                    row[key] = metadata[vector_id].get(key)
            writer.writerow(row)


__all__ = ["reduce_umap", "cluster_hdbscan", "export_cluster_csv"]
