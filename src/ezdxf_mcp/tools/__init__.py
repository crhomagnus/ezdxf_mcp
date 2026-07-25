"""Register the complete v3 tool catalog."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_all(mcp: FastMCP) -> None:
    from . import (
        create,
        customdata,
        documents,
        export,
        geometry,
        graphics,
        image,
        lexical,
        render,
        semantics,
        structure,
        text,
        units,
        xrefs,
    )

    for module in (
        documents,
        lexical,
        structure,
        semantics,
        xrefs,
        graphics,
        customdata,
        units,
        geometry,
        image,
        text,
        render,
        export,
        create,
    ):
        module.register_tools(mcp)
