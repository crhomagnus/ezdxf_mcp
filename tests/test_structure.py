from __future__ import annotations

from ezdxf_mcp.tools.documents import dxf_open_document
from ezdxf_mcp.tools.structure import (
    dxf_audit,
    dxf_find_dangling_handles,
    dxf_validate_structure,
    reference_semantics,
)


def _open(name: str) -> str:
    return dxf_open_document(name)["data"]["doc_id"]


def test_five_reference_ranges() -> None:
    assert reference_semantics(320)["kind"] == "arbitrary"
    assert reference_semantics(330)["kind"] == "soft_pointer"
    assert reference_semantics(340)["kind"] == "hard_pointer"
    assert reference_semantics(350)["kind"] == "soft_owner"
    assert reference_semantics(360)["kind"] == "hard_owner"
    assert reference_semantics(1005)["kind"] == "xdata_soft_pointer"


def test_audit_detects_block_cycle_104() -> None:
    result = dxf_audit(_open("ciclo_blocos.dxf"))["data"]
    assert 104 in {row["code"] for row in result["errors"]["items"]}


def test_loaded_case_collision_is_reported() -> None:
    result = dxf_validate_structure(_open("nome_colidente.dxf"))["data"]
    assert any(item["check"] == "name_collision" for item in result["findings"])


def test_xdata_soft_pointer_dangling_handle_is_reported() -> None:
    result = dxf_find_dangling_handles(_open("custom_data.dxf"))["data"]
    finding = next(item for item in result["items"] if item["target"] == "FFFF")
    assert finding["code"] == 1005
    assert finding["kind"] == "xdata_soft_pointer"
