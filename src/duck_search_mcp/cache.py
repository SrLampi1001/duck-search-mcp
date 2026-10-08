"""On-disk TTL cache for DDG responses.

Per SPECS §7: a missing, stale, corrupt, or unwritable cache entry must NEVER
fail the call. The tool logs a warning and degrades to a plain uncached call.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from .normalize import cache_path_for

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CachedResponse:
    query: str
    results: list[dict]


class DiskCache:
    """Filesystem TTL cache. `ttl_seconds <= 0` disables the cache entirely."""

    def __init__(self, base_dir: Path, ttl_seconds: int):
        self._dir = Path(base_dir)
        self._ttl = max(0, int(ttl_seconds))

    @property
    def enabled(self) -> bool:
        return self._ttl > 0

    def get(self, query: str) -> CachedResponse | None:
        if not self.enabled:
            return None
        path = self._path_for(query)
        try:
            if not path.exists():
                return None
            envelope = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = float(envelope.get("fetched_at_unix", 0))
            if (time.time() - fetched_at) > self._ttl:
                return None
            results = envelope.get("results")
            if not isinstance(results, list):
                log.warning("cache: %s has malformed results; ignoring", path)
                return None
            return CachedResponse(
                query=str(envelope.get("query", query.strip())),
                results=[r for r in results if isinstance(r, dict)],
            )
        except (OSError, ValueError, json.JSONDecodeError) as e:
            log.warning("cache: read failed for %r (%s); falling through", query, e)
            return None

    def set(self, query: str, results: list[dict]) -> None:
        if not self.enabled:
            return
        path = self._path_for(query)
        envelope = {
            "fetched_at_unix": time.time(),
            "query": query.strip(),
            "results": results,
        }
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except OSError as e:
            log.warning("cache: write failed for %r (%s); continuing without cache", query, e)

    def invalidate(self, query: str) -> None:
        if not self.enabled:
            return
        try:
            self._path_for(query).unlink(missing_ok=True)
        except OSError as e:
            log.warning("cache: invalidate failed for %r (%s)", query, e)

    def _path_for(self, query: str) -> Path:
        return cache_path_for(query, self._dir)
