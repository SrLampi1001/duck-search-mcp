"""Integration tests: real DDG calls, gated on opt-in.

Per SPECS §14. Network tests are opt-in via `--network` or the
DUCK_SEARCH_NETWORK_TESTS env var. Skipped by default.
"""
from __future__ import annotations

import os

import pytest
from fastmcp import Client

from duck_search_mcp.server import mcp

NETWORK_ENABLED = os.environ.get("DUCK_SEARCH_NETWORK_TESTS") == "1"
pytestmark = pytest.mark.skipif(
    not NETWORK_ENABLED,
    reason="network tests disabled (set DUCK_SEARCH_NETWORK_TESTS=1 to run)",
)


async def test_canonical_entity_returns_at_least_one_result():
    async with Client(mcp) as c:
        r = await c.call_tool("web_search", {"query": "HTTP 418", "count": 3})
        sc = r.structured_content
        assert sc["source"] in {"upstream", "cache"}
        assert len(sc["results"]) >= 1


async def test_known_empty_long_tail_returns_note():
    async with Client(mcp) as c:
        r = await c.call_tool(
            "web_search",
            {"query": "how do I write async code in Rust as a beginner with tokio 2026", "count": 3},
        )
        sc = r.structured_content
        assert sc["results"] == []
        assert sc["note"]
