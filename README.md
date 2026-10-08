# Duck Duck Go search MCP

A [Model Context Protocol](https://modelcontextprotocol.io/) server that exposes the free, unauthenticated DuckDuckGo Instant Answer API as a `web_search` tool, plus a `research_entity` prompt that helps any AI agent get the most from each search. No API key, no account, no rate-limit tier.

Built on **FastMCP 4.0.11** and targeting the **MCP 2026-07-28** revision. Runs over Streamable HTTP (default) or stdio.

## What you get

- `web_search(query, count=5)` — entity-shaped web search, returns short snippets with `{title, url, snippet}`.
- `research_entity(topic)` — a reusable prompt that plans a single `web_search` call and defines the empty-result fallback.
- On-disk TTL cache (24 h default) and a min-interval rate limiter so you are a polite citizen of the free shared DDG endpoint.
- No auth, loopback bind by design. Expose via **VS Code port forwarding** (recommended) or ngrok.

## Quick start

```bash
# Install (Python 3.10+)
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Run (Streamable HTTP on http://127.0.0.1:8000/mcp)
python3 -m duck_search_mcp
```

Then either:

- **Local use** — point an MCP client at `http://127.0.0.1:8000/mcp` on the same machine.
- **VS Code port forwarding** — open the Ports panel, forward `8000`, copy the tunnel URL, point your client at `<forwarded-url>/mcp`. See [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md).
- **ngrok** — `ngrok http 8000`, use the printed URL the same way.

## Documentation

- [docs/SPECS.md](./docs/SPECS.md) — the contract this server commits to: protocol, tool schema, response mapping, failure modes, acceptance criteria.
- [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) — connection recipes for every supported client, plus hardening notes for non-loopback exposure.
- [.agents/skills/mcp-fastmcp-2026/](./.agents/skills/mcp-fastmcp-2026/) — the skill this server was built against, kept in-tree for future agents and for the static audit and wire-probe scripts.

## Testing

```bash
.venv/bin/pytest                            # 42 unit tests, hermetic
DUCK_SEARCH_NETWORK_TESTS=1 .venv/bin/pytest    # + 2 integration tests, real DDG
.venv/bin/python .agents/skills/mcp-fastmcp-2026/scripts/audit_mcp_project.py .   # static
```

After starting the server:

```bash
.venv/bin/python .agents/skills/mcp-fastmcp-2026/scripts/probe_mcp_server.py http://127.0.0.1:8000/mcp   # wire probe
```

## Why the limits are where they are

The Instant Answer API is **not** a general web-search index. It only answers entity-shaped queries (people, places, products, standards) and returns empty `200`s for most long-tail / question-shaped queries. That is the protocol's behaviour, not a bug. The tool surfaces this honestly via the `note` field so the model can rephrase or fall back to its own knowledge — no silent fabrication.

If you need long-tail search, point a different MCP at a real search index (Tavily, Brave, etc.) and let the agent choose. This server is the free default; the paid general search is a separate concern.
