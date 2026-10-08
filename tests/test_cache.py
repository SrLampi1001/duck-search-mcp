"""Tests for the on-disk TTL cache. Per SPECS §7, cache failures must never break the call."""
import json
import time
from pathlib import Path

import pytest

from duck_search_mcp.cache import CachedResponse, DiskCache


def _make_cache(tmp_path: Path, ttl: int = 86400) -> DiskCache:
    return DiskCache(tmp_path, ttl)


def test_disabled_cache_returns_none(tmp_path):
    cache = _make_cache(tmp_path, ttl=0)
    assert cache.enabled is False
    assert cache.get("anything") is None
    cache.set("anything", [{"title": "t", "url": "u", "snippet": "s"}])
    assert cache.get("anything") is None
    assert list(tmp_path.iterdir()) == []  # nothing written


def test_round_trip_serves_from_disk(tmp_path):
    cache = _make_cache(tmp_path)
    payload = [{"title": "Rust", "url": "https://example.com", "snippet": "Systems language."}]
    cache.set("Rust programming language", payload)

    got = cache.get("Rust programming language")
    assert got is not None
    assert got.query == "Rust programming language"
    assert got.results == payload
    assert (tmp_path / "rust-programming-language-").exists() or any(
        p.name.startswith("rust-programming-language-") for p in tmp_path.iterdir()
    )


def test_normalised_query_hits_same_entry(tmp_path):
    cache = _make_cache(tmp_path)
    cache.set("  Rust   Programming  Language  ", [{"title": "x", "url": "u", "snippet": "s"}])
    assert cache.get("rust programming language") is not None
    assert cache.get("RUST PROGRAMMING LANGUAGE") is not None


def test_stale_entry_returns_none(tmp_path):
    cache = DiskCache(tmp_path, ttl_seconds=1)
    cache.set("q", [{"title": "t", "url": "u", "snippet": "s"}])
    time.sleep(1.2)
    assert cache.get("q") is None


def test_corrupt_file_falls_through_without_raising(tmp_path, caplog):
    cache = _make_cache(tmp_path)
    # Manually create a corrupt cache file at the expected path.
    cache.set("q", [{"title": "ok", "url": "u", "snippet": "s"}])
    paths = list(tmp_path.iterdir())
    assert len(paths) == 1
    paths[0].write_text("{not valid json")
    with caplog.at_level("WARNING"):
        assert cache.get("q") is None
    assert any("cache: read failed" in r.message for r in caplog.records)


def test_writes_are_atomic_via_tmp_rename(tmp_path):
    cache = _make_cache(tmp_path)
    cache.set("q", [{"title": "t", "url": "u", "snippet": "s"}])
    # Only the final file should exist, not any .tmp leftover.
    tmps = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert tmps == []


def test_unwritable_dir_does_not_raise(tmp_path, monkeypatch, caplog):
    # Force mkdir to fail by making the target path have a file as a parent.
    blocker = tmp_path / "blocker"
    blocker.write_text("I am a file, not a directory.")
    blocked = blocker / "deep" / "deeper"
    cache = DiskCache(blocked, ttl_seconds=60)
    with caplog.at_level("WARNING"):
        cache.set("q", [{"title": "t", "url": "u", "snippet": "s"}])
    # No exception raised; the warning was logged.
    assert any("cache: write failed" in r.message for r in caplog.records)


def test_unreadable_file_does_not_raise(tmp_path, caplog):
    cache = _make_cache(tmp_path)
    cache.set("q", [{"title": "t", "url": "u", "snippet": "s"}])
    # Corrupt the file in place.
    for p in tmp_path.iterdir():
        p.write_text("not json")
    with caplog.at_level("WARNING"):
        assert cache.get("q") is None
    assert any("cache: read failed" in r.message for r in caplog.records)


def test_invalidate_removes_entry(tmp_path):
    cache = _make_cache(tmp_path)
    cache.set("q", [{"title": "t", "url": "u", "snippet": "s"}])
    assert cache.get("q") is not None
    cache.invalidate("q")
    assert cache.get("q") is None
