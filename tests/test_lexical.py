from __future__ import annotations

from ezdxf_mcp.tools.documents import dxf_open_document
from ezdxf_mcp.tools.lexical import (
    dxf_dump_tags,
    dxf_explain_group_code,
    dxf_inspect_encoding,
)


def _open(name: str) -> str:
    return dxf_open_document(name)["data"]["doc_id"]


def test_r2000_vs_r2007_output_encoding() -> None:
    r2000 = dxf_inspect_encoding(_open("r2000.dxf"))["data"]
    r2007 = dxf_inspect_encoding(_open("r2007.dxf"))["data"]
    assert r2000["output_encoding"].lower() == "cp1252"
    assert r2007["output_encoding"].lower() == "utf-8"


def test_group_code_reference_semantics() -> None:
    arbitrary = dxf_explain_group_code(320)["data"]["reference"]
    hard_owner = dxf_explain_group_code(360)["data"]["reference"]
    assert arbitrary["translated_in_insert_xref"] is False
    assert hard_owner["protects_from_purge"] is True


def test_dump_tags_has_type() -> None:
    result = dxf_dump_tags(_open("r2007.dxf"), limit=10)["data"]
    assert result["items"]
    assert {"code", "type", "value"} <= result["items"][0].keys()
