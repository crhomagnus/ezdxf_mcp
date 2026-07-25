"""Layers, resource tables, graphical attributes, colors, and plot styles."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ezdxf import appsettings, colors
from ezdxf.addons import acadctb
from ezdxf.entities import DXFGraphic
from ezdxf.gfxattribs import GfxAttribs
from mcp.server.fastmcp import FastMCP

from ..formatting import response
from ..layers import all_layer_names, layer_state
from ..registry import register
from ..session import store
from ..validation import require_overwrite, safe_path


def dxf_list_layers(doc_id: str, response_format: str = "json") -> dict[str, Any]:
    """List union(table entries, entity references), marking undefined layers."""
    session = store.get(doc_id)
    names = all_layer_names(session.doc)
    lookup = {layer.dxf.name.casefold(): layer for layer in session.doc.layers}
    rows = []
    for name, has_entry in sorted(names.items(), key=lambda item: item[0].casefold()):
        row: dict[str, Any] = {"name": name, "has_table_entry": has_entry}
        if has_entry:
            row.update(layer_state(lookup[name.casefold()]))
        else:
            row.update(
                {
                    "implicit_defaults": {
                        "color": 7,
                        "linetype": "Continuous",
                        "lineweight": -3,
                    }
                }
            )
        row["entity_count"] = sum(
            1
            for entity in session.doc.entitydb.values()
            if entity.is_alive
            and entity.dxf.is_supported("layer")
            and str(entity.dxf.get("layer", "0")).casefold() == name.casefold()
        )
        rows.append(row)
    return response({"layers": rows}, response_format)


def dxf_manage_layer(
    doc_id: str,
    action: str,
    name: str,
    new_name: str | None = None,
    color: int | None = None,
    linetype: str | None = None,
    lineweight: int | None = None,
    transparency: float | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Create, rename, or set graphical/state properties of a layer."""
    session = store.get(doc_id)
    doc = session.doc
    if action == "create":
        attrs = {
            key: value
            for key, value in {
                "color": color,
                "linetype": linetype,
                "lineweight": lineweight,
            }.items()
            if value is not None
        }
        GfxAttribs(
            layer=name,
            color=color if color is not None else 7,
            linetype=linetype or "Continuous",
            lineweight=lineweight if lineweight is not None else -3,
            transparency=transparency,
        )
        layer = doc.layers.new(name, dxfattribs=attrs)
    else:
        layer = doc.layers.get(name)
        if action == "rename":
            if not new_name:
                raise ValueError("rename requires new_name")
            old = layer.dxf.name
            layer.rename(new_name)
            for entity in doc.entitydb.values():
                if (
                    entity.is_alive
                    and entity.dxf.is_supported("layer")
                    and str(entity.dxf.get("layer", "")).casefold() == old.casefold()
                ):
                    entity.dxf.layer = new_name
            name = new_name
        elif action == "set":
            GfxAttribs(
                layer=name,
                color=color if color is not None else layer.color,
                linetype=linetype or layer.dxf.linetype,
                lineweight=lineweight if lineweight is not None else layer.dxf.lineweight,
                transparency=transparency if transparency is not None else layer.transparency,
            )
            if color is not None:
                layer.color = color
            if linetype is not None:
                if linetype not in doc.linetypes:
                    raise ValueError(f"linetype not found: {linetype}")
                layer.dxf.linetype = linetype
            if lineweight is not None:
                layer.dxf.lineweight = lineweight
            if transparency is not None:
                layer.transparency = transparency
        elif action == "on":
            layer.on()
        elif action == "off":
            layer.off()
        elif action == "freeze":
            layer.freeze()
        elif action == "thaw":
            layer.thaw()
        elif action == "lock":
            layer.lock()
        elif action == "unlock":
            layer.unlock()
        else:
            raise ValueError(
                "action must be create, rename, set, on, off, freeze, thaw, lock, or unlock"
            )
    session.dirty = True
    return response(layer_state(doc.layers.get(name)), response_format)


