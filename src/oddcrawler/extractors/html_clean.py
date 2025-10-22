"""Basic HTML extraction and feature generation."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from oddcrawler.llm import GeminiClient, GeminiConfigurationError
from oddcrawler.utils.canonical import DEFAULT_ALLOWED_SCHEMES, canonicalize_url


class HTMLExtractor:
    """Simplified extractor that produces observation records."""

    def __init__(
        self,
        *,
        max_excerpt_chars: int = 500,
        flash_client: Optional[GeminiClient] = None,
    ) -> None:
        self.max_excerpt_chars = max_excerpt_chars
        self.flash_client = flash_client

    def extract(self, fetch_result: Any) -> Dict[str, Any]:
        soup = BeautifulSoup(fetch_result.body, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        excerpt = text[: self.max_excerpt_chars]

        outbound_links, link_signals = self._extract_links(fetch_result, soup)
        features = self._build_features(fetch_result, soup, text, outbound_links, link_signals)
        fetched_at = fetch_result.fetched_at
        hashes = {
            "url_sha256": fetch_result.url_hash,
            "content_sha256": hashlib.sha256(fetch_result.body).hexdigest(),
        }

        observation = {
            "url": fetch_result.url,
            "url_canonical": fetch_result.url,
            "fetched_at": fetched_at,
            "status": getattr(fetch_result, "status", 200),
            "headers": dict(fetch_result.headers),
            "hashes": hashes,
            "extract": {
                "lang": "unknown",
                "title": soup.title.string.strip() if soup.title and soup.title.string else "",
                "text_excerpt": excerpt,
                "token_count": len(text.split()),
            },
            "features": features,
            "storage_policy": "excerpt-only",
            "links": {"outbound": outbound_links},
        }

        if self.flash_client:
            try:
                prompt = self._build_flash_prompt(fetch_result.url, excerpt)
                flash_summary = self.flash_client.generate_text(prompt)
            except GeminiConfigurationError:
                flash_summary = None
            except Exception:  # pragma: no cover - LLM runtime errors
                flash_summary = None
            if flash_summary:
                observation["llm_flash_summary"] = flash_summary.strip()[:500]

        return observation

    def _build_flash_prompt(self, url: str, excerpt: str) -> str:
        excerpt_text = excerpt or "[no text extracted]"
        return (
            "Provide a concise 1-2 sentence neutral summary of the following web page excerpt. "
            "Avoid PII, keep it factual, and mention any notable odd or retro elements if present.\n"
            f"URL: {url}\n"
            f"Excerpt: {excerpt_text}"
        )

    def _build_features(
        self,
        fetch_result: Any,
        soup: BeautifulSoup,
        text: str,
        outbound_links: List[Mapping[str, Any]],
        link_signals: Mapping[str, Any],
    ) -> Dict[str, Any]:
        retro_tags = ["marquee", "blink", "font", "center", "frameset"]
        retro_count = 0
        signals: list[str] = []
        for tag in retro_tags:
            found = soup.find_all(tag)
            if found:
                retro_count += len(found)
                signals.append(tag)
        retro_score = min(retro_count / 3.0, 1.0)

        url_flags: list[str] = []
        lower_url = fetch_result.url.lower()
        if "cgi-bin" in lower_url:
            url_flags.append("cgi-bin")
        if "/~" in fetch_result.url:
            url_flags.append("tilde_home")
        if lower_url.startswith("http://"):
            url_flags.append("insecure")
        url_score = 1.0 if url_flags else 0.0

        token_count = len(text.split())
        semantic_score = min(token_count / 800.0, 1.0)

        outbound_domains = {urlsplit(link["url"]).netloc for link in outbound_links if "url" in link}
        webring_hits = int(link_signals.get("webring_hits") or 0)

        features = {
            "html_retro": {"signals": signals, "count": retro_count, "score": retro_score},
            "url_weird": {"flags": url_flags, "score": url_score},
            "semantic": {"score": semantic_score, "nn_dist": None},
            "anomaly": {"score": 0.0},
            "graph": {
                "score": 0.0,
                "outbound_count": len(outbound_links),
                "outbound_domains": len(outbound_domains),
                "webring_hits": webring_hits,
                "has_webring": bool(webring_hits),
            },
        }
        return features

    def _extract_links(self, fetch_result: Any, soup: BeautifulSoup) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        base_url = fetch_result.url
        base_tag = soup.find("base", href=True)
        if base_tag and base_tag.get("href"):
            base_url = urljoin(base_url, base_tag["href"])

        outbound: List[Dict[str, Any]] = []
        seen: set[str] = set()
        webring_hits = 0

        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "").strip()
            if not href or href.startswith("#"):
                continue

            absolute = urljoin(base_url, href)
            try:
                canonical = canonicalize_url(absolute, allowed_schemes=DEFAULT_ALLOWED_SCHEMES)
            except ValueError:
                continue
            if canonical in seen:
                continue
            seen.add(canonical)

            anchor_text = anchor.get_text(separator=" ", strip=True)[:160]
            rel = anchor.get("rel") or []
            if isinstance(rel, str):
                rel_tokens = [rel]
            else:
                rel_tokens = [token for token in rel if isinstance(token, str)]

            lower_text = anchor_text.lower()
            if "webring" in lower_text or "webring" in canonical.lower():
                webring_hits += 1

            outbound.append(
                {
                    "url": canonical,
                    "anchor_text": anchor_text,
                    "rel": rel_tokens,
                    "found_at": fetch_result.fetched_at,
                }
            )

        return outbound, {"webring_hits": webring_hits}


__all__ = ["HTMLExtractor"]
