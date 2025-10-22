"""Dedupe helpers (Bloom filter + SimHash)."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Iterable, Sequence


def _hash_bytes(data: bytes, seed: int = 0) -> int:
    return int.from_bytes(hashlib.sha256(seed.to_bytes(4, "big") + data).digest(), "big")


@dataclass
class BloomFilterConfig:
    capacity: int
    error_rate: float = 0.01


class BloomFilter:
    """Simple Bloom filter implementation using a bytearray bitset."""

    def __init__(self, capacity: int, error_rate: float = 0.01) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if not (0 < error_rate < 1):
            raise ValueError("error_rate must be between 0 and 1")

        self.capacity = capacity
        self.error_rate = error_rate
        self.size = self._optimal_size(capacity, error_rate)
        self.num_hashes = self._optimal_hash_count(self.size, capacity)

        self._bits = bytearray((self.size + 7) // 8)

    @staticmethod
    def _optimal_size(n: int, p: float) -> int:
        """Return number of bits required for capacity n with error rate p."""
        return int(math.ceil(-n * math.log(p) / (math.log(2) ** 2)))

    @staticmethod
    def _optimal_hash_count(size: int, capacity: int) -> int:
        return int(math.ceil((size / capacity) * math.log(2)))

    def _indices(self, item: bytes) -> Iterable[int]:
        h1 = _hash_bytes(item, seed=0)
        h2 = _hash_bytes(item, seed=1)
        for i in range(self.num_hashes):
            yield (h1 + i * h2) % self.size

    def add(self, item: str | bytes) -> None:
        data = item.encode("utf-8") if isinstance(item, str) else item
        for idx in self._indices(data):
            byte_index, bit_index = divmod(idx, 8)
            self._bits[byte_index] |= 1 << bit_index

    def __contains__(self, item: str | bytes) -> bool:
        data = item.encode("utf-8") if isinstance(item, str) else item
        for idx in self._indices(data):
            byte_index, bit_index = divmod(idx, 8)
            if not (self._bits[byte_index] & (1 << bit_index)):
                return False
        return True

    def clear(self) -> None:
        for i in range(len(self._bits)):
            self._bits[i] = 0


def tokenize(text: str) -> Sequence[str]:
    return re.findall(r"\w+", text.lower())


def simhash(text: str, *, hash_bits: int = 64) -> int:
    if hash_bits not in (32, 64, 128):
        raise ValueError("hash_bits must be one of 32, 64, or 128")

    tokens = tokenize(text)
    if not tokens:
        return 0

    weights = [0] * hash_bits
    for token in tokens:
        token_hash = _hash_bytes(token.encode("utf-8")) & ((1 << hash_bits) - 1)
        for bit in range(hash_bits):
            weight = 1
            if token_hash & (1 << bit):
                weights[bit] += weight
            else:
                weights[bit] -= weight

    fingerprint = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            fingerprint |= 1 << bit
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


__all__ = ["BloomFilter", "simhash", "hamming_distance"]
