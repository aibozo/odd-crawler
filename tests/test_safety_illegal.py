from __future__ import annotations

import unittest

import tests._path  # noqa: F401

from oddcrawler.safety import IllegalContentDetector


class IllegalContentDetectorTests(unittest.TestCase):
    def test_detects_keywords(self) -> None:
        detector = IllegalContentDetector(
            {
                "illegal_content": {
                    "keywords": ["illegal firearms marketplace", "csam"],
                    "min_keyword_matches": 1,
                }
            }
        )
        result = detector.scan("This forum hosts an illegal firearms marketplace with listings.")
        self.assertTrue(result.illegal)
        self.assertIn("illegal firearms marketplace", result.reason)

    def test_no_keywords_no_flag(self) -> None:
        detector = IllegalContentDetector({})
        result = detector.scan("Retro websites are fun")
        self.assertFalse(result.illegal)


if __name__ == "__main__":
    unittest.main()

