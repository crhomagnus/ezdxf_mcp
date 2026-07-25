from __future__ import annotations

from ezdxf_mcp.tools.documents import dxf_open_document


def test_corrupt_document_falls_back_to_recover() -> None:
    result = dxf_open_document("corrompido.dxf", mode="auto")["data"]
    assert result["loaded_with"] == "recover"
    assert result["recovered"] is True
