"""Entity, block, layout, and semantic document tools."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ezdxf import blkrefs, groupby
from ezdxf.entities import DXFEntity, Insert
from ezdxf.math import Vec3
from mcp.server.fastmcp import FastMCP

from ..formatting import json_safe, paginate, response
from ..layers import iter_entities
from ..registry import register
from ..session import DocumentSession, store


def _layout(session: DocumentSession, name: str | None):
    if name in {None, "", "Model", "Modelspace"}:
        return session.doc.modelspace()
    return session.doc.layouts.get(name)


def _entity_row(entity: DXFEntity) -> dict[str, Any]:
    return {
        "handle": entity.dxf.get("handle"),
        "type": entity.dxftype(),
        "owner": entity.dxf.get("owner"),
        "layer": entity.dxf.get("layer"),
        "attributes": json_safe(entity.dxfattribs()),
    }


def _add_entity(layout, spec: dict[str, Any]) -> DXFEntity:
    entity_type = str(spec.get("type", "")).upper()
    attrs = dict(spec.get("dxfattribs", {}))
    if entity_type == "LINE":
        return layout.add_line(spec["start"], spec["end"], dxfattribs=attrs)
    if entity_type == "CIRCLE":
        return layout.add_circle(spec["center"], float(spec["radius"]), dxfattribs=attrs)
    if entity_type == "ARC":
        return layout.add_arc(
            spec["center"],
            float(spec["radius"]),
            float(spec["start_angle"]),
            float(spec["end_angle"]),
            dxfattribs=attrs,
        )
    if entity_type == "LWPOLYLINE":
        return layout.add_lwpolyline(
            spec["points"], format=spec.get("format", "xy"), dxfattribs=attrs
        )
    if entity_type == "POINT":
        return layout.add_point(spec["location"], dxfattribs=attrs)
    if entity_type == "TEXT":
        return layout.add_text(spec["text"], dxfattribs=attrs).set_placement(spec["insert"])
    raise ValueError(f"unsupported entity type in this operation: {entity_type}")


def dxf_inspect_document(doc_id: str, response_format: str = "json") -> dict[str, Any]:
    """Return an ezdxf-info style semantic overview."""
    session = store.get(doc_id)
    doc = session.doc
    by_type = Counter(entity.dxftype() for entity in doc.entitydb.values() if entity.is_alive)
    return response(
        {
            **session.summary(),
            "entities_in_modelspace": len(doc.modelspace()),
            "layouts": doc.layouts.names_in_taborder(),
            "blocks": len(doc.blocks),
            "layers": len(doc.layers),
            "linetypes": len(doc.linetypes),
            "styles": len(doc.styles),
            "entitydb": len(doc.entitydb),
            "types": dict(sorted(by_type.items())),
            "units": int(doc.units),
        },
        response_format,
    )


def dxf_list_entities(
    doc_id: str,
    layout: str | None = None,
    entity_type: str | None = None,
    layer: str | None = None,
    respect_layer_state: bool = True,
    limit: int = 100,
    offset: int = 0,
    response_format: str = "json",
) -> dict[str, Any]:
    """List entities with optional type/layer filters and layer-state semantics."""
    session = store.get(doc_id)
    entities = iter_entities(
        _layout(session, layout),
        session.doc,
        respect_layer_state=respect_layer_state,
    )
    rows = [
        _entity_row(entity)
        for entity in entities
        if (entity_type is None or entity.dxftype() == entity_type.upper())
        and (layer is None or str(entity.dxf.get("layer", "0")).casefold() == layer.casefold())
    ]
    return response(paginate(rows, limit, offset), response_format)


def dxf_query(
    doc_id: str,
    query: str,
    layout: str | None = None,
    respect_layer_state: bool = True,
    limit: int = 100,
    offset: int = 0,
    response_format: str = "json",
) -> dict[str, Any]:
    """Run ezdxf's entity query language within a chosen layout."""
    session = store.get(doc_id)
    allowed = {
        entity.dxf.get("handle")
        for entity in iter_entities(
            _layout(session, layout),
            session.doc,
            respect_layer_state=respect_layer_state,
        )
    }
    rows = [
        _entity_row(entity)
        for entity in _layout(session, layout).query(query)
        if entity.dxf.get("handle") in allowed
    ]
    return response(paginate(rows, limit, offset), response_format)


