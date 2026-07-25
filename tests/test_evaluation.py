from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from ezdxf_mcp.session import store
from ezdxf_mcp.tools.customdata import dxf_inventory_custom_data
from ezdxf_mcp.tools.documents import dxf_open_document
from ezdxf_mcp.tools.graphics import dxf_list_layers
from ezdxf_mcp.tools.lexical import dxf_explain_group_code, dxf_inspect_encoding
from ezdxf_mcp.tools.semantics import dxf_list_entities
from ezdxf_mcp.tools.structure import (
    dxf_audit,
    dxf_find_dangling_handles,
    dxf_trace_handle,
    dxf_validate_structure,
)
from ezdxf_mcp.tools.units import dxf_check_version_compat


def _open(name: str) -> str:
    return dxf_open_document(name)["data"]["doc_id"]


def test_ten_read_only_evaluation_questions_have_verified_answers() -> None:
    evaluation = Path(__file__).parents[1] / "evals" / "evaluation.xml"
    questions = ElementTree.parse(evaluation).getroot().findall("question")
    assert len(questions) == 10
    assert len({question.attrib["id"] for question in questions}) == 10

    r2000 = dxf_inspect_encoding(_open("r2000.dxf"))["data"]
    r2007 = dxf_inspect_encoding(_open("r2007.dxf"))["data"]
    assert (r2000["output_encoding"], r2007["output_encoding"]) == ("cp1252", "utf-8")

    code_360 = dxf_explain_group_code(360)["data"]["reference"]
    assert code_360["kind"] == "hard_owner"
    assert code_360["protects_from_purge"] is True

    custom_id = _open("custom_data.dxf")
    line = next(iter(store.get(custom_id).doc.modelspace().query("LINE")))
    record = line.get_extension_dict()["CONFIG"]
    traced = dxf_trace_handle(custom_id, record.dxf.handle)["data"]
    assert traced["incoming_references"][0]["code"] == 350
    assert traced["incoming_references"][0]["kind"] == "soft_owner"

    dangling = dxf_find_dangling_handles(custom_id)["data"]
    assert any(
        item["target"] == "FFFF" and item["kind"] == "xdata_soft_pointer"
        for item in dangling["items"]
    )

    cycle = dxf_audit(_open("ciclo_blocos.dxf"))["data"]
    assert any(item["code"] == 104 for item in cycle["errors"]["items"])

    collision = dxf_validate_structure(_open("nome_colidente.dxf"))["data"]
    assert any(item["check"] == "name_collision" for item in collision["findings"])

    layers_id = _open("camadas_ocultas.dxf")
    layers = dxf_list_layers(layers_id)["data"]["layers"]
    assert any(row["name"] == "CORTE" and not row["has_table_entry"] for row in layers)

    all_entities = dxf_list_entities(layers_id, respect_layer_state=False)["data"]
    visible_entities = dxf_list_entities(layers_id, respect_layer_state=True)["data"]
    assert (all_entities["total"], visible_entities["total"]) == (3, 1)

    degradation = dxf_check_version_compat(_open("mesh.dxf"), "R12")["data"]
    assert degradation["compatible_without_degradation"] is False
    assert any(item["type"] == "MESH" for item in degradation["findings"])

    custom_data = dxf_inventory_custom_data(custom_id)["data"]
    assert custom_data["xdata_by_appid"]["THIRD_PARTY"] == 1
    assert custom_data["xrecords"] == 1
