# Deployment

The server is designed to be **simple to expose** and **hard to misuse**. It binds to `127.0.0.1` by default and ships without any authentication, on the assumption that whatever you put in front of it (a tunnel, a reverse proxy, your laptop's firewall) is the access control.

Two paths are supported. **VS Code port forwarding is recommended** because the tunnel runs through Microsoft's relay — no public hostname that corporate firewalls can blanket-block.

---

## 1. VS Code port forwarding (recommended)

Works on VS Code desktop (local forwarding), VS Code remote (SSH/devcontainer), and GitHub Codespaces. The forward is a public HTTPS URL authenticated by the tunnel; only people with the URL (or signed-in to your VS Code session) can reach it.

### 1.1 Start the server

In a VS Code terminal:

```bash
cd duck-search-mcp
source .venv/bin/activate          # if not already active
python3 -m duck_search_mcp
```

You should see:

```
INFO  Starting MCP server 'duck-search-mcp' with transport 'http' on http://127.0.0.1:8000/mcp
INFO  Uvicorn running on http://127.0.0.1:8000
```

The server is now reachable at `http://127.0.0.1:8000/mcp` on the local machine. A liveness probe is also available at `http://127.0.0.1:8000/health` (returns `200 OK` with `{"status": "ok"}`) — this is what VS Code's port-forward tunnel hits to verify the local port is alive.

### 1.2 Forward the port

1. Open the **Ports** panel (`Ctrl+Shift+P` → "Ports: Focus on Ports View", or click the **Ports** tab in the bottom panel).
2. Click **Forward a Port**.
3. Enter `8000`. Leave the protocol as `http`. Visibility defaults to **Auto**; switch to **Public** if you need to reach it from outside the tunnel's signed-in session.
4. Right-click the new forwarded port row → **Copy Local Address** or **Show Tunnel**.

The forward URL looks like `https://vscode-<...>.devtunnels.ms` or `https://<...>.github.dev` (Codespaces). The MCP endpoint is `<forwarded-url>/mcp`.

### 1.3 Point an MCP client at it

Any modern MCP client that supports Streamable HTTP. Examples:

**opencode** (or any FastMCP-based client):
```python
from fastmcp import Client
async with Client("https://<your-tunnel>/mcp") as c:
    print(await c.list_tools())  # → [web_search]
```

**Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "duck-search": {
      "type": "http",
      "url": "https://<your-tunnel>/mcp"
    }
  }
}
```

**VS Code Copilot Chat** (`.vscode/mcp.json` in any workspace):
```json
{
  "servers": {
    "duck-search": {
      "type": "http",
      "url": "https://<your-tunnel>/mcp"
    }
  }
}
```

Then run `MCP: List Servers` from the command palette and start the server.

**Cursor** — Settings → Features → MCP Servers → **Add new MCP server** → type `http` → paste the URL → name it `duck-search`.

### 1.4 Verify the tunnel

```bash
curl -s -X POST https://<your-tunnel>/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2026-07-28' -H 'Mcp-Method: server/discover' \
  -d '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{
        "io.modelcontextprotocol/protocolVersion":"2026-07-28",
        "io.modelcontextprotocol/clientInfo":{"name":"curl","version":"1"},
        "io.modelcontextprotocol/clientCapabilities":{}}}}'
```

You should see `"supportedVersions": ["2026-07-28"]` and the `web_search` tool in `tools/list`.

---

## 2. ngrok (fallback)

Use when you can't or don't want to use VS Code's tunnel. The trade-off: free-tier ngrok URLs are publicly enumerable and frequently blocked by corporate firewalls.

```bash
# Terminal 1: the server
cd duck-search-mcp
source .venv/bin/activate
python3 -m duck_search_mcp

# Terminal 2: the tunnel
ngrok http 8000
```

ngrok prints a `https://<...>.ngrok-free.app` URL. The MCP endpoint is `<ngrok-url>/mcp`. Use the same client config snippets as in §1.3, replacing the URL.

