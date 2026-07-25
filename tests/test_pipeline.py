from __future__ import annotations

from pathlib import Path

from ezdxf_mcp.tools.documents import dxf_open_document
from ezdxf_mcp.tools.export import dxf_export_r12_strict
from ezdxf_mcp.tools.graphics import dxf_analyze_formatting
from ezdxf_mcp.tools.lexical import dxf_inspect_encoding
from ezdxf_mcp.tools.render import dxf_render_svg
from ezdxf_mcp.tools.structure import dxf_audit, dxf_validate_structure


def test_reference_pipeline(workspace: Path) -> None:
    doc_id = dxf_open_document("formatting.dxf")["data"]["doc_id"]
    assert dxf_inspect_encoding(doc_id)["data"]["dxfversion"] == "AC1032"
    assert dxf_audit(doc_id)["data"]["error_count"] == 0
    assert dxf_validate_structure(doc_id)["data"]["valid"] is True
    assert dxf_analyze_formatting(doc_id)["data"]["attribute_modes"]
    r12 = workspace / "pipeline_r12.dxf"
    svg = workspace / "pipeline.svg"
    r12.unlink(missing_ok=True)
    svg.unlink(missing_ok=True)
    dxf_export_r12_strict(doc_id, r12.name)
    dxf_render_svg(doc_id, svg.name)
    assert r12.stat().st_size > 0
    assert svg.stat().st_size > 0
