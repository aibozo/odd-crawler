from __future__ import annotations

import unittest

import tests._path  # noqa: F401

from oddcrawler.utils import canonicalize_url


class CanonicalizeUrlTests(unittest.TestCase):
    def test_basic_normalization(self) -> None:
        url = "HTTP://Example.COM:80/a/../b?z=3&y=2"
        expected = "http://example.com/b?y=2&z=3"
        self.assertEqual(canonicalize_url(url), expected)

    def test_https_default_port_removed(self) -> None:
        url = "https://example.com:443/path"
        self.assertEqual(canonicalize_url(url), "https://example.com/path")

    def test_non_default_port_preserved(self) -> None:
        url = "https://example.com:4443/path"
        self.assertEqual(canonicalize_url(url), "https://example.com:4443/path")

    def test_query_sort_with_duplicates(self) -> None:
        url = "https://example.com/path?b=2&a=1&b=1"
        self.assertEqual(canonicalize_url(url), "https://example.com/path?a=1&b=1&b=2")

    def test_path_trailing_slash_retained(self) -> None:
        url = "https://example.com/foo/./"
        self.assertEqual(canonicalize_url(url), "https://example.com/foo/")

    def test_requires_scheme(self) -> None:
        with self.assertRaises(ValueError):
            canonicalize_url("example.com/path")

    def test_reject_disallowed_scheme(self) -> None:
        with self.assertRaises(ValueError):
            canonicalize_url("ftp://example.com/resource")


if __name__ == "__main__":
    unittest.main()