def dxf_delete_layer(
    doc_id: str,
    name: str,
    delete_entities: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Delete layer entities first, then the table entry; never delete layer 0."""
    if name.casefold() in {"0", "defpoints"}:
        raise ValueError("layer 0 and Defpoints are protected")
    session = store.get(doc_id)
    doc = session.doc
    entities = [
        entity
        for entity in doc.entitydb.values()
        if entity.is_alive
        and entity.dxf.is_supported("layer")
        and str(entity.dxf.get("layer", "")).casefold() == name.casefold()
    ]
    if entities and not delete_entities:
        raise ValueError(
            f"layer contains {len(entities)} entities; pass delete_entities=true to remove them first"
        )
    for entity in entities:
        entity.destroy()
    doc.entitydb.purge()
    doc.layers.remove(name)
    session.dirty = True
    return response({"deleted_layer": name, "deleted_entities": len(entities)}, response_format)


def dxf_organize_layers(
    doc_id: str,
    target_layer: str,
    query: str = "*",
    source_layer: str | None = None,
    layout: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Move entities selected by query and optional source layer to a target layer."""
    session = store.get(doc_id)
    doc = session.doc
    if target_layer not in doc.layers:
        doc.layers.new(target_layer)
    selected_layout = doc.modelspace() if layout is None else doc.layouts.get(layout)
    entities = list(selected_layout.query(query))
    if source_layer is not None:
        entities = [
            entity
            for entity in entities
            if str(entity.dxf.get("layer", "0")).casefold() == source_layer.casefold()
        ]
    previous = Counter(str(entity.dxf.get("layer", "0")) for entity in entities)
    for entity in entities:
        entity.dxf.layer = target_layer
    session.dirty = bool(entities)
    return response(
        {"moved": len(entities), "from_layers": dict(previous), "target": target_layer},
        response_format,
    )


def dxf_manage_linetype(
    doc_id: str,
    action: str,
    name: str,
    description: str = "",
    pattern: list[Any] | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Create, inspect, or delete simple/complex linetype table entries."""
    session = store.get(doc_id)
    table = session.doc.linetypes
    if action == "create":
        if not pattern:
            raise ValueError("create requires pattern, e.g. [0.2, 0.1, -0.1]")
        entry = table.new(
            name,
            dxfattribs={
                "description": description,
                "pattern": pattern,
                "length": float(pattern[0]),
            },
        )
        session.dirty = True
    elif action == "delete":
        if name.casefold() in {"bylayer", "byblock", "continuous"}:
            raise ValueError("built-in linetypes are protected")
        table.remove(name)
        session.dirty = True
        return response({"deleted": name}, response_format)
    elif action == "inspect":
        entry = table.get(name)
    else:
        raise ValueError("action must be create, inspect, or delete")
    return response(
        {
            "name": entry.dxf.name,
            "description": entry.dxf.description,
            "pattern_tags": [[tag.code, str(tag.value)] for tag in entry.pattern_tags.tags],
        },
        response_format,
    )


def dxf_manage_textstyle(
    doc_id: str,
    action: str,
    name: str,
    font: str | None = None,
    bigfont: str | None = None,
    width: float = 1.0,
    response_format: str = "json",
) -> dict[str, Any]:
    """Create, update, inspect, or delete a text style (SHX or TTF file name)."""
    session = store.get(doc_id)
    table = session.doc.styles
    if action == "create":
        entry = table.new(name)
    else:
        entry = table.get(name)
    if action in {"create", "set"}:
        if font is not None:
            entry.dxf.font = font
        if bigfont is not None:
            entry.dxf.bigfont = bigfont
        entry.dxf.width = width
        session.dirty = True
    elif action == "delete":
        if name.casefold() == "standard":
            raise ValueError("Standard style is protected")
        table.remove(name)
        session.dirty = True
        return response({"deleted": name}, response_format)
    elif action != "inspect":
        raise ValueError("action must be create, set, inspect, or delete")
    return response(
        {
            "name": entry.dxf.name,
            "font": entry.dxf.font,
            "bigfont": entry.dxf.bigfont,
            "width": entry.dxf.width,
            "font_kind": "SHX" if str(entry.dxf.font).lower().endswith(".shx") else "TTF",
        },
        response_format,
    )


def dxf_manage_dimstyle(
    doc_id: str,
    action: str,
    name: str,
    attributes: dict[str, Any] | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Create, update, inspect, or delete a DIMSTYLE table entry."""
    session = store.get(doc_id)
    table = session.doc.dimstyles
    if action == "create":
        entry = table.new(name)
    else:
        entry = table.get(name)
    if action in {"create", "set"}:
        for key, value in (attributes or {}).items():
            entry.dxf.set(key, value)
        session.dirty = True
    elif action == "delete":
        if name.casefold() == "standard":
            raise ValueError("Standard dimstyle is protected")
        table.remove(name)
        session.dirty = True
        return response({"deleted": name}, response_format)
    elif action != "inspect":
        raise ValueError("action must be create, set, inspect, or delete")
    return response(
        {"name": entry.dxf.name, "attributes": {k: str(v) for k, v in entry.dxfattribs().items()}},
        response_format,
    )


def dxf_manage_appid(
    doc_id: str,
    action: str,
    name: str,
    response_format: str = "json",
) -> dict[str, Any]:
    """Create, inspect, or delete an APPID required by XDATA."""
    session = store.get(doc_id)
    table = session.doc.appids
    if action == "create":
        entry = table.new(name)
        session.dirty = True
    elif action == "inspect":
        entry = table.get(name)
    elif action == "delete":
        table.remove(name)
        session.dirty = True
        return response({"deleted": name}, response_format)
    else:
        raise ValueError("action must be create, inspect, or delete")
    return response({"name": entry.dxf.name, "flags": entry.dxf.flags}, response_format)


def dxf_set_entity_attribs(
    doc_id: str,
    handles: list[str],
    attributes: dict[str, Any],
    response_format: str = "json",
) -> dict[str, Any]:
    """Set graphical attributes on entities after GfxAttribs validation."""
    session = store.get(doc_id)
    GfxAttribs(
        layer=attributes.get("layer", "0"),
        color=int(attributes.get("color", 256)),
        rgb=attributes.get("rgb"),
        linetype=attributes.get("linetype", "ByLayer"),
        lineweight=int(attributes.get("lineweight", -1)),
        transparency=attributes.get("transparency"),
        ltscale=float(attributes.get("ltscale", 1.0)),
    )
    changed = []
    for handle in handles:
        entity = session.doc.entitydb.get(handle.upper())
        if entity is None:
            raise ValueError(f"handle not found: {handle}")
        for key, value in attributes.items():
            if key == "rgb":
                entity.rgb = tuple(value) if value is not None else None
            elif key == "transparency":
                entity.transparency = value
            else:
                entity.dxf.set(key, value)
        changed.append(handle.upper())
    session.dirty = bool(changed)
    return response({"changed": changed, "attributes": attributes}, response_format)


def dxf_analyze_formatting(
    doc_id: str, response_format: str = "json"
) -> dict[str, Any]:
    """Analyze BYLAYER/BYBLOCK/explicit color, linetype, lineweight, and undefined layers."""
    session = store.get(doc_id)
    layers = all_layer_names(session.doc)
    counts: Counter[str] = Counter()
    invalid_lineweights = []
    undefined: Counter[str] = Counter()
    for entity in session.doc.entitydb.values():
        if not isinstance(entity, DXFGraphic) or not entity.is_alive:
            continue
        color = entity.dxf.get("color", 256)
        counts["color_bylayer" if color == 256 else "color_byblock" if color == 0 else "color_explicit"] += 1
        linetype = str(entity.dxf.get("linetype", "BYLAYER")).upper()
        counts[
            "linetype_bylayer"
            if linetype == "BYLAYER"
            else "linetype_byblock"
            if linetype == "BYBLOCK"
            else "linetype_explicit"
        ] += 1
        lineweight = int(entity.dxf.get("lineweight", -1))
        if lineweight < -3 or lineweight > 211:
            invalid_lineweights.append(
                {"handle": entity.dxf.get("handle"), "lineweight": lineweight}
            )
        layer = str(entity.dxf.get("layer", "0"))
        if not layers.get(layer, False):
            undefined[layer] += 1
    return response(
        {
            "attribute_modes": dict(counts),
            "undefined_layers": dict(undefined),
            "invalid_lineweights": invalid_lineweights,
        },
        response_format,
    )


def dxf_convert_colors(
    mode: str,
    value: Any,
    response_format: str = "json",
) -> dict[str, Any]:
    """Convert among ACI, RGB tuples, packed raw color, transparency, and luminance."""
    if mode == "aci_to_rgb":
        result: Any = list(colors.aci2rgb(int(value)))
    elif mode == "rgb_to_raw":
        result = colors.rgb2int(tuple(value))
    elif mode == "raw_to_rgb":
        result = list(colors.int2rgb(int(value)))
    elif mode == "transparency_to_float":
        result = colors.transparency2float(int(value))
    elif mode == "float_to_transparency":
        result = colors.float2transparency(float(value))
    elif mode == "luminance":
        red, green, blue = (float(channel) / 255 for channel in value)
        result = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    else:
        raise ValueError(
            "mode must be aci_to_rgb, rgb_to_raw, raw_to_rgb, transparency_to_float, "
            "float_to_transparency, or luminance"
        )
    return response({"mode": mode, "input": value, "result": result}, response_format)


def dxf_manage_plotstyles(
    action: str,
    path: str,
    kind: str = "ctb",
    overwrite: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Inspect or create CTB/STB plot-style files inside the workspace."""
    if action == "inspect":
        source = safe_path(path, must_exist=True, suffixes={".ctb", ".stb"})
        table = acadctb.load(source)
        return response(
            {
                "path": str(source),
                "type": type(table).__name__,
                "description": table.description,
                "custom_lineweights": list(table.custom_lineweight_table),
            },
            response_format,
        )
    if action == "create":
        target = safe_path(path, suffixes={".ctb", ".stb"})
        require_overwrite(target, overwrite)
        table = acadctb.new_ctb() if kind.lower() == "ctb" else acadctb.new_stb()
        target.parent.mkdir(parents=True, exist_ok=True)
        table.save(target)
        return response({"created": str(target), "type": type(table).__name__}, response_format)
    raise ValueError("action must be inspect or create")


def dxf_set_app_settings(
    doc_id: str,
    current_layer: str | None = None,
    current_linetype: str | None = None,
    current_dimstyle: str | None = None,
    current_textstyle: str | None = None,
    show_lineweight: bool | None = None,
    update_extents: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Set CAD application hints; these are suggestions, not rendering guarantees."""
    session = store.get(doc_id)
    doc = session.doc
    if current_layer is not None:
        appsettings.set_current_layer(doc, current_layer)
    if current_linetype is not None:
        appsettings.set_current_linetype(doc, current_linetype)
    if current_dimstyle is not None:
        appsettings.set_current_dimstyle(doc, current_dimstyle)
    if current_textstyle is not None:
        appsettings.set_current_textstyle(doc, current_textstyle)
    if show_lineweight is not None:
        appsettings.show_lineweight(doc, show_lineweight)
    extents = appsettings.update_extents(doc) if update_extents else None
    session.dirty = True
    return response(
        {
            "updated": True,
            "extents": [list(extents.extmin), list(extents.extmax)] if extents else None,
            "note": "CAD application settings are hints, not guarantees.",
        },
        response_format,
    )


def register_tools(mcp: FastMCP) -> None:
    for read_func in (dxf_list_layers, dxf_analyze_formatting, dxf_convert_colors):
        register(mcp, read_func, read_only=True)
    for write_func in (
        dxf_manage_layer,
        dxf_delete_layer,
        dxf_organize_layers,
        dxf_manage_linetype,
        dxf_manage_textstyle,
        dxf_manage_dimstyle,
        dxf_manage_appid,
        dxf_set_entity_attribs,
        dxf_manage_plotstyles,
        dxf_set_app_settings,
    ):
        register(
            mcp,
            write_func,
            read_only=False,
            destructive=write_func is dxf_delete_layer,
        )
