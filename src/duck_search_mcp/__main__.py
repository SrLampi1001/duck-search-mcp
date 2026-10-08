"""Entry point: `python -m duck_search_mcp` and the `duck-search-mcp` script."""
from __future__ import annotations

import logging

from .server import mcp
from .settings import Settings, configure_logging

log = logging.getLogger(__name__)


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    if settings.transport == "stdio":
        log.info("starting stdio transport")
        mcp.run(transport="stdio")
        return
    log.info("starting Streamable HTTP on http://%s:%d%s", settings.host, settings.port, settings.path)
    mcp.run(transport="http", host=settings.host, port=settings.port, path=settings.path)


if __name__ == "__main__":
    main()
