"""Resource import, XREF, XCLIP, and named-group tools."""

from __future__ import annotations

from typing import Any

import ezdxf
from ezdxf import xref
from ezdxf.addons import Importer
from ezdxf.entities import Insert
from ezdxf.xclip import XClip
from mcp.server.fastmcp import FastMCP

from ..formatting import response
from ..registry import register
from ..session import store
from ..validation import require_overwrite, safe_path


def _conflict_policy(name: str) -> xref.ConflictPolicy:
    try:
        return xref.ConflictPolicy[name.upper()]
    except KeyError as exc:
        raise ValueError(
            f"conflict_policy must be one of {[item.name for item in xref.ConflictPolicy]}"
        ) from exc


def dxf_import_from(
    doc_id: str,
    source_path: str,
    mode: str = "modelspace",
    query: str = "*",
    target_layout: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Import modelspace or queried resources/entities from another workspace DXF."""
    session = store.get(doc_id)
    source = safe_path(source_path, must_exist=True, suffixes={".dxf"})
    source_doc = ezdxf.readfile(source)
    importer = Importer(source_doc, session.doc)
    target = (
        session.doc.modelspace()
        if target_layout in {None, "", "Model", "Modelspace"}
        else session.doc.layouts.get(target_layout)
    )
    if mode == "modelspace":
        importer.import_modelspace(target_layout=target)
    elif mode == "query":
        importer.import_entities(source_doc.modelspace().query(query), target_layout=target)
    else:
        raise ValueError("mode must be modelspace or query")
    importer.finalize()
    session.dirty = True
    return response(
        {"source": str(source), "mode": mode, "target_layout": target.name}, response_format
    )


def dxf_manage_xref(
    doc_id: str,
    action: str,
    block_name: str | None = None,
    filename: str | None = None,
    insert: list[float] | None = None,
    scale: float = 1.0,
    rotation: float = 0.0,
    overlay: bool = False,
    conflict_policy: str = "XREF_PREFIX",
    output_path: str | None = None,
    paperspace: str | None = None,
    handles: list[str] | None = None,
    overwrite: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Attach, define, embed, detach, load, or write XREF content."""
    session = store.get(doc_id)
    doc = session.doc
    result: dict[str, Any] = {"action": action}
    if action in {"attach", "define"}:
        if not block_name or not filename:
            raise ValueError(f"{action} requires block_name and filename")
        source = safe_path(filename, must_exist=True, suffixes={".dxf"})
        if action == "attach":
            ref = xref.attach(
                doc,
                block_name=block_name,
                filename=str(source),
                insert=insert or (0, 0, 0),
                scale=scale,
                rotation=rotation,
                overlay=overlay,
            )
            result["insert_handle"] = ref.dxf.handle
        else:
            xref.define(doc, block_name, str(source), overlay=overlay)
        result.update({"block_name": block_name, "filename": str(source)})
    elif action == "embed":
        if not block_name:
            raise ValueError("embed requires block_name")
        xref.embed(
            doc.blocks[block_name],
            search_paths=[str(safe_path("."))],
            conflict_policy=_conflict_policy(conflict_policy),
        )
        result["block_name"] = block_name
    elif action == "detach":
        if not block_name or not output_path:
            raise ValueError("detach requires block_name and output_path")
        target = safe_path(output_path, suffixes={".dxf"})
        require_overwrite(target, overwrite)
        detached = xref.detach(doc.blocks[block_name], xref_filename=str(target), overlay=overlay)
        detached.saveas(target)
        result["output"] = str(target)
    elif action in {"load_modelspace", "load_paperspace"}:
        if not filename:
            raise ValueError(f"{action} requires filename")
        source = safe_path(filename, must_exist=True, suffixes={".dxf"})
        source_doc = ezdxf.readfile(source)
        policy = _conflict_policy(conflict_policy)
        if action == "load_modelspace":
            xref.load_modelspace(source_doc, doc, conflict_policy=policy)
        else:
            if not paperspace:
                raise ValueError("load_paperspace requires paperspace name")
            xref.load_paperspace(source_doc.layouts.get(paperspace), doc, conflict_policy=policy)
        result["source"] = str(source)
    elif action == "write_block":
        if not output_path or not handles:
            raise ValueError("write_block requires output_path and handles")
        target = safe_path(output_path, suffixes={".dxf"})
        require_overwrite(target, overwrite)
        entities = []
        for handle in handles:
            entity = doc.entitydb.get(handle.upper())
            if entity is None:
                raise ValueError(f"handle not found: {handle}")
            entities.append(entity)
        out_doc = xref.write_block(entities, origin=insert or (0, 0, 0))
        out_doc.saveas(target)
        result["output"] = str(target)
    else:
        raise ValueError(
            "action must be attach, define, embed, detach, load_modelspace, "
            "load_paperspace, or write_block"
        )
    session.dirty = action not in {"detach", "write_block"}
    return response(result, response_format)


def dxf_inspect_xref(path: str, response_format: str = "json") -> dict[str, Any]:
    """Inspect XREF metadata without loading the full document."""
    source = safe_path(path, must_exist=True, suffixes={".dxf"})
    info = xref.dxf_info(source)
    return response(
        {
            "path": str(source),
            "version": info.version,
            "encoding": info.encoding,
            "handseed": info.handseed,
            "insert_units": int(info.insert_units),
            "insert_base": list(info.insert_base),
        },
        response_format,
    )


def dxf_manage_xclip(
    doc_id: str,
    insert_handle: str,
    action: str = "inspect",
    vertices: list[list[float]] | None = None,
    coordinates: str = "block",
    response_format: str = "json",
) -> dict[str, Any]:
    """Inspect, set, enable, disable, or discard a 2D XCLIP boundary."""
    session = store.get(doc_id)
    entity = session.doc.entitydb.get(insert_handle.upper())
    if not isinstance(entity, Insert):
        raise ValueError("insert_handle does not reference an INSERT")
    clip = XClip(entity)
    if action == "set":
        if not vertices:
            raise ValueError("set requires vertices")
        if coordinates == "wcs":
            clip.set_wcs_clipping_path(vertices)
        elif coordinates == "block":
            clip.set_block_clipping_path(vertices)
        else:
            raise ValueError("coordinates must be block or wcs")
        session.dirty = True
    elif action == "enable":
        clip.enable_clipping()
        session.dirty = True
    elif action == "disable":
        clip.disable_clipping()
        session.dirty = True
    elif action == "discard":
        clip.discard_clipping_path()
        session.dirty = True
    elif action != "inspect":
        raise ValueError("action must be inspect, set, enable, disable, or discard")
    path = clip.get_wcs_clipping_path()
    return response(
        {
            "insert_handle": insert_handle.upper(),
            "has_path": clip.has_clipping_path,
            "enabled": clip.is_clipping_enabled,
            "inverted": clip.is_inverted_clip,
            "vertices": [list(vertex) for vertex in path.vertices],
        },
        response_format,
    )


def dxf_manage_groups(
    doc_id: str,
    action: str = "list",
    name: str | None = None,
    description: str = "",
    handles: list[str] | None = None,
    selectable: bool = True,
    response_format: str = "json",
) -> dict[str, Any]:
    """List, create, replace, extend, clear, or delete named DXF groups."""
    session = store.get(doc_id)
    groups = session.doc.groups
    if action == "list":
        rows = [
            {
                "name": group_name,
                "description": group.dxf.description,
                "selectable": bool(group.dxf.unnamed == 0),
                "handles": group.handles(),
            }
            for group_name, group in groups
        ]
        return response({"groups": rows}, response_format)
    if not name:
        raise ValueError(f"{action} requires group name")
    if action == "delete":
        groups.delete(name)
        session.dirty = True
        return response({"deleted": name}, response_format)
    if action == "create":
        group = groups.new(name, description=description, selectable=selectable)
    else:
        group = groups.get(name)
    if action in {"create", "replace", "extend"} and handles:
        entities = []
        layout_owner_handles = {layout.block_record_handle for layout in session.doc.layouts}
        for handle in handles:
            entity = session.doc.entitydb.get(handle.upper())
            if entity is None:
                raise ValueError(f"handle not found: {handle}")
            if entity.dxf.get("owner") not in layout_owner_handles:
                raise ValueError(
                    f"entity {handle} is in a block definition; DXF groups cannot contain it"
                )
            entities.append(entity)
        if action in {"create", "replace"}:
            group.set_data(entities)
        else:
            group.extend(entities)
    elif action == "clear":
        group.clear()
    elif action not in {"create", "replace", "extend"}:
        raise ValueError("action must be list, create, replace, extend, clear, or delete")
    session.dirty = True
    return response({"name": name, "handles": group.handles()}, response_format)


def register_tools(mcp: FastMCP) -> None:
    register(mcp, dxf_import_from, read_only=False, idempotent=False)
    register(mcp, dxf_manage_xref, read_only=False, destructive=True, idempotent=False)
    register(mcp, dxf_inspect_xref, read_only=True)
    register(mcp, dxf_manage_xclip, read_only=False, idempotent=False)
    register(mcp, dxf_manage_groups, read_only=False, idempotent=False)
