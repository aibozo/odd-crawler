#!/usr/bin/env python3
"""Generate BERTopic summaries for a corpus of documents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from oddcrawler.scoring import TopicConfig, TopicSummarizer


def load_documents(path: Path) -> list[str]:
    if path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list):
            return [str(item) for item in data]
        if isinstance(data, dict) and "documents" in data:
            docs = data["documents"]
            if isinstance(docs, list):
                return [str(item) for item in docs]
        raise ValueError("Unsupported JSON format; expected list or {\"documents\": [...]}")
    return path.read_text(encoding="utf-8").splitlines()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate topic summaries using BERTopic")
    parser.add_argument("input", type=Path, help="Path to input file (JSON list or newline-delimited text)")
    parser.add_argument("output", type=Path, help="Path to write summaries JSON")
    parser.add_argument("--model", default="sentence-transformers/all-MiniLM-L12-v2", help="SentenceTransformer model name")
    parser.add_argument("--n-neighbors", type=int, default=15)
    parser.add_argument("--min-cluster-size", type=int, default=5)
    args = parser.parse_args()

    docs = load_documents(args.input)
    if not docs:
        raise SystemExit("No documents provided")

    summarizer = TopicSummarizer(
        TopicConfig(
            model_name=args.model,
            n_neighbors=args.n_neighbors,
            min_cluster_size=args.min_cluster_size,
        )
    )
    summaries = summarizer.summarize(docs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(summaries, handle, indent=2)
    print(f"Wrote {len(summaries)} topic summaries to {args.output}")


if __name__ == "__main__":
    main()
