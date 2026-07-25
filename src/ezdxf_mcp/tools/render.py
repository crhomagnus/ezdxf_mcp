"""SVG, PNG, PDF, and JSON rendering with explicit output confinement."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from ezdxf import appsettings
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.config import (
    BackgroundPolicy,
    ColorPolicy,
    Configuration,
    HatchPolicy,
    ImagePolicy,
    LinePolicy,
    LineweightPolicy,
    ProxyGraphicPolicy,
    TextPolicy,
)
from ezdxf.addons.drawing.json import CustomJSONBackend, GeoJSONBackend
from ezdxf.addons.drawing.layout import Page, Settings
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend
from ezdxf.addons.drawing.svg import SVGBackend
from mcp.server.fastmcp import FastMCP

from ..formatting import response
from ..layers import hidden_layers
from ..registry import register
from ..session import store
from ..validation import require_overwrite, safe_path

_CONFIG: dict[str, Configuration] = {}


def _layout(session, name: str | None):
    return session.doc.modelspace() if name in {None, "", "Model", "Modelspace"} else session.doc.layouts.get(name)


def _configuration(doc_id: str) -> Configuration:
    return _CONFIG.get(doc_id, Configuration())


def _draw(doc_id: str, backend, layout: str | None, respect_layer_state: bool) -> None:
    session = store.get(doc_id)
    hidden = hidden_layers(session.doc) if respect_layer_state else set()

    def filter_func(entity) -> bool:
        return str(entity.dxf.get("layer", "0")).casefold() not in hidden

    Frontend(
        RenderContext(session.doc),
        backend,
        config=_configuration(doc_id),
    ).draw_layout(_layout(session, layout), filter_func=filter_func)


def dxf_render_svg(
    doc_id: str,
    output_path: str,
    layout: str | None = None,
    page_width_mm: float = 0.0,
    page_height_mm: float = 0.0,
    respect_layer_state: bool = True,
    overwrite: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Render SVG without Matplotlib; hidden/frozen layers are excluded by default."""
    target = safe_path(output_path, suffixes={".svg"})
    require_overwrite(target, overwrite)
    backend = SVGBackend()
    _draw(doc_id, backend, layout, respect_layer_state)
    content = backend.get_string(Page(page_width_mm, page_height_mm), settings=Settings())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return response({"output": str(target), "bytes": target.stat().st_size}, response_format)


def dxf_render_png(
    doc_id: str,
    output_path: str,
    layout: str | None = None,
    dpi: int = 150,
    respect_layer_state: bool = True,
    overwrite: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Render PNG through the optional Matplotlib backend."""
    import matplotlib.pyplot as plt

    target = safe_path(output_path, suffixes={".png"})
    require_overwrite(target, overwrite)
    figure = plt.figure()
    axis = figure.add_axes([0, 0, 1, 1])
    backend = MatplotlibBackend(axis)
    _draw(doc_id, backend, layout, respect_layer_state)
    figure.savefig(target, dpi=dpi)
    plt.close(figure)
    return response({"output": str(target), "bytes": target.stat().st_size, "dpi": dpi}, response_format)


def dxf_render_pdf(
    doc_id: str,
    output_path: str,
    layout: str | None = None,
    page_width_mm: float = 0.0,
    page_height_mm: float = 0.0,
    respect_layer_state: bool = True,
    overwrite: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Render PDF through the optional PyMuPDF backend."""
    target = safe_path(output_path, suffixes={".pdf"})
    require_overwrite(target, overwrite)
    backend = PyMuPdfBackend()
    _draw(doc_id, backend, layout, respect_layer_state)
    content = backend.get_pdf_bytes(Page(page_width_mm, page_height_mm))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return response({"output": str(target), "bytes": len(content)}, response_format)


def dxf_render_json(
    doc_id: str,
    backend_kind: str = "custom",
    output_path: str | None = None,
    layout: str | None = None,
    respect_layer_state: bool = True,
    overwrite: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Render deterministic geometry JSON through CustomJSON or GeoJSON backend."""
    if backend_kind == "custom":
        backend = CustomJSONBackend()
    elif backend_kind == "geojson":
        backend = GeoJSONBackend()
    else:
        raise ValueError("backend_kind must be custom or geojson")
    _draw(doc_id, backend, layout, respect_layer_state)
    data = backend.get_json_data()
    target_str = None
    if output_path:
        target = safe_path(output_path, suffixes={".json", ".geojson"})
        require_overwrite(target, overwrite)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        target_str = str(target)
    return response(
        {"backend": backend_kind, "output": target_str, "primitive_count": len(data), "geometry": data},
        response_format,
    )


def dxf_configure_render(
    doc_id: str,
    line_policy: str | None = None,
    hatch_policy: str | None = None,
    color_policy: str | None = None,
    background_policy: str | None = None,
    lineweight_policy: str | None = None,
    text_policy: str | None = None,
    image_policy: str | None = None,
    proxy_graphic_policy: str | None = None,
    max_flattening_distance: float | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Configure the eight drawing policies for subsequent renders of a session."""
    store.get(doc_id)
    changes: dict[str, Any] = {}
    enum_fields = {
        "line_policy": (line_policy, LinePolicy),
        "hatch_policy": (hatch_policy, HatchPolicy),
        "color_policy": (color_policy, ColorPolicy),
        "background_policy": (background_policy, BackgroundPolicy),
        "lineweight_policy": (lineweight_policy, LineweightPolicy),
        "text_policy": (text_policy, TextPolicy),
        "image_policy": (image_policy, ImagePolicy),
        "proxy_graphic_policy": (proxy_graphic_policy, ProxyGraphicPolicy),
    }
    for field, (value, enum_class) in enum_fields.items():
        if value is not None:
            try:
                changes[field] = enum_class[value.upper()]
            except KeyError as exc:
                raise ValueError(
                    f"{field} must be one of {[item.name for item in enum_class]}"
                ) from exc
    if max_flattening_distance is not None:
        changes["max_flattening_distance"] = max_flattening_distance
    config = _configuration(doc_id).with_changes(**changes)
    _CONFIG[doc_id] = config
    serialized = {
        key: (value.name if hasattr(value, "name") else value)
        for key, value in asdict(config).items()
    }
    return response({"doc_id": doc_id, "configuration": serialized}, response_format)


def dxf_zoom_extents(
    doc_id: str, response_format: str = "json"
) -> dict[str, Any]:
    """Update document extents for CAD zoom-extents and return the measured box."""
    session = store.get(doc_id)
    box = appsettings.update_extents(session.doc)
    session.dirty = True
    return response(
        {
            "extmin": list(box.extmin),
            "extmax": list(box.extmax),
            "header_extmin": list(session.doc.header["$EXTMIN"]),
            "header_extmax": list(session.doc.header["$EXTMAX"]),
        },
        response_format,
    )


def register_tools(mcp: FastMCP) -> None:
    for func in (
        dxf_render_svg,
        dxf_render_png,
        dxf_render_pdf,
        dxf_render_json,
        dxf_configure_render,
        dxf_zoom_extents,
    ):
        register(mcp, func, read_only=False, idempotent=True)
