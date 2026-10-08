# `duck-search-mcp` — MCP server

> **Status:** v0.1 implemented. Speaks MCP 2026-07-28 over Streamable HTTP and stdio, built on FastMCP 4.0.11. The behaviour described below is the contract this server commits to.

A [Model Context Protocol](https://modelcontextprotocol.io/specification/2026-07-28) server that exposes a free, unauthenticated web-search tool backed by the DuckDuckGo Instant Answer API. No API key, no account, no rate-limit tier — just one entity-shaped query in and a few short snippets out.

| Tool | Backend | Cost | Best for |
| --- | --- | --- | --- |
| `web_search` | DuckDuckGo Instant Answer API | Free, no key | Entity-like queries (people, places, products, standards). Short snippets, no page contents. |

| Prompt | Use |
| --- | --- |
| `research_entity` | Plan a single `web_search` call for a topic, including the empty-result fallback. |

---

## 1. Why this server exists

DDG's Instant Answer API is the free, no-key path. The trade-off is that it is **not** a general web-search index:

- It only answers **entity-shaped** queries (Wikipedia-style entries: people, places, products, standards, calculations).
- It returns an empty 200 for most long-tail / question-shaped queries. That is normal, not an error — see §6.
- It does not return page contents, only short snippets.

This server does not try to compensate. The companion MCPs that cover the other shapes (general question-shaped search, full-page extraction) are out of scope; agents that need them should call them as separate tools.

---

## 2. Protocol contract

The server is built on **FastMCP 4.0.11** and targets the **MCP 2026-07-28** revision. It is dual-era out of the box — modern clients negotiate the stateless protocol, legacy clients that send `initialize` still get a working session.

| Contract | Value |
| --- | --- |
| Protocol revision | `2026-07-28` (advertised via `server/discover`; legacy `initialize` negotiates `2025-11-25`) |
| Transports | Streamable HTTP at `/mcp` (default), stdio (opt-in via `DUCK_SEARCH_TRANSPORT=stdio`) |
| Bind address | `127.0.0.1` (loopback only; expose via VS Code port forwarding or ngrok — see `docs/DEPLOYMENT.md`) |
| Authentication | **None.** Loopback binding is the only access control. Operate behind a trusted tunnel. |
| Required response fields | `MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name` headers; tool list advertises `ttlMs`/`cacheScope` |
| Server features | `tools` (one), `prompts` (one), `resources/templates` (none), `extensions: io.modelcontextprotocol/ui` |

Any modern MCP client (Claude Desktop, Cursor, opencode, VS Code Copilot Chat) that supports Streamable HTTP can connect to the forwarded URL without code changes.

---

## 3. Tool

### `web_search` (single tool)

**Input schema** (JSON Schema, surfaced verbatim to the model):

```json
{
  "type": "object",
  "properties": {
    "query":  { "type": "string",  "description": "...",
                "minLength": 1 },
    "count":  { "type": "integer", "description": "...",
                "default": 5 }
  },
  "required": ["query"],
  "additionalProperties": false
}
```

| Argument | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `query` | string | yes | – | The search query. Trimmed before any cache lookup; the trimmed query is echoed in the response. |
| `count` | integer | no | 5 | Max results to return. **Clamped** to `[1, 10]` server-side (out-of-range values are not rejected, they are clamped). Applied after mapping. |

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
| `source` | `"upstream"` or `"cache"` | Tells the model whether this call hit the network. |
| `note` | string | Non-empty on empty results. Tells the model what happened and what to do. |

**Description (the model reads this verbatim):**

> Free, unauthenticated web search via the DuckDuckGo Instant Answer API. Reach for this first for entity-like queries — people, places, products, standards, programming languages, calculations. Returns short snippets; no page contents. For long-tail or question-shaped queries the API often returns an empty response (that's a 200 with results: [] plus a guidance note, NOT an error); rephrase as a canonical topic name at most once, then fall back to your own knowledge. Use count to cap the result list (default 5, max 10).

---

## 4. Response mapping

The DDG Instant Answer API returns a JSON document with `AbstractText`, `AbstractURL`, `Heading`, `Answer`, and `RelatedTopics`. The mapping mirrors the legacy web-search MCP so behaviour is unchanged:

1. **The abstract** — `AbstractText` / `AbstractURL` / `Heading`. This is the "real" instant answer (usually a Wikipedia lead paragraph). Used when non-empty.
2. **The direct answer** — `Answer`, only when there is no abstract (calculations, unit conversions). Often has no URL.
3. **Related topics** — `RelatedTopics`, flattened: entries with a nested `Topics` array are recursed into. The `Text` field (usually `"<Title> - <one-liner>"`) is split on the first `" - "` to derive the title. Without a separator, the whole `Text` is used for both `title` and `snippet`.

Everything else (`Image`, `Redirect`, `Definition*`, `Type`, `meta`, …) is dropped.

The result list is capped at `count` (clamped to `[1, 10]`). A hard ceiling of 10 is applied during mapping as well, so a single `web_search` call never materialises megabytes of related topics.

---

## 5. Configuration

All configuration is via environment variables. See `.env.example` for the full list with defaults.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DUCK_SEARCH_TRANSPORT` | `http` | `http` (Streamable HTTP) or `stdio`. |
| `DUCK_SEARCH_HOST` | `127.0.0.1` | Bind address for HTTP transport. Loopback by design. |
| `DUCK_SEARCH_PORT` | `8000` | Port for HTTP transport. |
| `DUCK_SEARCH_PATH` | `/mcp` | URL path for the MCP endpoint. |
| `DDG_CACHE_DIR` | `./cache/ddg` | On-disk cache directory. Gitignored. |
| `DDG_CACHE_TTL_SECS` | `86400` | Cache freshness window, seconds. `0` disables the cache. |
| `DDG_MIN_INTERVAL_MS` | `1100` | Minimum spacing between upstream DDG calls. Concurrent calls queue on a shared mutex. |
| `DDG_HTTP_TIMEOUT_S` | `10` | Upstream HTTP request timeout in seconds. |
| `MCP_LOG_LEVEL` | `WARNING` | `DEBUG` / `INFO` / `WARNING` / `ERROR`. Logs go to **stderr** (stdout is the JSON-RPC stream). `FASTMCP_LOG_LEVEL` is honoured as a fallback. |

**No API key is required.** The DDG Instant Answer API is free and unauthenticated. The `t=duck-search-mcp` query parameter identifies the consumer to DDG.

---

## 6. Empty responses are normal

A `200 OK` with empty fields (`Heading: ""`, `AbstractText: ""`, `RelatedTopics: []`) means **"DuckDuckGo has no instant answer for this query"** — not "the API is broken" and not "retry". Common causes, in rough order:

1. The query is question-shaped or long-tail. Rephrase as a canonical topic name (`"Rust programming language"` instead of `"how do I write async code in Rust"`).
2. The topic has no instant answer (too niche, too recent).
3. The endpoint is throttling you. DDG sometimes answers heavy traffic with empty `200`s or `202`s instead of a clean `429`.

**Behaviour:**

- The tool **never** errors on an empty response. It returns `results: []` plus the guidance `note` quoted in §3.
- Non-2xx upstream statuses (real `429`, `5xx`) surface as a `ToolError` with the status text. The model can fall back.
- A cache miss followed by an empty upstream response **is cached** for the TTL — the next call within 24 h gets the same empty result with zero network traffic.

---

## 7. Caching

On-disk TTL cache, key = normalised query (trimmed, inner whitespace collapsed, lowercased). File name = `<slug>-<fnv1a64>.json`. The slug keeps the directory human-browsable; the FNV-1a 64-bit hash disambiguates queries that slugify identically (`"c++"` vs `"c#"`). Envelope:

```json
{ "fetched_at_unix": 1730000000,
  "query": "rust programming language",
  "results": [ ... ] }
```

**Failure semantics:** a missing, stale, corrupt, or unwritable cache entry **never fails the call**. The tool logs a `warn` and degrades to a plain uncached call.

The cache directory is gitignored. Delete any time to force fresh lookups.

---

## 8. Prompts

### `research_entity`

A reusable user-message prompt that sets up a single `web_search` call. Args: `topic: str`. Returns a user message that:

1. Tells the model to use `web_search` with a canonical topic name (not a question).
2. Sets `count=5`.
3. Defines the empty-result fallback: rephrase once, then fall back to the model's own knowledge and say so.

Registered on the same FastMCP instance as the tool. No extra setup.

---

## 9. Install / setup

```bash
cd duck-search-mcp
python3 -m venv .venv           # or: uv venv --python 3.12 .venv
source .venv/bin/activate
pip install -e .                # or: uv pip install -e .
```

**Dependencies (pinned, per the project's `pyproject.toml`):**

- `fastmcp==4.0.11` — MCP server framework, the standalone PrefectHQ package.
- `httpx>=0.27` — async HTTP client. The DDG Instant Answer API is unauthenticated and JSON-shaped, so no SDK is needed.

Tested with Python 3.12. Works on 3.10+.

---

## 10. Run by hand

```bash
# HTTP (default) — listen on http://127.0.0.1:8000/mcp
python3 -m duck_search_mcp

# Stdio — for clients that spawn the server as a child process
DUCK_SEARCH_TRANSPORT=stdio python3 -m duck_search_mcp
```

A blank stdin in stdio mode lets the server sit idle. Point any MCP client (opencode, Claude Desktop, VS Code, Cursor) at the URL or spawn the process; see `docs/DEPLOYMENT.md` for the connection recipes.

---

## 11. Deployment

Two supported paths. Both rely on the server binding to `127.0.0.1`; neither requires the server itself to know it's being forwarded.

1. **VS Code "Forward a Port"** (recommended). Open the Ports panel, forward `8000`, copy the URL, point your client at `<forwarded-url>/mcp`. The tunnel runs through Microsoft's relay — no public hostname to block.
2. **ngrok** (fallback). `ngrok http 8000`, point your client at `<ngrok-url>/mcp`. Free-tier URLs are publicly enumerable; corporate networks often block them.

For both, the server is started with `python3 -m duck_search_mcp`. No auth is configured — the loopback bind + tunnel auth is the access control. See `docs/DEPLOYMENT.md` for the full step-by-step.

---

## 12. Failure modes

| What goes wrong | What the tool does | What the model sees |
| --- | --- | --- |
| Upstream returns `200` with empty fields | Returns `results: []` + the guidance `note` | A normal success, empty results, with an instruction to rephrase once or fall back. |
| Upstream returns non-2xx (`429`, `5xx`) | Raises `ToolError` with the status text | A clear HTTP error. The model retries with another tool, or moves on. |
| Upstream throttling (empty `200`s) | Cached entry still serves; misses return the empty-result shape | Same as the first row — the model only sees the standard shape. |
| Cache directory missing / unwritable | Logs `warn`; falls through to a plain uncached call | The tool still works, just slower on repeat queries. |
| Cache file corrupt | Logs `warn`; falls through to a fresh upstream call | Same. |
| DDG endpoint changes shape | The mapper may return `results: []` for previously-working queries | Empty results with the standard `note`. Operators notice; the schema-mapping code is the only thing to update. |
| Server didn't start (port in use, venv missing) | Process exits with a clear log line on stderr | The client gets a connection error. No silent fallback. |
| Foreign `Origin` header | Accepted when the server is bound to `127.0.0.1` (DNS rebinding isn't possible) | The probe flags this as a WARN; see `docs/DEPLOYMENT.md` for when to enable `http_host_origin_protection`. |

---

## 13. Acceptance criteria

The implementation is "good enough to ship" when **all** of the following hold:

1. `pip install -e .` from a clean checkout succeeds on Python 3.10+. ✅
2. `python3 -m duck_search_mcp` starts on `http://127.0.0.1:8000/mcp` and answers `server/discover` with `supportedVersions: ["2026-07-28"]`. ✅
3. The advertised tool is exactly `web_search`, with the input schema and description in §3. ✅
4. A live call against the DDG Instant Answer API with a canonical entity query (`"Rust programming language"`, `"HTTP 418"`, `"Isaac Newton"`) returns at least one result. ✅
5. A live call with a known-empty long-tail query returns `results: []` plus a non-empty `note`. ✅
6. Two identical calls within the cache TTL produce a second response with `source: "cache"` and no upstream traffic. ✅
7. The wire probe (`scripts/probe_mcp_server.py`) reports 0 failures against the live server. ✅
8. The in-process test suite (`pytest`) reports 0 failures in both `mode="auto"` and `mode="legacy"`. ✅

---

## 14. Test plan

Unit tests (hermetic, no network) live in `tests/`:

- `test_normalize.py` — query normalisation, slug, FNV-1a 64-bit hash.
- `test_cache.py` — round trip, normalisation equivalence, stale entry, corrupt file, unwritable dir, atomic write.
- `test_rate_limit.py` — disabled at 0 ms, serial waits spaced, concurrent waits queued.
- `test_ddg_mapping.py` — empty payload, abstract, answer, related topics, recursion, hard cap, specials drop.
- `test_server.py` — tool/prompt advertisement, basic search, trim+echo, count clamp, empty result, cache second call, upstream error, both client modes.
- `test_server_integration.py` — real DDG calls, skipped unless `DUCK_SEARCH_NETWORK_TESTS=1`.

End-to-end (manual):

- `python3 -m duck_search_mcp` then connect from any modern MCP client (opencode, VS Code, Claude Desktop, Cursor) and confirm `web_search` appears and returns results.

---

## 15. Out of scope for v0.1

- **No other DDG endpoints.** The Images API, the Video API, etc. are not exposed. Only the Instant Answer API.
- **No general web-search index.** Long-tail queries are out of scope; the agent should fall back to its own knowledge or a different tool.
- **No rate-limit-aware retries.** DDG's "soft 429" (empty `200`s) is handled by the cache; the tool does not implement explicit backoff. Operators monitor logs.
- **No parallel upstream calls.** A single in-flight upstream request is the unit. The shared `min_interval_ms` mutex serialises them.
- **No authentication.** The server is open by design; access control relies on the loopback bind plus whatever the user puts in front (VS Code tunnel, ngrok, etc.).

---

## 16. References

- MCP specification (target revision): https://modelcontextprotocol.io/specification/2026-07-28/
- MCP `server/discover`: https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/discover
- DDG Instant Answer API overview: https://duckduckgo.com/duckduckgo-help-pages/settings/params and https://api.duckduckgo.com/api.
- FastMCP (Python MCP server framework): https://github.com/PrefectHQ/fastmcp and https://gofastmcp.com.
- VS Code Streamable HTTP support: https://code.visualstudio.com/api/extension-guides/ai/mcp
