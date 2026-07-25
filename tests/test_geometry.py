from __future__ import annotations

from ezdxf_mcp.tools.documents import dxf_open_document
from ezdxf_mcp.tools.geometry import dxf_analyze_contours


def _open(name: str) -> str:
    return dxf_open_document(name)["data"]["doc_id"]


def test_gap_tolerance_regression() -> None:
    doc_id = _open("gap_002.dxf")
    assert dxf_analyze_contours(doc_id, gap_tol=0.01)["data"]["loop_count"] == 0
    assert dxf_analyze_contours(doc_id, gap_tol=0.05)["data"]["loop_count"] == 1


def test_disconnected_network_keeps_existing_loop() -> None:
    result = dxf_analyze_contours(_open("multi_rede.dxf"), gap_tol=0.05)["data"]
    assert result["network_count"] == 2
    assert result["loop_count"] >= 1
