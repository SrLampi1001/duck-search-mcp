"""In-process tests for the FastMCP server.

These run against the in-memory FastMCP instance via `fastmcp.Client`. The
outbound DDG call is mocked at the `fetch_ddg` boundary (via monkeypatch)
so the tests are hermetic. The real network is exercised separately in
`test_server_integration.py` (skipped unless `DUCK_SEARCH_NETWORK_TESTS=1`).
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastmcp import Client

from duck_search_mcp import server as server_module
from duck_search_mcp.ddg import EMPTY_NOTE
from duck_search_mcp.server import mcp


class FakeDDG:
    """Pluggable canned responses keyed by query. Inject as the `fetch_ddg` callable."""

    def __init__(self) -> None:
        self.responses: dict[str, dict] = {}
        self.exceptions: dict[str, BaseException] = {}
        self.statuses: dict[str, int] = {}
        self.calls: list[str] = []

    def set(self, query: str, payload: dict) -> None:
        self.responses[query] = payload

    def set_error(self, query: str, exc: BaseException) -> None:
        self.exceptions[query] = exc

    def set_status(self, query: str, status: int) -> None:
        self.statuses[query] = status

    async def __call__(self, query: str, *, client: httpx.AsyncClient, timeout_s: float) -> dict:
        self.calls.append(query)
        if query in self.statuses:
            # Build a fake response and raise.
            request = httpx.Request("GET", "https://api.duckduckgo.com/")
            response = httpx.Response(self.statuses[query], request=request)
            raise httpx.HTTPStatusError("upstream", request=request, response=response)
        if query in self.exceptions:
            raise self.exceptions[query]
        return self.responses.get(query, {"AbstractText": "", "RelatedTopics": []})


@pytest.fixture
def fake_ddg(monkeypatch, tmp_cache_dir):
    """Replace `server.fetch_ddg` with a controllable fake; ensure clean cache."""
    monkeypatch.setattr(server_module, "fetch_ddg", FakeDDG.__call__.__get__(FakeDDG()))
    # Re-grab the fake instance from the patched function's bound self.
    fake = server_module.fetch_ddg.__self__  # type: ignore[attr-defined]
    return fake


# --- tests -----------------------------------------------------------------

async def test_tools_list_advertises_only_web_search(fake_ddg):
    async with Client(mcp) as c:
        tools = await c.list_tools()
        names = [t.name for t in tools]
        assert names == ["web_search"]
        tool = tools[0]
        assert "query" in tool.input_schema["properties"]
        assert "count" in tool.input_schema["properties"]
        assert tool.input_schema["required"] == ["query"]


async def test_prompts_list_advertises_research_entity(fake_ddg):
    async with Client(mcp) as c:
        prompts = await c.list_prompts()
        names = [p.name for p in prompts]
        assert names == ["research_entity"]


async def test_research_entity_prompt_returns_user_message(fake_ddg):
    async with Client(mcp) as c:
        p = await c.get_prompt("research_entity", {"topic": "PostgreSQL"})
        assert p.messages
        text = p.messages[0].content.text
        assert "PostgreSQL" in text
        assert "canonical topic name" in text


async def test_basic_search_returns_structured_results(fake_ddg):
    fake_ddg.set(
        "Rust programming language",
        {
            "AbstractText": "Rust is a systems programming language focused on safety.",
            "AbstractURL": "https://en.wikipedia.org/wiki/Rust_(programming_language)",
            "Heading": "Rust (programming language)",
            "RelatedTopics": [],
        },
    )
    async with Client(mcp) as c:
        result = await c.call_tool("web_search", {"query": "Rust programming language"})
        sc = result.structured_content
        assert sc["query"] == "Rust programming language"
        assert sc["source"] == "upstream"
        assert sc["note"] == ""
        assert len(sc["results"]) == 1
        assert sc["results"][0]["title"] == "Rust (programming language)"
        assert sc["results"][0]["url"].startswith("https://en.wikipedia.org")


async def test_query_is_trimmed_and_echoed(fake_ddg):
    fake_ddg.set(
        "hello",
        {"AbstractText": "Greeting.", "AbstractURL": "https://example.com/h", "Heading": "Hello"},
    )
    async with Client(mcp) as c:
        result = await c.call_tool("web_search", {"query": "  hello  "})
        assert result.structured_content["query"] == "hello"
        assert fake_ddg.calls == ["hello"]


async def test_count_is_clamped_to_1_through_10(fake_ddg):
    fake_ddg.set(
        "anything",
        {
            "AbstractText": "",
            "RelatedTopics": [
                {"Text": f"Topic {i} - desc {i}", "FirstURL": f"https://example.com/{i}"}
                for i in range(12)
            ],
        },
    )
    async with Client(mcp) as c:
        r1 = await c.call_tool("web_search", {"query": "anything", "count": 0})
        assert len(r1.structured_content["results"]) == 1
        r2 = await c.call_tool("web_search", {"query": "anything", "count": 11})
        assert len(r2.structured_content["results"]) == 10
        r3 = await c.call_tool("web_search", {"query": "anything"})
        assert len(r3.structured_content["results"]) == 5


async def test_empty_ddg_response_returns_empty_with_note(fake_ddg):
    fake_ddg.set("how do I write async code in Rust as a beginner", {})
    async with Client(mcp) as c:
        result = await c.call_tool(
            "web_search",
            {"query": "how do I write async code in Rust as a beginner"},
        )
        sc = result.structured_content
        assert sc["results"] == []
        assert sc["note"] == EMPTY_NOTE


async def test_second_call_within_ttl_serves_from_cache(fake_ddg, tmp_cache_dir, monkeypatch):
    monkeypatch.setenv("DDG_CACHE_TTL_SECS", "3600")
    fake_ddg.set(
        "cached query",
        {
            "AbstractText": "Cached.",
            "AbstractURL": "https://example.com/c",
            "Heading": "Cached",
            "RelatedTopics": [],
        },
    )
    async with Client(mcp) as c:
        r1 = await c.call_tool("web_search", {"query": "cached query"})
        r2 = await c.call_tool("web_search", {"query": "cached query"})
        assert r1.structured_content["source"] == "upstream"
        assert r2.structured_content["source"] == "cache"
        # Only one outbound call was made.
        assert fake_ddg.calls == ["cached query"]


async def test_empty_result_is_cached_and_keeps_note(fake_ddg, tmp_cache_dir, monkeypatch):
    monkeypatch.setenv("DDG_CACHE_TTL_SECS", "3600")
    fake_ddg.set("empty query", {})
    async with Client(mcp) as c:
        r1 = await c.call_tool("web_search", {"query": "empty query"})
        r2 = await c.call_tool("web_search", {"query": "empty query"})
        assert r1.structured_content["results"] == []
        assert r1.structured_content["note"] == EMPTY_NOTE
        assert r2.structured_content["source"] == "cache"
        # Note is preserved on cache hit when the original result was empty.
        assert r2.structured_content["note"] == EMPTY_NOTE


async def test_upstream_500_raises_tool_error(fake_ddg):
    fake_ddg.set_status("failing", 503)
    async with Client(mcp) as c:
        with pytest.raises(Exception) as ei:
            await c.call_tool("web_search", {"query": "failing"})
        assert "503" in str(ei.value)


async def test_modern_protocol_negotiated(fake_ddg):
    async with Client(mcp) as c:
        assert c.protocol_version == "2026-07-28"


async def test_legacy_era_also_calls_the_tool(fake_ddg):
    fake_ddg.set("Rust", {})  # empty upstream → empty result + note
    async with Client(mcp, mode="legacy") as c:
        result = await c.call_tool("web_search", {"query": "Rust", "count": 3})
        sc = result.structured_content
        assert sc["query"] == "Rust"
        assert sc["note"] == EMPTY_NOTE


async def test_health_endpoint_returns_200():
    # The /health route is registered on the ASGI app; we hit it through the
    # underlying Starlette client (httpx.AsyncClient(transport=ASGITransport(app=mcp.http_app()))).
    from starlette.testclient import TestClient
    client = TestClient(mcp.http_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
