from __future__ import annotations

import os
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.asyncio
async def test_real_stdio_handshake_catalog_and_tool_call(workspace: Path) -> None:
    """Validate the packaged executable over the actual MCP stdio transport."""
    executable = Path(__file__).parents[1] / ".venv" / "bin" / "ezdxf-mcp"
    parameters = StdioServerParameters(
        command=str(executable),
        env={**os.environ, "EZDXF_MCP_WORKSPACE": str(workspace)},
    )

    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as session:
            initialized = await session.initialize()
            assert initialized.serverInfo.name == "ezdxf_mcp"

            catalog = await session.list_tools()
            assert len(catalog.tools) == 117
            assert len({tool.name for tool in catalog.tools}) == 117

            result = await session.call_tool(
                "dxf_detect_format",
                {"path": "r2000.dxf"},
            )
            assert result.isError is False
            assert result.structuredContent is not None
            assert result.structuredContent["_runtime"]["status"] == "success"