def dxf_get_entity(
    doc_id: str, handle: str, response_format: str = "json"
) -> dict[str, Any]:
    """Get one entity including DXF attributes and extension surfaces."""
    doc = store.get(doc_id).doc
    entity = doc.entitydb.get(handle.upper())
    if entity is None:
        raise ValueError(f"handle not found: {handle}")
    row = _entity_row(entity)
    row["has_xdata"] = bool(getattr(entity, "xdata", None))
    row["has_appdata"] = bool(getattr(entity, "appdata", None))
    row["has_extension_dict"] = bool(getattr(entity, "extension_dict", None))
    row["has_reactors"] = bool(getattr(entity, "reactors", None))
    return response(row, response_format)


def dxf_groupby(
    doc_id: str,
    dxfattrib: str = "layer",
    layout: str | None = None,
    respect_layer_state: bool = True,
    response_format: str = "json",
) -> dict[str, Any]:
    """Group visible entities by a DXF attribute."""
    session = store.get(doc_id)
    groups = groupby.groupby(
        iter_entities(
            _layout(session, layout),
            session.doc,
            respect_layer_state=respect_layer_state,
        ),
        dxfattrib=dxfattrib,
    )
    return response(
        {
            "attribute": dxfattrib,
            "groups": {
                str(key): [entity.dxf.get("handle") for entity in entities]
                for key, entities in groups.items()
            },
        },
        response_format,
    )


def dxf_list_layouts(doc_id: str, response_format: str = "json") -> dict[str, Any]:
    """List modelspace and paperspaces with block-record relationships."""
    doc = store.get(doc_id).doc
    rows = []
    for layout in doc.layouts:
        rows.append(
            {
                "name": layout.name,
                "type": type(layout).__name__,
                "entity_count": len(layout),
                "block_record_handle": layout.block_record_handle,
                "layout_key": layout.layout_key,
            }
        )
    return response({"layouts": rows}, response_format)


