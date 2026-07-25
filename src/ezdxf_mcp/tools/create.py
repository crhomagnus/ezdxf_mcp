"""Batch entities, procedural forms/paths, dimensions, and hatches."""

from __future__ import annotations

import math
from typing import Any

from ezdxf.math import Matrix44, Vec3
from ezdxf.render import forms
from mcp.server.fastmcp import FastMCP

from ..formatting import response
from ..registry import register
from ..session import store
from .semantics import _add_entity


def _layout(session, name: str | None):
    return session.doc.modelspace() if name in {None, "", "Model", "Modelspace"} else session.doc.layouts.get(name)


def dxf_add_entities(
    doc_id: str,
    entities: list[dict[str, Any]],
    layout: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Add a validated batch of LINE/CIRCLE/ARC/LWPOLYLINE/POINT/TEXT entities."""
    session = store.get(doc_id)
    target = _layout(session, layout)
    created = [_add_entity(target, spec) for spec in entities]
    session.dirty = bool(created)
    return response(
        {
            "created": [
                {"handle": entity.dxf.handle, "type": entity.dxftype()} for entity in created
            ]
        },
        response_format,
    )


def dxf_add_form(
    doc_id: str,
    form: str,
    parameters: dict[str, Any] | None = None,
    layout: str | None = None,
    layer: str = "FORMS",
    translate: list[float] | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Add a procedural cube, cylinder, cone, sphere, or torus mesh."""
    session = store.get(doc_id)
    params = parameters or {}
    constructors = {
        "cube": forms.cube,
        "cylinder": forms.cylinder,
        "cone": forms.cone,
        "sphere": forms.sphere,
        "torus": forms.torus,
    }
    try:
        mesh = constructors[form.lower()](**params)
    except KeyError as exc:
        raise ValueError("form must be cube, cylinder, cone, sphere, or torus") from exc
    if layer not in session.doc.layers:
        session.doc.layers.new(layer)
    matrix = Matrix44.translate(*(translate or [0, 0, 0]))
    entity = mesh.render_mesh(
        _layout(session, layout), dxfattribs={"layer": layer}, matrix=matrix
    )
    session.dirty = True
    return response(
        {"handle": entity.dxf.handle, "type": entity.dxftype(), "form": form},
        response_format,
    )


def _gear_vertices(
    teeth: int, outer_radius: float, inner_radius: float, elevation: float
) -> list[Vec3]:
    points = []
    count = teeth * 4
    for index in range(count):
        radius = outer_radius if index % 4 in {1, 2} else inner_radius
        angle = math.tau * index / count
        points.append(Vec3(math.cos(angle) * radius, math.sin(angle) * radius, elevation))
    return points


def dxf_add_path_shape(
    doc_id: str,
    shape: str,
    parameters: dict[str, Any] | None = None,
    layout: str | None = None,
    layer: str = "PATH_SHAPES",
    response_format: str = "json",
) -> dict[str, Any]:
    """Add a rect, ngon, star, gear, helix, or wedge path as a new polyline."""
    session = store.get(doc_id)
    params = parameters or {}
    closed = True
    if shape == "rect":
        width = float(params.get("width", 1.0))
        height = float(params.get("height", 1.0))
        vertices = [Vec3(0, 0), Vec3(width, 0), Vec3(width, height), Vec3(0, height)]
    elif shape == "ngon":
        vertices = list(
            forms.ngon(
                int(params.get("count", 6)),
                radius=float(params.get("radius", 1.0)),
                rotation=float(params.get("rotation", 0.0)),
            )
        )
    elif shape == "star":
        vertices = list(
            forms.star(
                int(params.get("count", 5)),
                float(params.get("inner_radius", 0.5)),
                float(params.get("outer_radius", 1.0)),
                rotation=float(params.get("rotation", 0.0)),
            )
        )
    elif shape == "gear":
        vertices = _gear_vertices(
            int(params.get("teeth", 12)),
            float(params.get("outer_radius", 1.0)),
            float(params.get("inner_radius", 0.8)),
            float(params.get("elevation", 0.0)),
        )
    elif shape == "helix":
        vertices = list(
            forms.helix(
                float(params.get("radius", 1.0)),
                float(params.get("pitch", 1.0)),
                float(params.get("turns", 3.0)),
                int(params.get("resolution", 16)),
            )
        )
        closed = False
    elif shape == "wedge":
        width = float(params.get("width", 1.0))
        height = float(params.get("height", 1.0))
        vertices = [Vec3(0, 0), Vec3(width, 0), Vec3(0, height)]
    else:
        raise ValueError("shape must be rect, ngon, star, gear, helix, or wedge")
    if layer not in session.doc.layers:
        session.doc.layers.new(layer)
    target = _layout(session, layout)
    if all(abs(vertex.z) < 1e-12 for vertex in vertices):
        entity = target.add_lwpolyline(vertices, close=closed, dxfattribs={"layer": layer})
    else:
        entity = target.add_polyline3d(vertices, dxfattribs={"layer": layer})
        entity.close(closed)
    session.dirty = True
    return response(
        {
            "handle": entity.dxf.handle,
            "shape": shape,
            "vertex_count": len(vertices),
            "closed": closed,
        },
        response_format,
    )


def dxf_add_dimension(
    doc_id: str,
    kind: str,
    parameters: dict[str, Any],
    layout: str | None = None,
    dimstyle: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Add and render one of seven dimension types."""
    session = store.get(doc_id)
    target = _layout(session, layout)
    params = dict(parameters)
    if dimstyle is not None:
        params["dimstyle"] = dimstyle
    if kind == "linear":
        override = target.add_linear_dim(**params)
    elif kind == "aligned":
        override = target.add_aligned_dim(**params)
    elif kind == "angular_2l":
        override = target.add_angular_dim_2l(**params)
    elif kind == "angular_3p":
        override = target.add_angular_dim_3p(**params)
    elif kind == "ordinate":
        override = target.add_ordinate_dim(**params)
    elif kind == "radius":
        override = target.add_radius_dim(**params)
    elif kind == "diameter":
        override = target.add_diameter_dim(**params)
    else:
        raise ValueError(
            "kind must be linear, aligned, angular_2l, angular_3p, ordinate, radius, or diameter"
        )
    override.render()
    session.dirty = True
    dimension = override.dimension
    return response(
        {"handle": dimension.dxf.handle, "type": dimension.dxftype(), "kind": kind},
        response_format,
    )


def dxf_add_hatch(
    doc_id: str,
    boundaries: list[dict[str, Any]],
    layout: str | None = None,
    layer: str = "HATCH",
    color: int = 7,
    pattern_name: str = "SOLID",
    pattern_scale: float = 1.0,
    pattern_angle: float = 0.0,
    response_format: str = "json",
) -> dict[str, Any]:
    """Add a HATCH with polyline or edge-path boundaries."""
    session = store.get(doc_id)
    if layer not in session.doc.layers:
        session.doc.layers.new(layer)
    hatch = _layout(session, layout).add_hatch(
        color=color, dxfattribs={"layer": layer}
    )
    if pattern_name.upper() != "SOLID":
        hatch.set_pattern_fill(
            pattern_name,
            scale=pattern_scale,
            angle=pattern_angle,
        )
    for boundary in boundaries:
        if boundary.get("type", "polyline") == "polyline":
            hatch.paths.add_polyline_path(
                boundary["vertices"],
                is_closed=bool(boundary.get("closed", True)),
            )
        elif boundary["type"] == "edges":
            edge_path = hatch.paths.add_edge_path()
            for edge in boundary["edges"]:
                edge_type = edge["type"]
                if edge_type == "line":
                    edge_path.add_line(edge["start"], edge["end"])
                elif edge_type == "arc":
                    edge_path.add_arc(
                        edge["center"],
                        edge["radius"],
                        edge["start_angle"],
                        edge["end_angle"],
                        ccw=bool(edge.get("ccw", True)),
                    )
                else:
                    raise ValueError(f"unsupported hatch edge type: {edge_type}")
        else:
            raise ValueError("boundary type must be polyline or edges")
    session.dirty = True
    return response(
        {
            "handle": hatch.dxf.handle,
            "boundary_count": len(boundaries),
            "pattern": pattern_name,
        },
        response_format,
    )


def register_tools(mcp: FastMCP) -> None:
    for func in (
        dxf_add_entities,
        dxf_add_form,
        dxf_add_path_shape,
        dxf_add_dimension,
        dxf_add_hatch,
    ):
        register(mcp, func, read_only=False, idempotent=False)