If you have a paid ngrok account and want a fixed subdomain or reserved domain, pass it on the command line: `ngrok http 8000 --domain=my-search.ngrok.app`.

---

## 3. Plain local use (no tunnel)

For development and testing without exposing the server, just point an MCP client at `http://127.0.0.1:8000/mcp` on the same machine. No tunnel, no firewall concerns.

**fastmcp CLI smoke test** (no client wiring required):

```bash
fastmcp list http://127.0.0.1:8000/mcp          # list tools
fastmcp call  http://127.0.0.1:8000/mcp web_search '{"query":"HTTP 418","count":2}'
```

**opencode** or Claude Desktop running on the same machine: same configs as §1.3, but use `http://127.0.0.1:8000/mcp` as the URL.

---

## 4. stdio (legacy / embedded use)

If a client spawns the server as a child process (the original `rust-agent` pattern), use stdio instead of HTTP:

```bash
DUCK_SEARCH_TRANSPORT=stdio python3 -m duck_search_mcp
```

or, after `pip install -e .`, the `duck-search-mcp` console script picks up the same env:

```bash
DUCK_SEARCH_TRANSPORT=stdio duck-search-mcp
```

Client config (opencode `mcp.toml`, Claude Desktop, etc.):

```toml
[[mcp.servers]]
name = "duck-search"
command = ["/abs/path/to/.venv/bin/python", "-m", "duck_search_mcp"]
env = { DUCK_SEARCH_TRANSPORT = "stdio" }
enabled = true
```

```json
{
  "mcpServers": {
    "duck-search": {
      "command": "/abs/path/to/.venv/bin/python",
      "args": ["-m", "duck_search_mcp"],
      "env": { "DUCK_SEARCH_TRANSPORT": "stdio" }
    }
  }
}
```

---

## 5. Hardening for non-loopback exposure

If you ever need to bind the server directly to `0.0.0.0` (e.g. behind a reverse proxy you control, not a tunnel), two things change:

1. **Enable Origin validation.** Without it, a browser visiting an attacker-controlled page can be made to talk to the server (DNS rebinding). Set `FASTMCP_HTTP_HOST_ORIGIN_PROTECTION=true` in the server's environment, or pass `http_host_origin_protection=True` if you wire the server in code.
2. **Add authentication.** The simplest option is `JWTVerifier` from `fastmcp.server.auth.providers.jwt`, configured for your IdP. See `gofastmcp.com/servers/auth/token-verification` for the full pattern.

For anything reachable from the public internet, **do both**. The current "no auth" stance is safe only because the server is bound to `127.0.0.1`.

---

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `Address already in use` on start | Port 8000 is taken | `DUCK_SEARCH_PORT=8123 python3 -m duck_search_mcp` and re-forward that port |
| `Connection refused` from the client | Server not running, or tunnel expired | Re-start the server; in VS Code, right-click the port row → **Restart Port Forwarding** |
| Client sees "no tools" | URL is wrong (e.g. `/` instead of `/mcp`) | The full path is `/mcp`; clients must include it |
| `400 -32020 HeaderMismatch` | Client is a legacy client speaking `2024-11-05` HTTP+SSE | Use a modern client (opencode, VS Code Copilot, Claude Desktop ≥ 2026); FastMCP 4 is dual-era but the old SSE transport is gone |
| `403` from a browser-based client | The forwarded URL is being treated as cross-origin | Use a non-browser MCP client; or set `FASTMCP_HTTP_HOST_ORIGIN_PROTECTION=true` and add the origin to `allowed_origins` |
| Empty results for an obviously entity-shaped query | DDG is throttling or has no entry for that exact topic | Rephrase, or wait an hour and try again. The cache may also be holding an old empty result — delete `DDG_CACHE_DIR` to invalidate. |
| Server logs are silent at INFO | `MCP_LOG_LEVEL=WARNING` (default) | Set `MCP_LOG_LEVEL=DEBUG` to see cache hits, rate-limit waits, and upstream call timing. |
