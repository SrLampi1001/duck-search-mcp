"""Environment-driven configuration for the server.

Single source of truth for defaults and env-var parsing. All settings are
read at process start; nothing here mutates global state.
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return default if raw is None or raw == "" else raw


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ValueError(f"{name} must be an integer; got {raw!r}") from e


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as e:
        raise ValueError(f"{name} must be a float; got {raw!r}") from e


def _resolve_log_level() -> int:
    raw = _env_str("MCP_LOG_LEVEL", _env_str("FASTMCP_LOG_LEVEL", "WARNING")).upper()
    mapping = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    if raw not in mapping:
        raise ValueError(f"MCP_LOG_LEVEL must be one of {sorted(mapping)}; got {raw!r}")
    return mapping[raw]


@dataclass(frozen=True)
class Settings:
    transport: str
    host: str
    port: int
    path: str
    cache_dir: Path
    cache_ttl_secs: int
    min_interval_ms: int
    http_timeout_s: float
    log_level: int

    @classmethod
    def from_env(cls) -> "Settings":
        transport = _env_str("DUCK_SEARCH_TRANSPORT", "http").lower()
        if transport not in {"http", "stdio"}:
            raise ValueError(f"DUCK_SEARCH_TRANSPORT must be 'http' or 'stdio'; got {transport!r}")
        return cls(
            transport=transport,
            host=_env_str("DUCK_SEARCH_HOST", "127.0.0.1"),
            port=_env_int("DUCK_SEARCH_PORT", 8000),
            path=_env_str("DUCK_SEARCH_PATH", "/mcp"),
            cache_dir=Path(_env_str("DDG_CACHE_DIR", "./cache/ddg")).expanduser().resolve(),
            cache_ttl_secs=_env_int("DDG_CACHE_TTL_SECS", 86400),
            min_interval_ms=_env_int("DDG_MIN_INTERVAL_MS", 1100),
            http_timeout_s=_env_float("DDG_HTTP_TIMEOUT_S", 10.0),
            log_level=_resolve_log_level(),
        )


def configure_logging(level: int) -> None:
    """Logs go to stderr; stdout is the JSON-RPC stream."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )


def clamp_count(value: int | None) -> int:
    if value is None:
        return 5
    return max(1, min(10, int(value)))
