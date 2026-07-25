from __future__ import annotations

from ezdxf_mcp.tools.documents import dxf_open_document
from ezdxf_mcp.tools.graphics import dxf_list_layers
from ezdxf_mcp.tools.semantics import dxf_list_entities


def _open() -> str:
    return dxf_open_document("camadas_ocultas.dxf")["data"]["doc_id"]


def test_hidden_layers_are_respected() -> None:
    doc_id = _open()
    all_entities = dxf_list_entities(doc_id, respect_layer_state=False)["data"]
    visible = dxf_list_entities(doc_id, respect_layer_state=True)["data"]
    assert all_entities["total"] == 3
    assert visible["total"] == 1
    assert visible["items"][0]["layer"] == "CORTE"


def test_referenced_layer_without_table_entry() -> None:
    rows = dxf_list_layers(_open())["data"]["layers"]
    corte = next(row for row in rows if row["name"] == "CORTE")
    assert corte["has_table_entry"] is False
