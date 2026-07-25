# MCP/API Tool Catalog v3.2

The FastMCP server advertises **117 unique tools**. Every tool is called by
`tests/test_runtime_catalog.py`, which requires a structured response and
`_runtime.status == "success"`.

## Documents — 5

`dxf_open_document`, `dxf_new_document`, `dxf_close_document`,
`dxf_list_documents`, `dxf_set_option`.

## Lexical inspection — 8

`dxf_inspect_encoding`, `dxf_find_encoding_issues`,
`dxf_check_string_limits`, `dxf_dump_tags`, `dxf_explain_group_code`,
`dxf_read_comments`, `dxf_detect_format`, `dxf_strip_file`.

## Structure and integrity — 14

`dxf_audit`, `dxf_validate_structure`, `dxf_map_sections`,
`dxf_inspect_header`, `dxf_set_header_var`, `dxf_list_tables`,
`dxf_inspect_classes`, `dxf_trace_handle`, `dxf_find_dangling_handles`,
`dxf_analyze_ownership`, `dxf_check_purge_safety`, `dxf_purge_unused`,
`dxf_inspect_entitydb`, `dxf_check_name_conformance`.

## Semantics, layouts, and blocks — 13

`dxf_inspect_document`, `dxf_list_entities`, `dxf_query`, `dxf_get_entity`,
`dxf_groupby`, `dxf_list_layouts`, `dxf_list_blocks`,
`dxf_list_block_refs`, `dxf_find_unreferenced_blocks`, `dxf_create_block`,
`dxf_insert_block`, `dxf_manage_attribs`, `dxf_manage_paperspace`.

## XREF, import, and groups — 5

`dxf_import_from`, `dxf_manage_xref`, `dxf_inspect_xref`,
`dxf_manage_xclip`, `dxf_manage_groups`.

## Graphic formatting — 13

`dxf_list_layers`, `dxf_manage_layer`, `dxf_delete_layer`,
`dxf_organize_layers`, `dxf_manage_linetype`, `dxf_manage_textstyle`,
`dxf_manage_dimstyle`, `dxf_manage_appid`, `dxf_set_entity_attribs`,
`dxf_analyze_formatting`, `dxf_convert_colors`, `dxf_manage_plotstyles`,
`dxf_set_app_settings`.

## Custom data — 7

`dxf_inventory_custom_data`, `dxf_get_xdata`, `dxf_set_xdata`,
`dxf_get_extension_dict`, `dxf_manage_xrecord`, `dxf_manage_appdata`,
`dxf_manage_reactors`.

## Units and versions — 7

`dxf_inspect_units`, `dxf_set_units`, `dxf_convert_units`,
`dxf_check_block_scale`, `dxf_check_version_compat`,
`dxf_check_r12_compat`, `dxf_check_acad_compat`.

## Geometry — 18

`dxf_analyze_contours`, `dxf_sweep_tolerance`, `dxf_find_duplicates`,
`dxf_check_2d_purity`, `dxf_measure_extents`, `dxf_measure_geometry`,
`dxf_normalize_extrusions`, `dxf_flatten_to_2d`, `dxf_disassemble`,
`dxf_close_contours`, `dxf_transform`, `dxf_convert_to_path`,
`dxf_offset_contour`, `dxf_boolean_2d`, `dxf_fillet_corners`,
`dxf_chamfer_corners`, `dxf_explode_blocks`, `dxf_select_spatial`.

## Text and fonts — 6

`dxf_add_text`, `dxf_extract_text`, `dxf_inspect_mtext_formatting`,
`dxf_explode_mtext`, `dxf_text_to_contour`, `dxf_manage_fonts`.

## Image, OCR, and spatial recognition — 2

`dxf_image_to_dxf`, `dxf_recognize_components`.

## Render — 6

`dxf_render_svg`, `dxf_render_png`, `dxf_render_pdf`,
`dxf_render_json`, `dxf_configure_render`, `dxf_zoom_extents`.

## Export — 8

`dxf_save`, `dxf_save_as`, `dxf_export_r12_strict`,
`dxf_export_json_tags`, `dxf_export_mesh`, `dxf_generate_code`,
`dxf_export_binary`, `dxf_export_zip`.

## Creation — 5

`dxf_add_entities`, `dxf_add_form`, `dxf_add_path_shape`,
`dxf_add_dimension`, `dxf_add_hatch`.

## PRD count reconciliation

The PRD definition of done mentions 92 tools, but extracting its concrete
`dxf_*` identifiers produces 115 unique names plus one conceptual wildcard
item for spatial selection. The wildcard is implemented as
`dxf_select_spatial`; none of the 115 concrete names were removed. The two
image/DXF tools were added after the PRD, producing the advertised total of
117.

## Rotas HTTP próprias — não contam como ferramentas MCP

- `GET /health`;
- `POST /v1/convert`;
- `GET /v1/jobs/{job_id}`;
- `GET /v1/jobs/{job_id}/components`;
- `GET /v1/jobs/{job_id}/drawing.dxf`;
- `POST /v1/jobs/{job_id}/cursor/plan`;
- `POST /v1/jobs/{job_id}/cursor/move`.

A ponte local separada expõe somente `GET /health` e
`POST /v1/cursor/move`, ambos em loopback.
