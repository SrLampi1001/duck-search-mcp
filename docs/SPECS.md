# `duckduckgo-mcp` — MCP server

> **Status:** spec only, not yet implemented. The behaviour described below is the **minimum required to be considered a viable replacement for the current `web_search_basic` tool**. Implementation happens in this repo; integration with the agent happens by editing  `config/mcp.toml` in the `rust-agent` repo. (/home/srlampi/Documents/projects/rust-agent/)

A [Model Context Protocol](https://modelcontextprotocol.io/) server that exposes a single free, unauthenticated web-search tool to the `rust-agent` over stdio:

| Tool | Backend | Cost | Best for |
| --- | --- | --- | --- |
| `web_search` | DuckDuckGo Instant Answer API | Free, no key | Entity-like queries (people, places, products, standards). Short snippets, no page contents. |

The Rust agent spawns this server as a child process via the official [`rmcp`](https://github.com/modelcontextprotocol/rust-sdk) crate, lists the tool, and registers it as a regular `rig::tool::Tool`. From the agent's point of view the tool is indistinguishable from any other.

---

## 1. Why this server exists

This server is one of **three** that together replace the current bundled `mcp-servers/web-search/` MCP. The bundle is being split so each backend (DDG, Firecrawl, Tavily) can be enabled, disabled, scaled, and rate-limited independently. The agent code is **unaware** of the split — it still sees one `web_search`-shaped tool per server, with the server-name prefix disambiguating which backend answered.

DDG's Instant Answer API is the free, no-key path. The trade-off is that it is **not** a general web-search index:

- It only answers **entity-shaped** queries (Wikipedia-style entries: people, places, products, standards, calculations).
- It returns an empty 200 for most long-tail / question-shaped queries. That is normal, not an error — see §6.
- It does not return page contents, only short snippets.

The companion MCPs cover what DDG can't:

- **Tavily** for general question-shaped queries (free tier, agent-tuned).
- **Firecrawl** for deep content extraction (paid; returns full page
  bodies as markdown).

Together the three give the agent a layered search strategy where the free path is the default and the paid path is reserved for the few queries that genuinely need it.

---

## 2. Protocol contract

The agent (per [`docs/mcp.md`](https://github.com/example/rust-agent/blob/main/docs/mcp.md) §8) requires:

1. Speaks **MCP 2026-07-28** (https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning#protocol-version-negotiation).
2. Accepts JSON-args objects on `tools/call`.
3. Returns either `structured_content` (preferred) or at least one text content block.
4. Advertises at least one tool on `tools/list`.

Anything beyond this contract is a server-side decision.

---

## 3. Tool

### `web_search` (single tool)

**Input schema** (JSON Schema, surfaced verbatim to the model):

```json
{
  "type": "object",
  "properties": {
    "query":  { "type": "string",  "description": "..." },
    "count":  { "type": "integer", "minimum": 1, "maximum": 10,
                "default": 5,     "description": "..." }
  },
  "required": ["query"],
  "additionalProperties": false
}
```

| Argument | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `query` | string | yes | – | The search query. Trimmed and lowercased before any cache lookup; original query is echoed in the response. |
| `count` | integer | no | 5 | Max results to return. Clamped to `[1, 10]`. Applied **client-side** — the upstream API has no `count` parameter. |

**Output** (`structured_content`, a JSON object):

```json
{
  "query": "Rust programming language",
  "results": [
    { "title": "Rust (programming language) - Wikipedia",
      "url":   "https://en.wikipedia.org/wiki/Rust_(programming_language)",
      "snippet": "Rust is a general-purpose programming language..." }
  ],
  "source": "upstream" | "cache",
  "note":   "" | "DuckDuckGo returned no results — rephrase once as a canonical topic name, then answer from your own knowledge."
}
```

| Field | Type | Notes |
| --- | --- | --- |
| `query` | string | The query as the server received it (after `trim()`). |
| `results` | array of `{title, url, snippet}` | Mapped from DDG's `AbstractText` / `RelatedTopics`. See §4. Capped at `count`. |
| `source` | `"upstream"` or `"cache"` | Tells the model whether this call hit the network. Useful for the model's budgeting, not for end-user display. |
| `note` | string | Non-empty only on empty results. Tells the model what happened and what to do. |

**Description (the model reads this verbatim):**

> Free, unauthenticated web search via the DuckDuckGo Instant Answer
> API. **Reach for this first for entity-like queries** — people,
> places, products, standards, programming languages, calculations.
> Returns short snippets; no page contents. For long-tail or
> question-shaped queries the API often returns an empty response
> (that's a 200 with `results: []` plus a guidance `note`, **not an
> error**); rephrase as a canonical topic name at most once, then
> fall back to the `firecrawl__web_search` or `tavily__web_search`
> tool. Use `count` to cap the result list (default 5, max 10).

---

## 4. Response mapping

The DDG Instant Answer API returns a JSON document with `AbstractText`, `AbstractURL`, `Heading`, `Answer`, and `RelatedTopics`. The mapping mirrors the one in the current `mcp-servers/web-search/server.py` so the agent sees no behavioural change:

1. **The abstract** — `AbstractText` / `AbstractURL` / `Heading`. This is the "real" instant answer (usually a Wikipedia lead paragraph). Used when non-empty.
2. **The direct answer** — `Answer`, only when there is no abstract (calculations, unit conversions). Often has no URL.
3. **Related topics** — `RelatedTopics`, flattened: entries with a nested `Topics` array are recursed into. The `Text` field (usually `"<Title> - <one-liner>"`) is split on the first `" - "` to derive the title.

Everything else (`Image`, `Redirect`, `Definition*`, `Type`, `meta`, …) is dropped.

The result list is capped at `count` (clamped to `[1, 10]`). Capping applies **after** mapping, not before.

---

## 5. Configuration

All configuration is via environment variables. The Rust agent forwards the relevant ones when it spawns the server via the `env_pass` allow-list in `config/mcp.toml` — see the agent's [`docs/mcp.md`](https://github.com/example/rust-agent/blob/main/docs/mcp.md) §3 for the env-forwarding semantics.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DDG_CACHE_DIR` | `./cache/ddg` | On-disk cache directory. Gitignored. |
| `DDG_CACHE_TTL_SECS` | `86400` | Cache freshness window, seconds. `0` disables the cache. |
| `DDG_MIN_INTERVAL_MS` | `1100` | Minimum spacing between upstream DDG calls. Concurrent calls queue on a shared mutex. |
| `MCP_LOG_LEVEL` | `WARNING` | `DEBUG` / `INFO` / `WARNING`. Logs go to **stderr** (stdout is the JSON-RPC stream). |

**No API key is required.** The DDG Instant Answer API is free and unauthenticated. The `t=rust-agent` query parameter identifies the consumer to DDG.

---

## 6. Empty responses are normal

A `200 OK` with empty fields (`Heading: ""`, `AbstractText: ""`, `RelatedTopics: []`) means **"DuckDuckGo has no instant answer for this query"** — not "the API is broken" and not "retry". Common causes, in rough order:

1. The query is question-shaped or long-tail. Rephrase as a canonical topic name (`"Rust programming language"` instead of `"how do I write async code in Rust"`).
2. The topic has no instant answer (too niche, too recent).
3. The endpoint is throttling you. DDG sometimes answers heavy traffic with empty `200`s or `202`s instead of a clean `429`.

**Behaviour:**

- The tool **never** errors on an empty response. It returns `results: []` plus the guidance `note` quoted in §3.
- Non-2xx upstream statuses (real `429`, `5xx`) are surfaced as `is_error: true` with the status text. The model can fall back.
- A cache miss followed by an empty upstream response **is cached** for the TTL — the next call within 24 h gets the same empty result with zero network traffic. (Polite consumer of a free shared resource.)

---

## 7. Caching

On-disk TTL cache, key = normalised query (trimmed, inner whitespace collapsed, lowercased). File name = `<slug>-<fnv1a64>.json`. The slug keeps the directory human-browsable; the FNV-1a 64-bit hash disambiguates queries that slugify identically (`"c++"` vs `"c#"`). Envelope:

```json
{ "fetched_at_unix": 1730000000,
  "query": "rust programming language",
  "results": [ ... ] }
```

**Failure semantics:** a missing, stale, corrupt, or unwritable cache entry **never fails the call**. The tool logs a `warn` and degrades to a plain uncached call. The agent's tool-error path is reserved for real upstream failures.

The cache directory is gitignored. Delete any time to force fresh lookups.

---

## 8. Install / setup

Match the layout of the existing `mcp-servers/web-search/` so an operator who has set that up before can copy-paste:

```bash
cd rust-agent-duckduckgo-mcp
python3 -m venv .venv      # or: uv venv --python 3.12 .venv
source .venv/bin/activate
pip install -e .
```

**Dependencies (suggested):**

- `fastmcp>=2.0` — MCP server framework. (The project is `prefecthq/fastmcp` on GitHub but published as `fastmcp` on PyPI; it is the standard framework for building MCP servers in Python and powers most of the Python MCP ecosystem.)
- `httpx>=0.27` — plain async HTTP client. The DDG Instant Answer API is unauthenticated and JSON-shaped, so no SDK is needed.

Tested with Python 3.10+. Other interpreters are fine as long as the `rmcp` 0.8 client on the agent side negotiates `2024-11-05` (the version `fastmcp` 2.x ships).

---

## 9. Run by hand (for debugging)

```bash
# The server speaks JSON-RPC over stdio. A blank stdin will let
# it sit idle; pipe a real `initialize` + `tools/list` exchange
# to see the registered tool schema.
python3 -m duckduckgo_mcp
```

To smoke-test the tool without the agent, point any MCP client at the running process (e.g. the `mcp-cli` Python package, or `npx @modelcontextprotocol/inspector`). Expected: a `tools/list` response containing exactly one tool, `web_search`, with the schema in §3.

---

## 10. Integration with `rust-agent`

Add a single entry to `config/mcp.toml` in the `rust-agent` repo:

```toml
[[mcp.servers]]
name = "duckduckgo"
command = ["/abs/path/to/rust-agent-duckduckgo-mcp/.venv/bin/python",
           "/abs/path/to/rust-agent-duckduckgo-mcp/duckduckgo_mcp/__main__.py"]
env_pass = ["PATH", "HOME"]   # no API keys needed
enabled = true
```

Restart the agent. The model now sees the tool under its qualified name `duckduckgo__web_search`. To temporarily disable DDG without removing the entry, set `enabled = false` (the agent parses and validates the entry but skips spawning).

The default `web-search` MCP entry in `config/mcp.toml` (the bundled DDG + Firecrawl one) **must be removed or disabled** before the new DDG entry is enabled, or the agent will register two `web_search` shaped tools and the model will be confused about which to use.

---

## 11. Failure modes and how the model reacts

| What goes wrong | What the tool does | What the model sees |
| --- | --- | --- |
| Upstream returns `200` with empty fields | Returns `results: []` + the guidance `note` | A normal success, empty results, with an instruction to rephrase once or fall back. |
| Upstream returns non-2xx (`429`, `5xx`) | `is_error: true` with the status text | A clear HTTP error. The model retries with the `tavily__web_search` tool, or moves on. |
| Upstream throttling (empty `200`s) | Cached entry still serves; misses return the empty-result shape | Same as the first row — the model only sees the standard shape. |
| Cache directory missing / unwritable | Logs `warn`; falls through to a plain uncached call | The tool still works, just slower on repeat queries. |
| Cache file corrupt | Logs `warn`; falls through to a fresh upstream call | Same. |
| DDG endpoint changes shape | The mapper may return `results: []` for previously-working queries | Empty results with the standard `note`. Operators notice; the schema-mapping code is the only thing to update. |
| MCP server child dies | The `rmcp` client surfaces an `ErrorData`; the tool returns a protocol-level error | A connection error. The supervisor loop's standard "two empty iterations" rule nudges the model. |
| Server didn't spawn (venv missing) | `build_agent` returns an error at agent startup | The agent refuses to start with a clear message naming the server and the command. **No silent fallback** — the design choice documented in `docs/mcp.md` §7. |

---

## 12. Context-budget protection

The DDG tool's per-result content is small (a snippet, not a page body), so a single call with `count=10` is on the order of a few hundred tokens. No per-result markdown cap is required. The agent's existing `RUST_AGENT_CONTEXT_PRESSURE_THRESHOLD_TOKENS` guard (default 800k, sized for MiniMax-M3's 1M-token window) covers the multi-call case end-to-end.

---

## 13. Acceptance criteria (minimum viable)

The implementation is "good enough to unblock the agent" when **all** of the following hold:

1. `pip install -e .` from a clean checkout succeeds on Python 3.10+.
2. `python3 -m duckduckgo_mcp` starts and responds to a manual`initialize` + `tools/list` JSON-RPC exchange (smoke test).
3. The advertised tool is exactly `web_search`, with the input schema and description in §3.
4. A live call against the DDG Instant Answer API with a canonical entity query (`"Rust programming language"`, `"HTTP 418"`, `"Isaac Newton"`) returns at least one result.
5. A live call with a known-empty long-tail query (the one in `tests/mcp.rs::basic_search_long_tail_returns_empty_with_note`) returns `results: []` plus a non-empty `note`.
6. Two identical calls within the cache TTL produce a second response with `source: "cache"` and no upstream traffic.
7. Spawning this server from the agent's `config/mcp.toml` succeeds, the model sees the tool as `duckduckgo__web_search`, and a one-shot request (`cargo run -- run --request "What is the capital of Japan?"`) triggers at least one call to it.

---

## 14. Test plan

Unit tests (hermetic, no network):

- `cache_round_trip_serves_second_call_from_disk` — write a cache entry, read it back, assert `source: "cache"`.
- `cache_corrupt_file_falls_through_to_upstream` — write garbage to a cache file, assert the call still succeeds (with a `warn` log).
- `count_is_clamped_to_1_through_10` — assert `count=0` clamps to `1`, `count=11` clamps to `10`, `count=None` (omitted) defaults to `5`.
- `query_is_trimmed_and_echoed` — assert `"  hello  "` is stored as `"hello"` and returned in the `query` field.
- `empty_ddg_response_returns_empty_results_with_note` — feed a canned empty `200` response, assert the shape.

Integration tests (network, gated on the venv existing, mirroring `tests/mcp.rs` in the agent)

- `mcp_server_advertises_web_search` — handshake, `tools/list`, assert exactly one tool named `web_search`.
- `basic_search_returns_structured_results` — call `"Rust programming language"`, assert `results.len() >= 1` and `source in {"upstream", "cache"}`.
- `basic_search_long_tail_returns_empty_with_note` — call the known-empty long-tail query, assert `results == []` and `note != ""`.
- `second_call_within_ttl_serves_from_cache` — call twice, assert the second has `source: "cache"`.

End-to-end (manual, smoke checklist from `docs/testing.md`):

- `cargo run -- run --request "What is the capital of Japan?"` — assert at least one `duckduckgo__web_search` tool call in the log, and a non-empty final reply.

---

## 15. Out of scope for v0.1

- **No other DDG endpoints.** The Images API, the Video API, etc. are not exposed. Only the Instant Answer API.
- **No general web-search index.** The Instant Answer API is an entity-lookup API, not a web index. Long-tail queries are out of scope for this server; the agent should fall back to `tavily__web_search` or `firecrawl__web_search`.
- **No rate-limit-aware retries.** DDG's "soft 429" (empty `200`s) is handled by the cache; the tool does not implement explicit backoff. Operators monitor logs.
- **No parallel upstream calls.** A single in-flight upstream request is the unit. The shared `min_interval_ms` mutex serialises them.
- **No HTTP transport.** Stdio only, per `docs/mcp.md` §6. When the agent's HTTP transport lands, this server may be wrapped behind a small stdio-to-HTTP shim, or a parallel HTTP entry point can be added later — out of scope for v0.1.

---

## 16. References

- Agent integration overview: [`docs/mcp.md`](https://github.com/example/rust-agent/blob/main/docs/mcp.md) in the `rust-agent` repo.
- Agent's `tools::mcp` module-level reference: [`docs/modules/tools-mcp.md`](https://github.com/example/rust-agent/blob/main/docs/modules/tools-mcp.md).
- Existing bundled DDG + Firecrawl MCP (split source for this work): [`mcp-servers/web-search/`](https://github.com/example/rust-agent/tree/main/mcp-servers/web-search) in the `rust-agent` repo — specifically `server.py` (the `web_search_basic` / `_do_ddg_basic_search` path) and `docs/duckduckgo-api.md` (the API contract and empty-response semantics). When the bundled MCP is retired, that document moves here.
- DDG Instant Answer API overview: <https://duckduckgo.com/duckduckgo-help-pages/settings/params> and <https://api.duckduckgo.com/api>.
- MCP specification: <https://modelcontextprotocol.io>.
- `fastmcp` (Python MCP server framework): <https://github.com/PrefectHQ/fastmcp>.
