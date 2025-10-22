from __future__ import annotations

import unittest

import tests._path  # noqa: F401

from oddcrawler.scoring import TopicConfig, TopicSummarizer


class DummyEmbeddingModel:
    def encode(self, texts, convert_to_numpy=True, normalize_embeddings=False):
        import numpy as np

        embeddings = []
        for idx, text in enumerate(texts):
            vec = np.zeros(10, dtype="float32")
            vec[idx % 10] = 1.0
            embeddings.append(vec)
        return np.vstack(embeddings)


class TopicSummarizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.docs = [
            "Oddcrawler explores the small web.",
            "Retro HTML signals include marquee and blink tags.",
            "We detect webrings and webring widgets.",
            "Another document about odd communities and retro forums.",
            "Small and strange communities gather on retro sites.",
        ]

    def test_summarize_topics(self) -> None:
        summarizer = TopicSummarizer(
            TopicConfig(n_neighbors=2, n_components=2, min_cluster_size=2, min_samples=1),
            model=DummyEmbeddingModel(),
        )
        summaries = summarizer.summarize(self.docs, top_n=3)
        self.assertTrue(summaries)
        for summary in summaries:
            self.assertIn("topic", summary)
            self.assertIn("representation", summary)
            self.assertLessEqual(len(summary["representation"]), 3)


if __name__ == "__main__":
    unittest.main()