def dxf_list_blocks(
    doc_id: str,
    include_special: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """List block definitions with entity and XREF metadata."""
    doc = store.get(doc_id).doc
    rows = []
    for block in doc.blocks:
        if not include_special and block.name.startswith("*"):
            continue
        rows.append(
            {
                "name": block.name,
                "entity_count": len(block),
                "block_record_handle": block.block_record_handle,
                "is_xref": block.block.is_xref,
                "is_xref_overlay": block.block.is_xref_overlay,
                "base_point": list(block.block.dxf.base_point),
            }
        )
    return response({"blocks": rows}, response_format)


def dxf_list_block_refs(
    doc_id: str, block_name: str | None = None, response_format: str = "json"
) -> dict[str, Any]:
    """Count block references by name and block-record handle."""
    doc = store.get(doc_id).doc
    counter = blkrefs.BlockReferenceCounter(doc)
    names = [block_name] if block_name else [block.name for block in doc.blocks]
    rows = []
    for name in names:
        if name not in doc.blocks:
            continue
        block = doc.blocks[name]
        rows.append(
            {
                "name": name,
                "block_record_handle": block.block_record_handle,
                "count_by_name": counter.by_name(name),
                "count_by_handle": counter.by_handle(block.block_record_handle),
            }
        )
    return response({"references": rows}, response_format)


def dxf_find_unreferenced_blocks(
    doc_id: str, response_format: str = "json"
) -> dict[str, Any]:
    """Find unreferenced block definitions using ezdxf.blkrefs."""
    names = sorted(blkrefs.find_unreferenced_blocks(store.get(doc_id).doc))
    return response({"blocks": names}, response_format)


def dxf_create_block(
    doc_id: str,
    name: str,
    base_point: list[float] | None = None,
    entities: list[dict[str, Any]] | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Create a block definition and optional supported entities."""
    session = store.get(doc_id)
    if name in session.doc.blocks:
        raise ValueError(f"block already exists: {name}")
    block = session.doc.blocks.new(name, base_point=Vec3(base_point or (0, 0, 0)))
    created = [_entity_row(_add_entity(block, spec)) for spec in (entities or [])]
    session.dirty = True
    return response({"name": name, "created_entities": created}, response_format)


def dxf_insert_block(
    doc_id: str,
    block_name: str,
    insert: list[float],
    layout: str | None = None,
    xscale: float = 1.0,
    yscale: float = 1.0,
    zscale: float = 1.0,
    rotation: float = 0.0,
    attribs: dict[str, str] | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Insert a block reference with explicit scale and optional ATTRIB values."""
    session = store.get(doc_id)
    if block_name not in session.doc.blocks:
        raise ValueError(f"block not found: {block_name}")
    ref = _layout(session, layout).add_blockref(
        block_name,
        insert,
        dxfattribs={
            "xscale": xscale,
            "yscale": yscale,
            "zscale": zscale,
            "rotation": rotation,
        },
    )
    if attribs:
        ref.add_auto_attribs(attribs)
    session.dirty = True
    return response(_entity_row(ref), response_format)


def dxf_manage_attribs(
    doc_id: str,
    insert_handle: str,
    action: str = "list",
    tag: str | None = None,
    value: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """List, add, update, or delete ATTRIB entities attached to an INSERT."""
    session = store.get(doc_id)
    entity = session.doc.entitydb.get(insert_handle.upper())
    if not isinstance(entity, Insert):
        raise ValueError("insert_handle does not reference an INSERT")
    if action == "list":
        pass
    elif action == "set":
        if not tag or value is None:
            raise ValueError("set requires tag and value")
        attrib = entity.get_attrib(tag, search_const=True)
        if attrib is None or attrib.dxftype() != "ATTRIB":
            entity.add_attrib(tag, value, insert=entity.dxf.insert)
        else:
            attrib.dxf.text = value
        session.dirty = True
    elif action == "delete":
        if not tag:
            raise ValueError("delete requires tag")
        entity.delete_attrib(tag, ignore=True)
        session.dirty = True
    else:
        raise ValueError("action must be list, set, or delete")
    rows = [
        {"handle": attrib.dxf.handle, "tag": attrib.dxf.tag, "value": attrib.dxf.text}
        for attrib in entity.attribs
    ]
    return response({"insert": insert_handle.upper(), "attribs": rows}, response_format)


def dxf_manage_paperspace(
    doc_id: str,
    action: str,
    name: str,
    new_name: str | None = None,
    viewport: dict[str, Any] | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Create, rename, delete, activate, or add a viewport to a paperspace layout."""
    session = store.get(doc_id)
    layouts = session.doc.layouts
    if action == "create":
        layout = layouts.new(name)
    elif action == "rename":
        if not new_name:
            raise ValueError("rename requires new_name")
        layouts.rename(name, new_name)
        layout = layouts.get(new_name)
    elif action == "delete":
        layouts.delete(name)
        session.dirty = True
        return response({"deleted": name}, response_format)
    elif action == "activate":
        layouts.set_active_layout(name)
        layout = layouts.get(name)
    elif action == "add_viewport":
        layout = layouts.get(name)
        if not viewport:
            raise ValueError("add_viewport requires viewport settings")
        layout.add_viewport(
            center=viewport["center"],
            size=tuple(viewport["size"]),
            view_center_point=viewport["view_center_point"],
            view_height=float(viewport["view_height"]),
            status=int(viewport.get("status", 2)),
        )
    else:
        raise ValueError("action must be create, rename, delete, activate, or add_viewport")
    session.dirty = action != "list"
    return response({"layout": layout.name, "entity_count": len(layout)}, response_format)


def register_tools(mcp: FastMCP) -> None:
    for read_func in (
        dxf_inspect_document,
        dxf_list_entities,
        dxf_query,
        dxf_get_entity,
        dxf_groupby,
        dxf_list_layouts,
        dxf_list_blocks,
        dxf_list_block_refs,
        dxf_find_unreferenced_blocks,
    ):
        register(mcp, read_func, read_only=True)
    for write_func in (
        dxf_create_block,
        dxf_insert_block,
        dxf_manage_attribs,
        dxf_manage_paperspace,
    ):
        register(mcp, write_func, read_only=False, idempotent=False)
