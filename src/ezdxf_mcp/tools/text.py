"""TEXT/MTEXT creation, extraction, formatting inspection, and contours."""

from __future__ import annotations

import re
from typing import Any

from ezdxf import path
from ezdxf.addons import MTextExplode, text2path
from ezdxf.entities import MText, Text
from ezdxf.fonts import fonts
from ezdxf.tools.text import MTextEditor, plain_mtext, plain_text
from mcp.server.fastmcp import FastMCP

from ..formatting import response
from ..registry import register
from ..session import store

_INLINE_CODE = re.compile(
    r"\\(?P<code>[PpFfSsAaCcHhWwQq])(?P<value>[^;{}\\\\]*;)?|(?P<brace>[{}])"
)


def _layout(session, name: str | None):
    return session.doc.modelspace() if name in {None, "", "Model", "Modelspace"} else session.doc.layouts.get(name)


def dxf_add_text(
    doc_id: str,
    text: str,
    insert: list[float],
    kind: str = "TEXT",
    layout: str | None = None,
    layer: str = "0",
    height: float = 2.5,
    style: str = "Standard",
    width: float | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Add TEXT or MTEXT; MTEXT content is passed through MTextEditor."""
    session = store.get(doc_id)
    target = _layout(session, layout)
    if kind.upper() == "TEXT":
        entity = target.add_text(
            text,
            dxfattribs={"layer": layer, "height": height, "style": style},
        ).set_placement(insert)
    elif kind.upper() == "MTEXT":
        editor = MTextEditor(text)
        attrs: dict[str, Any] = {
            "layer": layer,
            "char_height": height,
            "style": style,
            "insert": insert,
        }
        if width is not None:
            attrs["width"] = width
        entity = target.add_mtext(str(editor), dxfattribs=attrs)
    else:
        raise ValueError("kind must be TEXT or MTEXT")
    session.dirty = True
    return response(
        {"handle": entity.dxf.handle, "type": entity.dxftype(), "text": text},
        response_format,
    )


def dxf_extract_text(
    doc_id: str,
    handles: list[str] | None = None,
    split_paragraphs: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Extract plain text from TEXT and MTEXT entities."""
    doc = store.get(doc_id).doc
    source = (
        [doc.entitydb.get(handle.upper()) for handle in handles]
        if handles
        else list(doc.query("TEXT MTEXT"))
    )
    rows = []
    for entity in source:
        if isinstance(entity, MText):
            extracted = plain_mtext(entity.text, split=split_paragraphs)
        elif isinstance(entity, Text):
            extracted = plain_text(entity.dxf.text)
        else:
            continue
        rows.append(
            {"handle": entity.dxf.handle, "type": entity.dxftype(), "text": extracted}
        )
    return response({"entities": rows}, response_format)


def dxf_inspect_mtext_formatting(
    doc_id: str, handle: str, response_format: str = "json"
) -> dict[str, Any]:
    """Inspect MTEXT inline codes, stacked text, braces, colors, and heights."""
    entity = store.get(doc_id).doc.entitydb.get(handle.upper())
    if not isinstance(entity, MText):
        raise ValueError("handle does not reference MTEXT")
    codes = []
    brace_depth = 0
    max_depth = 0
    for match in _INLINE_CODE.finditer(entity.text):
        if match.group("brace") == "{":
            brace_depth += 1
            max_depth = max(max_depth, brace_depth)
            codes.append({"code": "{", "position": match.start(), "depth": brace_depth})
        elif match.group("brace") == "}":
            codes.append({"code": "}", "position": match.start(), "depth": brace_depth})
            brace_depth -= 1
        else:
            codes.append(
                {
                    "code": match.group("code"),
                    "value": (match.group("value") or "").removesuffix(";"),
                    "position": match.start(),
                    "depth": brace_depth,
                }
            )
    return response(
        {
            "handle": handle.upper(),
            "raw_text": entity.text,
            "plain_text": plain_mtext(entity.text),
            "codes": codes,
            "max_brace_depth": max_depth,
            "balanced_braces": brace_depth == 0,
            "embedded_stack_count": sum(str(item["code"]).upper() == "S" for item in codes),
            "embedded_color_count": sum(str(item["code"]).upper() == "C" for item in codes),
            "embedded_height_count": sum(str(item["code"]).upper() == "H" for item in codes),
        },
        response_format,
    )


def dxf_explode_mtext(
    doc_id: str,
    handles: list[str],
    layout: str | None = None,
    destroy: bool = False,
    spacing_factor: float = 1.0,
    response_format: str = "json",
) -> dict[str, Any]:
    """Explode MTEXT into TEXT entities using ezdxf.addons.MTextExplode."""
    session = store.get(doc_id)
    target = _layout(session, layout)
    before = {entity.dxf.handle for entity in target}
    with MTextExplode(target, doc=session.doc, spacing_factor=spacing_factor) as exploder:
        for handle in handles:
            entity = session.doc.entitydb.get(handle.upper())
            if not isinstance(entity, MText):
                raise ValueError(f"handle is not MTEXT: {handle}")
            exploder.explode(entity, destroy=destroy)
    created = [entity.dxf.handle for entity in target if entity.dxf.handle not in before]
    session.dirty = bool(created)
    return response({"created": created, "destroyed_sources": destroy}, response_format)


def dxf_text_to_contour(
    doc_id: str,
    handles: list[str],
    layout: str | None = None,
    layer: str = "TEXT_CONTOUR",
    max_sagitta: float = 0.01,
    response_format: str = "json",
) -> dict[str, Any]:
    """Create new LWPOLYLINE text contours with the configured fonts."""
    session = store.get(doc_id)
    paths = []
    for handle in handles:
        entity = session.doc.entitydb.get(handle.upper())
        if not isinstance(entity, (Text, MText)):
            raise ValueError(f"handle is not TEXT/MTEXT: {handle}")
        paths.extend(text2path.make_paths_from_entity(entity))
    if layer not in session.doc.layers:
        session.doc.layers.new(layer)
    created = path.render_lwpolylines(
        _layout(session, layout),
        paths,
        distance=max_sagitta,
        dxfattribs={"layer": layer},
    )
    result = [entity.dxf.handle for entity in created]
    session.dirty = bool(result)
    return response({"created": result, "path_count": len(paths)}, response_format)


def dxf_manage_fonts(
    doc_id: str,
    action: str = "list_styles",
    font_name: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """List drawing fonts or resolve a TTF/SHX font through ezdxf's font manager."""
    doc = store.get(doc_id).doc
    if action == "list_styles":
        rows = []
        for style in doc.styles:
            name = style.dxf.font
            try:
                face = fonts.resolve_font_face(name)
                resolved = {
                    "family": face.family,
                    "style": face.style,
                    "weight": face.weight,
                    "width": face.width,
                }
                missing = False
            except fonts.FontNotFoundError:
                resolved = None
                missing = True
            rows.append(
                {
                    "style": style.dxf.name,
                    "font": name,
                    "kind": "SHX" if fonts.is_shx_font_name(name) else "TTF",
                    "missing": missing,
                    "resolved": resolved,
                }
            )
        return response({"styles": rows}, response_format)
    if action == "resolve":
        if not font_name:
            raise ValueError("resolve requires font_name")
        face = fonts.resolve_font_face(font_name)
        return response(
            {
                "font_name": font_name,
                "family": face.family,
                "style": face.style,
                "weight": face.weight,
                "width": face.width,
            },
            response_format,
        )
    raise ValueError("action must be list_styles or resolve")


def register_tools(mcp: FastMCP) -> None:
    for read_func in (dxf_extract_text, dxf_inspect_mtext_formatting, dxf_manage_fonts):
        register(mcp, read_func, read_only=True)
    for write_func in (dxf_add_text, dxf_explode_mtext, dxf_text_to_contour):
        register(mcp, write_func, read_only=False, idempotent=False)
