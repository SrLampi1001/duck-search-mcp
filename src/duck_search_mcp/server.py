"""FastMCP server definition: tool + prompt registration.

Single `web_search` tool over the DuckDuckGo Instant Answer API, per
`docs/SPECS.md`. The server is dual-era (FastMCP 4 default) and serves both
stdio and Streamable HTTP depending on the chosen transport.

Application state (httpx client, on-disk cache, rate limiter) is owned by
the FastMCP `lifespan` context, so it's safely constructed at startup and
closed at shutdown. The tool reads it from `ctx.request_context.lifespan_context`.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .cache import DiskCache
from .ddg import EMPTY_NOTE, fetch_ddg, map_ddg_response
from .prompts import register_prompts
from .rate_limit import MinIntervalLimiter
from .settings import Settings, clamp_count, configure_logging

log = logging.getLogger(__name__)


INSTRUCTIONS = (
    "Free, unauthenticated web search via the DuckDuckGo Instant Answer API. "
    "One tool: web_search. One prompt: research_entity. "
    "Best for entity-shaped queries (people, places, products, standards, "
    "calculations). Returns short snippets; no page contents. Long-tail or "
    "question-shaped queries often return empty results — that's normal, not "
    "an error, and the tool returns a guidance note instead."
)


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncGenerator[dict, None]:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    cache = DiskCache(settings.cache_dir, settings.cache_ttl_secs)
    rate_limiter = MinIntervalLimiter(settings.min_interval_ms)
    log.info(
        "starting: transport-aware lifespan; cache=%s ttl=%ss interval=%sms timeout=%ss",
        settings.cache_dir, settings.cache_ttl_secs, settings.min_interval_ms, settings.http_timeout_s,
    )
    async with httpx.AsyncClient(
        headers={"User-Agent": "duck-search-mcp/0.1 (+https://github.com/)"},
        follow_redirects=True,
    ) as http_client:
        yield {
            "settings": settings,
            "cache": cache,
            "rate_limiter": rate_limiter,
            "http_client": http_client,
        }


mcp = FastMCP(
    name="duck-search-mcp",
    instructions=INSTRUCTIONS,
    cache_ttl=300,        # tool/prompt lists rarely change; safe to share publicly
    cache_scope="public",
    lifespan=lifespan,
)

register_prompts(mcp)


@mcp.custom_route(path="/health", methods=["GET"], name="health")
async def health(_: Request) -> Response:
    """Liveness probe.

    Returns 200 OK for any GET. Used by VS Code's port-forward tunnel and any
    external monitor. Does not exercise the cache or the upstream; a 200 only
    means the ASGI app is up and the lifespan has started.
    """
    return JSONResponse({"status": "ok"})


@mcp.tool(
    name="web_search",
    description=(
        "Free, unauthenticated web search via the DuckDuckGo Instant Answer API. "
        "Reach for this first for entity-like queries — people, places, products, "
        "standards, programming languages, calculations. Returns short snippets; "
        "no page contents. For long-tail or question-shaped queries the API often "
        "returns an empty response (that's a 200 with results: [] plus a guidance "
        "note, NOT an error); rephrase as a canonical topic name at most once, "
        "then fall back to your own knowledge. Use count to cap the result list "
        "(default 5, max 10)."
    ),
)
async def web_search(
    query: str = Field(
        description=(
            "The search query. Entity-shaped names work best: people, places, "
            "products, standards, programming languages, calculations."
        ),
        min_length=1,
    ),
    count: int = Field(
        default=5,
        description="Max results to return. Clamped to [1, 10].",
    ),
    ctx: Context | None = None,
) -> dict:
    """Search DuckDuckGo for an entity-shaped query and return structured snippets."""
    state = _state_from(ctx)
    cache: DiskCache = state["cache"]
    rate_limiter: MinIntervalLimiter = state["rate_limiter"]
    http_client: httpx.AsyncClient = state["http_client"]
    settings: Settings = state["settings"]

    echoed = query.strip()
    n = clamp_count(count)
    if not echoed:
        return {"query": "", "results": [], "source": "upstream", "note": EMPTY_NOTE}

    cached = cache.get(echoed)
    if cached is not None:
        results = cached.results[:n]
        return {
            "query": echoed,
            "results": results,
            "source": "cache",
            "note": EMPTY_NOTE if not results else "",
        }

    await rate_limiter.wait()

    try:
        payload = await fetch_ddg(echoed, client=http_client, timeout_s=settings.http_timeout_s)
    except httpx.HTTPStatusError as e:
        # Outbound DDG call goes through a direct httpx.AsyncClient (NOT FastMCP's
        # internal client), so catching httpx.HTTPStatusError is correct here.
        status = e.response.status_code
        log.warning("ddg: upstream HTTP %s for %r", status, echoed)
        raise ToolError(f"Upstream HTTP {status}: {e.response.reason_phrase}") from e
    except httpx.HTTPError as e:
        # Same reasoning as above; this is a direct httpx call to the DDG endpoint.
        log.warning("ddg: upstream transport error for %r: %s", echoed, e)
        raise ToolError(f"Upstream transport error: {e.__class__.__name__}: {e}") from e

    results = map_ddg_response(payload)
    cache.set(echoed, results)

    return {
        "query": echoed,
        "results": results[:n],
        "source": "upstream",
        "note": "" if results else EMPTY_NOTE,
    }


def _state_from(ctx: Context | None) -> dict:
    if ctx is None or ctx.request_context is None:
        raise RuntimeError("web_search called without a request context")
    lifespan_state = ctx.request_context.lifespan_context
    if not lifespan_state:
        raise RuntimeError("server lifespan did not initialise state")
    return lifespan_state
