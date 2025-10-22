"""URL canonicalization helpers."""

from __future__ import annotations

import posixpath
from typing import Iterable, Tuple
from urllib.parse import parse_qsl, urlsplit, urlunsplit

DEFAULT_ALLOWED_SCHEMES: Tuple[str, ...] = ("http", "https")


def canonicalize_url(url: str, *, allowed_schemes: Iterable[str] = DEFAULT_ALLOWED_SCHEMES) -> str:
    """Return a normalized URL following RFC3986-ish rules."""
    if not url:
        raise ValueError("URL must be non-empty")

    split = urlsplit(url.strip())
    if not split.scheme:
        raise ValueError("URL must include a scheme")

    scheme = split.scheme.lower()
    allowed = tuple(s.lower() for s in allowed_schemes)
    if allowed and scheme not in allowed:
        raise ValueError(f"Scheme '{scheme}' not allowed")

    if not split.netloc:
        raise ValueError("URL must include a network location")

    netloc = _normalize_netloc(split.netloc, scheme)
    path = _normalize_path(split.path)

    query = _normalize_query(split.query)

    return urlunsplit((scheme, netloc, path, query, ""))


def _normalize_netloc(netloc: str, scheme: str) -> str:
    userinfo = ""
    host_port = netloc
    if "@" in netloc:
        userinfo, host_port = netloc.rsplit("@", 1)

    if ":" in host_port:
        host, port = host_port.split(":", 1)
    else:
        host, port = host_port, ""

    host = host.lower().strip(".")
    port = port.strip()

    if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
        port = ""

    host_port = host if not port else f"{host}:{port}"
    if userinfo:
        return f"{userinfo}@{host_port}"
    return host_port


def _normalize_path(path: str) -> str:
    # If path is empty, default to "/"
    if not path:
        return "/"

    has_trailing_slash = path.endswith("/")

    normalized = posixpath.normpath(path)
    if not normalized.startswith("/"):
        normalized = "/" + normalized

    if has_trailing_slash and not normalized.endswith("/"):
        normalized = normalized + "/"

    if normalized == "//":
        normalized = "/"

    return normalized


def _normalize_query(query: str) -> str:
    if not query:
        return ""

    pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=False)
    pairs.sort()

    # Re-encode pairs preserving ordering
    from urllib.parse import urlencode

    return urlencode(pairs, doseq=True)


__all__ = ["canonicalize_url"]
