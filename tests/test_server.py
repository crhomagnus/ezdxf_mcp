from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_catalog_has_117_unique_tools() -> None:
    from ezdxf_mcp.server import mcp

    tools = await mcp.list_tools()
    names = [tool.name for tool in tools]
    assert len(names) == 117
    assert len(names) == len(set(names))
    assert all(tool.description for tool in tools)
    assert all(tool.annotations.openWorldHint is False for tool in tools)
