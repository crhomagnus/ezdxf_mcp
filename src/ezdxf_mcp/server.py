"""stdio MCP entry point."""

from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP

from .config import settings
from .tools import register_all
from .validation import ensure_workspace

logging.basicConfig(
    stream=sys.stderr,
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

mcp = FastMCP(
    "ezdxf_mcp",
    instructions=(
        "Inspect, validate, normalize, convert, render, and create DXF documents. "
        "Writes are confined to EZDXF_MCP_WORKSPACE and never overwrite by default."
    ),
)
register_all(mcp)


def main() -> None:
    ensure_workspace()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
