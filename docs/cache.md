# Dedupe, Canonicalization, and Revisits

## URL canonicalization
- Normalize scheme/host case, remove default ports, resolve `.`/`..`, sort query keys.
- Respect `<link rel="canonical">` if present (and allowed).

## Seen-URL dedupe
- Maintain a **Bloom filter** (capacity and FP rate in config) to skip previously seen URLs quickly.
- Persist a set of canonical URL hashes for crash recovery.

## Near-duplicate content
- **SimHash** on cleaned text; Hamming distance threshold (e.g., 5) drops near-duplicates.
- Optional **MinHash/LSH** for robustness on longer pages.

## Revisits
- Honor **ETag/If-None-Match** and **Last-Modified/If-Modified-Since**.
- Use a per-host **TTL** with bonus priority if headers indicate a change.
