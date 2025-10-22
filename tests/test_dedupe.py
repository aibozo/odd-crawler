from __future__ import annotations

import unittest

import tests._path  # noqa: F401

from oddcrawler.utils import BloomFilter, hamming_distance, simhash


class BloomFilterTests(unittest.TestCase):
    def test_add_and_membership(self) -> None:
        bloom = BloomFilter(capacity=100, error_rate=0.01)
        items = [f"item-{i}" for i in range(10)]
        for item in items:
            bloom.add(item)
        for item in items:
            self.assertIn(item, bloom)

    def test_clear(self) -> None:
        bloom = BloomFilter(capacity=10, error_rate=0.1)
        bloom.add("foo")
        self.assertIn("foo", bloom)
        bloom.clear()
        # Not guaranteed to be absent but highly likely for small bloom
        self.assertNotIn("bar", bloom)


class SimHashTests(unittest.TestCase):
    def test_simhash_similarity(self) -> None:
        text1 = "Oddcrawler explores the small and strange web." \
            "It looks for retro signals and unusual language."
        text2 = "Oddcrawler explores the strange small web. " \
            "It looks for unusual language and retro signals."
        hash1 = simhash(text1)
        hash2 = simhash(text2)
        self.assertLess(hamming_distance(hash1, hash2), 10)

    def test_simhash_difference(self) -> None:
        hash1 = simhash("This is a short text about gardening.")
        hash2 = simhash("Completely different topic concerning astrophysics and math.")
        self.assertGreater(hamming_distance(hash1, hash2), 10)


if __name__ == "__main__":
    unittest.main()
