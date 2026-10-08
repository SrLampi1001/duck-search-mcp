"""Query normalization, slug, and FNV-1a 64-bit hash for cache keying.

Per SPECS §7: cache key = trimmed, inner-whitespace-collapsed, lowercased query.
File name = `<slug>-<fnv1a64>.json`. The slug keeps the directory human-browsable;
the FNV-1a 64-bit hash disambiguates queries that slugify identically
("c++" vs "c#", "go" vs "Go!", etc.).
"""
from __future__ import annotations

import re
from pathlib import Path

_INNER_WS = re.compile(r"\s+")
_NON_SLUG = re.compile(r"[^a-z0-9]+")
_FNV_OFFSET = 0xCBF29CE484222325
_FNV_PRIME = 0x100000001B3
_FNV_MASK = 0xFFFFFFFFFFFFFFFF


def normalize_query(q: str) -> str:
    if not isinstance(q, str):
        q = str(q)
    return _INNER_WS.sub(" ", q).strip().lower()


def slugify(normalized: str, max_len: int = 80) -> str:
    slug = _NON_SLUG.sub("-", normalized).strip("-")
    if not slug:
        slug = "empty"
    return slug[:max_len]


def fnv1a64(s: str) -> int:
    h = _FNV_OFFSET
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * _FNV_PRIME) & _FNV_MASK
    return h


def cache_path_for(query: str, base_dir: Path) -> Path:
    norm = normalize_query(query)
    return base_dir / f"{slugify(norm)}-{fnv1a64(norm):016x}.json"
