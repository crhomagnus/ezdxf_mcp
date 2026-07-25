from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


@pytest.mark.asyncio
async def test_every_registered_tool_has_successful_runtime_evidence(workspace: Path) -> None:
    """Exercise every catalog entry through FastMCP, not by direct Python calls."""
    from ezdxf_mcp.server import mcp
    from ezdxf_mcp.session import store

    invoked: set[str] = set()

    async def call(tool_name: str, **arguments: Any) -> dict[str, Any]:
        result = await mcp.call_tool(tool_name, arguments)
        invoked.add(tool_name)
        assert isinstance(result, tuple)
        structured = result[1]
        assert isinstance(structured, dict)
        assert structured["_runtime"]["status"] == "success"
        assert structured["_runtime"]["tool"] == tool_name
        return structured

    for output in workspace.glob("smoke_*"):
        output.unlink()

    image_conversion = await call(
        "dxf_image_to_dxf",
        image_path="componentes.png",
        output_path="smoke_image.dxf",
        width_mm=200,
        ocr_page_segmentation_mode=11,
        ocr_min_confidence=35,
        overwrite=True,
    )
    await call(
        "dxf_recognize_components",
        doc_id=image_conversion["data"]["doc_id"],
        max_relationships=100,
    )

    opened = await call("dxf_open_document", path="custom_data.dxf")
    doc_id = opened["data"]["doc_id"]
    fresh = await call("dxf_new_document", version="R2018")
    fresh_id = fresh["data"]["doc_id"]
    await call("dxf_list_documents")
    await call("dxf_set_option", name="load_proxy_graphics", value=True)

    session = store.get(doc_id)
    doc = session.doc
    msp = doc.modelspace()
    source_line = next(iter(msp.query("LINE")))
    line = msp.add_line((0, 0, 0), (10, 0, 0))
    circle = msp.add_circle((5, 5), 2)
    msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True)
    mtext = msp.add_mtext(r"{\C1;Red}\P\H2x;Tall\S1/2;")
    block = doc.blocks.new("PART")
    block.add_line((0, 0), (1, 0))
    block.add_attdef("CODE", (0, 0), text="X")
    insert = msp.add_blockref("PART", (20, 0))
    insert.add_auto_attribs({"CODE": "A"})

    await call("dxf_inspect_encoding", doc_id=doc_id)
    await call("dxf_find_encoding_issues", doc_id=doc_id)
    await call("dxf_check_string_limits", doc_id=doc_id)
    await call("dxf_dump_tags", doc_id=doc_id, handle=line.dxf.handle)
    await call("dxf_explain_group_code", code=360)
    await call("dxf_read_comments", path="r2000.dxf")
    await call(
        "dxf_strip_file",
        path="r2000.dxf",
        output_path="smoke_stripped.dxf",
        overwrite=True,
    )
    await call("dxf_detect_format", path="smoke_stripped.dxf")

    await call("dxf_audit", doc_id=doc_id)
    await call("dxf_validate_structure", doc_id=doc_id)
    await call("dxf_map_sections", doc_id=doc_id)
    await call("dxf_inspect_header", doc_id=doc_id)
    await call("dxf_set_header_var", doc_id=doc_id, name="$LTSCALE", value=1.25)
    await call("dxf_list_tables", doc_id=doc_id)
    await call("dxf_inspect_classes", doc_id=doc_id)
    await call("dxf_trace_handle", doc_id=doc_id, handle=line.dxf.handle)
    await call("dxf_find_dangling_handles", doc_id=doc_id)
    await call("dxf_analyze_ownership", doc_id=doc_id)
    await call("dxf_check_purge_safety", doc_id=doc_id, handle=line.dxf.handle)
    await call("dxf_purge_unused", doc_id=doc_id, dry_run=True)
    await call("dxf_inspect_entitydb", doc_id=doc_id)
    await call("dxf_check_name_conformance", doc_id=doc_id)

    await call("dxf_inspect_document", doc_id=doc_id)
    await call("dxf_list_entities", doc_id=doc_id)
    await call("dxf_query", doc_id=doc_id, query="LINE")
    await call("dxf_get_entity", doc_id=doc_id, handle=line.dxf.handle)
    await call("dxf_groupby", doc_id=doc_id, dxfattrib="layer")
    await call("dxf_list_layouts", doc_id=doc_id)
    await call("dxf_list_blocks", doc_id=doc_id)
    await call("dxf_list_block_refs", doc_id=doc_id)
    await call("dxf_find_unreferenced_blocks", doc_id=doc_id)
    await call("dxf_create_block", doc_id=doc_id, name="SMOKE_BLOCK")
    inserted = await call(
        "dxf_insert_block",
        doc_id=doc_id,
        block_name="PART",
        insert=[30, 0, 0],
        attribs={"CODE": "B"},
    )
    inserted_handle = inserted["data"]["handle"]
    await call(
        "dxf_manage_attribs",
        doc_id=doc_id,
        insert_handle=inserted_handle,
        action="list",
    )
    await call(
        "dxf_manage_paperspace",
        doc_id=doc_id,
        action="create",
        name="SmokeLayout",
    )

    await call(
        "dxf_import_from",
        doc_id=doc_id,
        source_path="xref_source.dxf",
        mode="modelspace",
    )
    await call(
        "dxf_manage_xref",
        doc_id=doc_id,
        action="define",
        block_name="SMOKE_XREF",
        filename="xref_source.dxf",
    )
    await call("dxf_inspect_xref", path="xref_source.dxf")
    await call(
        "dxf_manage_xclip",
        doc_id=doc_id,
        insert_handle=insert.dxf.handle,
        action="set",
        vertices=[[0, 0], [1, 0], [1, 1], [0, 1]],
    )
    await call(
        "dxf_manage_groups",
        doc_id=doc_id,
        action="create",
        name="SMOKE_GROUP",
        handles=[line.dxf.handle],
    )

    await call("dxf_list_layers", doc_id=doc_id)
    await call("dxf_manage_layer", doc_id=doc_id, action="create", name="SMOKE_LAYER")
    await call(
        "dxf_organize_layers",
        doc_id=doc_id,
        target_layer="ORGANIZED",
        query="LINE",
    )
    await call(
        "dxf_manage_linetype",
        doc_id=doc_id,
        action="create",
        name="SMOKE_DASH",
        pattern=[0.2, 0.1, -0.1],
    )
    await call(
        "dxf_manage_textstyle",
        doc_id=doc_id,
        action="create",
        name="SmokeStyle",
        font="DejaVuSans.ttf",
    )
    await call(
        "dxf_manage_dimstyle",
        doc_id=doc_id,
        action="inspect",
        name="Standard",
    )
    await call("dxf_manage_appid", doc_id=doc_id, action="create", name="SMOKEAPP")
    await call(
        "dxf_set_entity_attribs",
        doc_id=doc_id,
        handles=[circle.dxf.handle],
        attributes={"layer": "0", "color": 2},
    )
    await call("dxf_analyze_formatting", doc_id=doc_id)
    await call("dxf_convert_colors", mode="aci_to_rgb", value=2)
    await call(
        "dxf_manage_plotstyles",
        action="create",
        path="smoke_plot.ctb",
        kind="ctb",
        overwrite=True,
    )
    await call(
        "dxf_set_app_settings",
        doc_id=doc_id,
        current_layer="0",
        update_extents=True,
    )
    await call(
        "dxf_delete_layer",
        doc_id=doc_id,
        name="SMOKE_LAYER",
        delete_entities=False,
    )

    await call("dxf_inventory_custom_data", doc_id=doc_id)
    await call(
        "dxf_get_xdata",
        doc_id=doc_id,
        handle=source_line.dxf.handle,
        appid="THIRD_PARTY",
    )
    await call(
        "dxf_set_xdata",
        doc_id=doc_id,
        handle=source_line.dxf.handle,
        appid="SMOKE_XDATA",
        tags=[[1000, "payload"], [1070, 7]],
    )
    await call(
        "dxf_get_extension_dict",
        doc_id=doc_id,
        handle=source_line.dxf.handle,
    )
    await call(
        "dxf_manage_xrecord",
        doc_id=doc_id,
        handle=source_line.dxf.handle,
        name="SMOKE_RECORD",
        action="set",
        data=["value", 42],
    )
    await call(
        "dxf_manage_appdata",
        doc_id=doc_id,
        handle=source_line.dxf.handle,
        appid="SMOKE_APPDATA",
        action="set",
        tags=[[1, "value"]],
    )
    await call(
        "dxf_manage_reactors",
        doc_id=doc_id,
        handle=source_line.dxf.handle,
        action="get",
    )

    await call("dxf_inspect_units", doc_id=doc_id)
    await call("dxf_set_units", doc_id=doc_id, unit=4)
    await call("dxf_check_block_scale", doc_id=doc_id)
    await call("dxf_check_version_compat", doc_id=doc_id, target_version="R12")
    await call("dxf_check_r12_compat", doc_id=doc_id)
    await call("dxf_check_acad_compat", doc_id=doc_id)
    await call("dxf_convert_units", doc_id=doc_id, target_unit=5)

    await call("dxf_analyze_contours", doc_id=doc_id, gap_tol=0.05)
    await call("dxf_sweep_tolerance", doc_id=doc_id, tolerances=[0.01, 0.05])
    await call("dxf_find_duplicates", doc_id=doc_id)
    await call("dxf_check_2d_purity", doc_id=doc_id)
    await call("dxf_measure_extents", doc_id=doc_id)
    await call("dxf_measure_geometry", doc_id=doc_id)
    await call("dxf_normalize_extrusions", doc_id=doc_id)
    await call("dxf_flatten_to_2d", doc_id=doc_id, handles=[line.dxf.handle])
    await call("dxf_disassemble", doc_id=doc_id)
    await call("dxf_close_contours", doc_id=doc_id, max_gap=0.01)
    await call(
        "dxf_transform",
        doc_id=doc_id,
        handles=[line.dxf.handle],
        translate=[1, 1, 0],
    )
    await call(
        "dxf_convert_to_path",
        doc_id=doc_id,
        handles=[circle.dxf.handle],
    )
    await call(
        "dxf_offset_contour",
        doc_id=doc_id,
        vertices=[[0, 0], [10, 0], [10, 10], [0, 10]],
        offset=1.0,
    )
    await call(
        "dxf_boolean_2d",
        doc_id=doc_id,
        operation="intersection",
        polygon_a=[[0, 0], [10, 0], [10, 10], [0, 10]],
        polygon_b=[[5, 5], [15, 5], [15, 15], [5, 15]],
    )
    await call(
        "dxf_fillet_corners",
        doc_id=doc_id,
        points=[[0, 0], [10, 0], [10, 10], [0, 10]],
        radius=1.0,
    )
    await call(
        "dxf_chamfer_corners",
        doc_id=doc_id,
        points=[[0, 0], [10, 0], [10, 10], [0, 10]],
        length=1.0,
    )
    await call(
        "dxf_select_spatial",
        doc_id=doc_id,
        mode="overlap",
        shape="window",
        points=[[-100, -100], [100, 100]],
    )
    await call(
        "dxf_explode_blocks",
        doc_id=doc_id,
        insert_handles=[inserted_handle],
    )

    await call("dxf_extract_text", doc_id=doc_id)
    await call(
        "dxf_inspect_mtext_formatting",
        doc_id=doc_id,
        handle=mtext.dxf.handle,
    )
    added_text = await call(
        "dxf_add_text",
        doc_id=doc_id,
        text="Smoke",
        insert=[0, 20, 0],
        kind="TEXT",
    )
    await call(
        "dxf_explode_mtext",
        doc_id=doc_id,
        handles=[mtext.dxf.handle],
        destroy=False,
    )
    await call(
        "dxf_text_to_contour",
        doc_id=doc_id,
        handles=[added_text["data"]["handle"]],
    )
    await call("dxf_manage_fonts", doc_id=doc_id, action="list_styles")

    await call("dxf_configure_render", doc_id=doc_id, color_policy="COLOR")
    await call(
        "dxf_render_svg",
        doc_id=doc_id,
        output_path="smoke_render.svg",
        overwrite=True,
    )
    await call(
        "dxf_render_png",
        doc_id=doc_id,
        output_path="smoke_render.png",
        overwrite=True,
    )
    await call(
        "dxf_render_pdf",
        doc_id=doc_id,
        output_path="smoke_render.pdf",
        overwrite=True,
    )
    await call(
        "dxf_render_json",
        doc_id=doc_id,
        output_path="smoke_render.json",
        overwrite=True,
    )
    await call("dxf_zoom_extents", doc_id=doc_id)

    await call(
        "dxf_add_entities",
        doc_id=doc_id,
        entities=[{"type": "POINT", "location": [0, 0, 0]}],
    )
    await call("dxf_add_form", doc_id=doc_id, form="cube")
    await call(
        "dxf_add_path_shape",
        doc_id=doc_id,
        shape="star",
        parameters={"count": 5, "inner_radius": 2, "outer_radius": 4},
    )
    await call(
        "dxf_add_dimension",
        doc_id=doc_id,
        kind="linear",
        parameters={"base": [0, 15], "p1": [0, 0], "p2": [10, 0]},
    )
    await call(
        "dxf_add_hatch",
        doc_id=doc_id,
        boundaries=[
            {
                "type": "polyline",
                "vertices": [[0, 0], [2, 0], [2, 2], [0, 2]],
                "closed": True,
            }
        ],
    )

    await call(
        "dxf_save_as",
        doc_id=doc_id,
        output_path="smoke_saveas.dxf",
        overwrite=True,
    )
    await call(
        "dxf_export_r12_strict",
        doc_id=doc_id,
        output_path="smoke_r12.dxf",
        overwrite=True,
    )
    await call(
        "dxf_export_json_tags",
        doc_id=doc_id,
        output_path="smoke_tags.json",
        overwrite=True,
    )
    mesh_opened = await call("dxf_open_document", path="mesh.dxf")
    mesh_id = mesh_opened["data"]["doc_id"]
    await call(
        "dxf_export_mesh",
        doc_id=mesh_id,
        output_path="smoke_mesh.stl",
        format="stl",
        overwrite=True,
    )
    await call(
        "dxf_generate_code",
        doc_id=doc_id,
        output_path="smoke_generated.py",
        handles=[line.dxf.handle],
        overwrite=True,
    )
    await call(
        "dxf_export_binary",
        doc_id=doc_id,
        output_path="smoke_binary.dxf",
        overwrite=True,
    )
    await call(
        "dxf_export_zip",
        doc_id=doc_id,
        output_path="smoke_export.zip",
        overwrite=True,
    )
    await call("dxf_save", doc_id=doc_id, overwrite=True)

    await call("dxf_close_document", doc_id=mesh_id)
    await call("dxf_close_document", doc_id=fresh_id)
    await call("dxf_close_document", doc_id=doc_id)

    tools = await mcp.list_tools()
    registered = {tool.name for tool in tools}
    assert invoked == registered
