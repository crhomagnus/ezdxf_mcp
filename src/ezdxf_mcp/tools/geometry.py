"""Structural geometry analysis, transformations, construction, and selection."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from ezdxf import bbox, disassemble, path, select, transform, upright
from ezdxf import edgeminer as em
from ezdxf import edgesmith as es
from ezdxf.entities import DXFEntity, Insert
from ezdxf.math import Matrix44, Vec2, Vec3, offset_vertices_2d
from ezdxf.math.clipping import (
    greiner_hormann_difference,
    greiner_hormann_intersection,
    greiner_hormann_union,
)
from mcp.server.fastmcp import FastMCP

from ..formatting import response
from ..layers import iter_entities
from ..registry import register
from ..session import store


def _layout(session, name: str | None):
    return session.doc.modelspace() if name in {None, "", "Model", "Modelspace"} else session.doc.layouts.get(name)


def _edge_entities(session, layout: str | None, respect_layer_state: bool):
    return list(
        es.filter_edge_entities(
            iter_entities(
                _layout(session, layout),
                session.doc,
                respect_layer_state=respect_layer_state,
            )
        )
    )


def _analyze(
    doc_id: str,
    *,
    layout: str | None,
    gap_tol: float,
    timeout: float,
    respect_layer_state: bool,
) -> dict[str, Any]:
    session = store.get(doc_id)
    visible = list(
        iter_entities(
            _layout(session, layout),
            session.doc,
            respect_layer_state=respect_layer_state,
        )
    )
    closed_entities = [
        {
            "handle": entity.dxf.get("handle"),
            "type": entity.dxftype(),
        }
        for entity in visible
        if es.is_closed_entity(entity)
    ]
    candidates = list(es.filter_edge_entities(visible))
    edges = list(es.edges_from_entities_2d(candidates, gap_tol=gap_tol))
    deposit = em.Deposit(edges, gap_tol=gap_tol)
    networks = list(deposit.find_all_networks())
    network_rows = []
    total_loops = 0
    incomplete = False
    for index, network in enumerate(networks):
        sub = em.Deposit(list(network), gap_tol=gap_tol)
        partial = False
        try:
            loops = em.find_all_loops(sub, timeout=timeout)
        except em.TimeoutError as exc:
            loops = exc.solutions
            partial = True
            incomplete = True
        loop_rows = []
        for loop in loops:
            loop_rows.append(
                {
                    "edge_count": len(loop),
                    "area": es.loop_area(loop, gap_tol=gap_tol),
                    "perimeter": sum(edge.length for edge in loop),
                    "source_handles": sorted(
                        {
                            edge.payload.dxf.get("handle")
                            for edge in loop
                            if isinstance(edge.payload, DXFEntity)
                        }
                    ),
                }
            )
        total_loops += len(loops)
        network_rows.append(
            {
                "index": index,
                "edge_count": len(network),
                "loop_count": len(loops),
                "loops": loop_rows,
                "leaf_count": sum(1 for _ in sub.find_leafs()),
                "max_degree": sub.max_degree,
                "partial_timeout_result": partial,
            }
        )
    return {
        "gap_tolerance": gap_tol,
        "visible_entities": len(visible),
        "edge_candidate_entities": len(candidates),
        "edges": len(edges),
        "network_count": len(networks),
        "loop_count": total_loops,
        "closed_entities_counted_separately": closed_entities,
        "incomplete": incomplete,
        "networks": network_rows,
    }


def dxf_analyze_contours(
    doc_id: str,
    layout: str | None = None,
    gap_tol: float = 0.01,
    timeout: float = 60.0,
    respect_layer_state: bool = True,
    response_format: str = "json",
) -> dict[str, Any]:
    """Analyze contour loops per disconnected network, preserving partial timeout results."""
    if gap_tol <= 0:
        raise ValueError("gap_tol must be > 0")
    return response(
        _analyze(
            doc_id,
            layout=layout,
            gap_tol=gap_tol,
            timeout=timeout,
            respect_layer_state=respect_layer_state,
        ),
        response_format,
    )


def dxf_sweep_tolerance(
    doc_id: str,
    tolerances: list[float],
    layout: str | None = None,
    timeout: float = 10.0,
    respect_layer_state: bool = True,
    response_format: str = "json",
) -> dict[str, Any]:
    """Measure contour stability over explicit gap tolerances."""
    rows = []
    for tolerance in tolerances:
        data = _analyze(
            doc_id,
            layout=layout,
            gap_tol=float(tolerance),
            timeout=timeout,
            respect_layer_state=respect_layer_state,
        )
        rows.append(
            {
                "gap_tolerance": tolerance,
                "networks": data["network_count"],
                "loops": data["loop_count"],
                "incomplete": data["incomplete"],
            }
        )
    return response({"sweep": rows}, response_format)


def _geometry_key(entity: DXFEntity, tolerance: float) -> tuple[Any, ...] | None:
    def quantize(value: Any) -> int | float:
        return round(float(value) / tolerance) if tolerance else float(value)

    kind = entity.dxftype()
    if kind == "LINE":
        points = sorted(
            (
                tuple(quantize(v) for v in entity.dxf.start),
                tuple(quantize(v) for v in entity.dxf.end),
            )
        )
        return (kind, *points)
    if kind == "CIRCLE":
        return (
            kind,
            *(quantize(v) for v in entity.dxf.center),
            quantize(entity.dxf.radius),
        )
    if kind == "ARC":
        return (
            kind,
            *(quantize(v) for v in entity.dxf.center),
            quantize(entity.dxf.radius),
            quantize(entity.dxf.get("start_angle", 0)),
            quantize(entity.dxf.get("end_angle", 360)),
        )
    if kind == "LWPOLYLINE":
        return (
            kind,
            tuple((quantize(p[0]), quantize(p[1]), quantize(p[4])) for p in entity.get_points()),
            entity.closed,
        )
    return None


def dxf_find_duplicates(
    doc_id: str,
    tolerance: float = 1e-9,
    layout: str | None = None,
    respect_layer_state: bool = True,
    response_format: str = "json",
) -> dict[str, Any]:
    """Find geometrically duplicate LINE/CIRCLE/ARC/LWPOLYLINE entities."""
    session = store.get(doc_id)
    grouped: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    unsupported: Counter[str] = Counter()
    for entity in iter_entities(
        _layout(session, layout),
        session.doc,
        respect_layer_state=respect_layer_state,
    ):
        key = _geometry_key(entity, tolerance)
        if key is None:
            unsupported[entity.dxftype()] += 1
            continue
        grouped[key].append(entity.dxf.handle)
    duplicates = [handles for handles in grouped.values() if len(handles) > 1]
    return response(
        {"duplicate_groups": duplicates, "unsupported_types": dict(unsupported)},
        response_format,
    )


def dxf_check_2d_purity(
    doc_id: str,
    tolerance: float = 1e-9,
    layout: str | None = None,
    respect_layer_state: bool = True,
    response_format: str = "json",
) -> dict[str, Any]:
    """Report non-zero Z extents and non-WCS extrusion vectors."""
    session = store.get(doc_id)
    findings = []
    for entity in iter_entities(
        _layout(session, layout),
        session.doc,
        respect_layer_state=respect_layer_state,
    ):
        box = bbox.extents([entity], fast=True)
        nonzero_z = box.has_data and (
            abs(box.extmin.z) > tolerance or abs(box.extmax.z) > tolerance
        )
        extrusion = Vec3(entity.dxf.get("extrusion", (0, 0, 1)))
        tilted = not extrusion.isclose((0, 0, 1), abs_tol=tolerance)
        if nonzero_z or tilted:
            findings.append(
                {
                    "handle": entity.dxf.handle,
                    "type": entity.dxftype(),
                    "z_range": [box.extmin.z, box.extmax.z] if box.has_data else None,
                    "extrusion": list(extrusion),
                }
            )
    return response({"pure_2d": not findings, "findings": findings}, response_format)


def dxf_measure_extents(
    doc_id: str,
    layout: str | None = None,
    fast: bool = False,
    respect_layer_state: bool = True,
    response_format: str = "json",
) -> dict[str, Any]:
    """Measure visible geometry extents with a bbox cache."""
    session = store.get(doc_id)
    cache = bbox.Cache()
    box = bbox.extents(
        iter_entities(
            _layout(session, layout),
            session.doc,
            respect_layer_state=respect_layer_state,
        ),
        fast=fast,
        cache=cache,
    )
    return response(
        {
            "has_data": box.has_data,
            "extmin": list(box.extmin) if box.has_data else None,
            "extmax": list(box.extmax) if box.has_data else None,
            "size": list(box.size) if box.has_data else None,
            "cache_entries": len(cache._boxes),
            "cache_hits": cache.hits,
            "cache_misses": cache.misses,
        },
        response_format,
    )


def dxf_measure_geometry(
    doc_id: str,
    layout: str | None = None,
    gap_tol: float = 0.01,
    respect_layer_state: bool = True,
    response_format: str = "json",
) -> dict[str, Any]:
    """Measure edge length, closed-loop area, and entity counts."""
    session = store.get(doc_id)
    entities = list(
        iter_entities(
            _layout(session, layout),
            session.doc,
            respect_layer_state=respect_layer_state,
        )
    )
    edges = list(
        es.edges_from_entities_2d(es.filter_edge_entities(entities), gap_tol=gap_tol)
    )
    deposit = em.Deposit(edges, gap_tol=gap_tol)
    simple_chains = em.find_all_simple_chains(deposit)
    closed = [chain for chain in simple_chains if em.is_loop(chain)]
    return response(
        {
            "entity_count": len(entities),
            "edge_count": len(edges),
            "edge_length": sum(edge.length for edge in edges),
            "closed_chain_count": len(closed),
            "closed_area_abs": sum(abs(es.loop_area(chain, gap_tol=gap_tol)) for chain in closed),
            "entity_types": dict(Counter(entity.dxftype() for entity in entities)),
        },
        response_format,
    )


def dxf_normalize_extrusions(
    doc_id: str,
    handles: list[str] | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Upright entities with extrusion `(0,0,-1)` while preserving WCS geometry."""
    session = store.get(doc_id)
    entities = (
        [
            session.doc.entitydb.get(handle.upper())
            for handle in handles
            if session.doc.entitydb.get(handle.upper()) is not None
        ]
        if handles
        else list(session.doc.entitydb.values())
    )
    candidates = [
        entity
        for entity in entities
        if entity is not None
        and entity.is_alive
        and entity.dxf.is_supported("extrusion")
        and entity.dxf.get("extrusion") is not None
    ]
    before = sum(
        1 for entity in candidates if Vec3(entity.dxf.extrusion).isclose((0, 0, -1))
    )
    upright.upright_all(candidates)
    session.dirty = before > 0
    return response({"normalized": before, "considered": len(candidates)}, response_format)


def dxf_flatten_to_2d(
    doc_id: str,
    handles: list[str] | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Project selected graphical entities onto Z=0 and report unsupported transforms."""
    session = store.get(doc_id)
    entities = (
        [session.doc.entitydb.get(handle.upper()) for handle in handles]
        if handles
        else list(session.doc.modelspace())
    )
    valid = [entity for entity in entities if entity is not None and entity.is_alive]
    logger = transform.inplace(valid, Matrix44.scale(1, 1, 0))
    session.dirty = bool(valid)
    return response(
        {
            "considered": len(valid),
            "errors": [
                {"error": str(error), "message": message, "handle": entity.dxf.get("handle")}
                for error, message, entity in logger
            ],
        },
        response_format,
    )


def dxf_disassemble(
    doc_id: str,
    layout: str | None = None,
    respect_layer_state: bool = True,
    response_format: str = "json",
) -> dict[str, Any]:
    """Recursively decompose supported geometry and report ignored source types."""
    session = store.get(doc_id)
    source = list(
        iter_entities(
            _layout(session, layout),
            session.doc,
            respect_layer_state=respect_layer_state,
        )
    )
    decomposed = list(disassemble.recursive_decompose(source))
    primitives = list(disassemble.to_primitives(decomposed))
    usable = [primitive for primitive in primitives if not primitive.is_empty]
    ignored = Counter(entity.dxftype() for entity in source if entity.dxftype() in {
        "3DSOLID", "BODY", "REGION", "XREF", "UNDERLAY", "ACAD_TABLE", "RAY", "XLINE"
    })
    return response(
        {
            "source_count": len(source),
            "decomposed_count": len(decomposed),
            "primitive_count": len(usable),
            "ignored_types": dict(ignored),
        },
        response_format,
    )


def dxf_close_contours(
    doc_id: str,
    max_gap: float,
    layout: str | None = None,
    layer: str = "CLOSURE",
    response_format: str = "json",
) -> dict[str, Any]:
    """Create explicit LINE entities between nearest dangling endpoints within max_gap."""
    session = store.get(doc_id)
    target = _layout(session, layout)
    edges = list(es.edges_from_entities_2d(es.filter_edge_entities(target), gap_tol=max_gap))
    deposit = em.Deposit(edges, gap_tol=max_gap)
    endpoints: list[Vec3] = []
    for edge in deposit.find_leafs():
        if deposit.degree(edge.start) == 1:
            endpoints.append(edge.start)
        if deposit.degree(edge.end) == 1:
            endpoints.append(edge.end)
    pairs = []
    remaining = list(endpoints)
    while remaining:
        first = remaining.pop(0)
        if not remaining:
            break
        nearest = min(remaining, key=first.distance)
        distance = first.distance(nearest)
        if distance <= max_gap:
            remaining.remove(nearest)
            pairs.append((first, nearest, distance))
    if layer not in session.doc.layers:
        session.doc.layers.new(layer)
    handles = [
        target.add_line(start, end, dxfattribs={"layer": layer}).dxf.handle
        for start, end, _ in pairs
    ]
    session.dirty = bool(handles)
    return response(
        {
            "created": handles,
            "gaps": [{"start": list(a), "end": list(b), "distance": d} for a, b, d in pairs],
        },
        response_format,
    )


def dxf_transform(
    doc_id: str,
    handles: list[str],
    matrix: list[float] | None = None,
    translate: list[float] | None = None,
    scale: list[float] | None = None,
    rotation_z_degrees: float = 0.0,
    response_format: str = "json",
) -> dict[str, Any]:
    """Apply a Matrix44 transform to selected entities and return ezdxf's failure log."""
    session = store.get(doc_id)
    entities = []
    for handle in handles:
        entity = session.doc.entitydb.get(handle.upper())
        if entity is None:
            raise ValueError(f"handle not found: {handle}")
        entities.append(entity)
    if matrix is not None:
        if len(matrix) != 16:
            raise ValueError("matrix must contain 16 row-major values")
        transform_matrix = Matrix44(matrix)
    else:
        sx, sy, sz = (scale or [1, 1, 1])
        tx, ty, tz = (translate or [0, 0, 0])
        transform_matrix = (
            Matrix44.scale(sx, sy, sz)
            @ Matrix44.z_rotate(math.radians(rotation_z_degrees))
            @ Matrix44.translate(tx, ty, tz)
        )
    logger = transform.inplace(entities, transform_matrix)
    session.dirty = bool(entities)
    return response(
        {
            "transformed": handles,
            "errors": [
                {"error": str(error), "message": message, "handle": entity.dxf.get("handle")}
                for error, message, entity in logger
            ],
        },
        response_format,
    )


def dxf_convert_to_path(
    doc_id: str,
    handles: list[str],
    max_sagitta: float = 0.01,
    layout: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Create new LWPOLYLINE approximations from selected path-capable entities."""
    session = store.get(doc_id)
    paths = []
    for handle in handles:
        entity = session.doc.entitydb.get(handle.upper())
        if entity is None:
            raise ValueError(f"handle not found: {handle}")
        paths.append(path.make_path(entity))
    created = path.render_lwpolylines(
        _layout(session, layout), paths, distance=max_sagitta
    )
    result = [entity.dxf.handle for entity in created]
    session.dirty = bool(result)
    return response({"created": result, "source_handles": handles}, response_format)


def dxf_offset_contour(
    doc_id: str,
    vertices: list[list[float]],
    offset: float,
    closed: bool = True,
    layout: str | None = None,
    layer: str = "OFFSET",
    response_format: str = "json",
) -> dict[str, Any]:
    """Create a new offset LWPOLYLINE and report achieved orientation."""
    session = store.get(doc_id)
    points = [Vec2(vertex) for vertex in vertices]
    signed_area = sum(
        points[index].det(points[(index + 1) % len(points)]) for index in range(len(points))
    ) / 2
    normalized = points if signed_area >= 0 else list(reversed(points))
    result = list(offset_vertices_2d(normalized, offset, closed=closed))
    if layer not in session.doc.layers:
        session.doc.layers.new(layer)
    entity = _layout(session, layout).add_lwpolyline(
        result, close=closed, dxfattribs={"layer": layer}
    )
    session.dirty = True
    return response(
        {
            "handle": entity.dxf.handle,
            "vertices": [list(point) for point in result],
            "source_orientation": "CCW" if signed_area >= 0 else "CW",
            "normalized_orientation": "CCW",
            "warning": "Concave offsets may self-intersect; inspect the output.",
        },
        response_format,
    )


def dxf_boolean_2d(
    doc_id: str,
    operation: str,
    polygon_a: list[list[float]],
    polygon_b: list[list[float]],
    layout: str | None = None,
    layer: str = "BOOLEAN",
    response_format: str = "json",
) -> dict[str, Any]:
    """Create new LWPOLYLINE results from Greiner-Hormann 2D boolean operations."""
    functions = {
        "union": greiner_hormann_union,
        "difference": greiner_hormann_difference,
        "intersection": greiner_hormann_intersection,
    }
    try:
        polygons = functions[operation](polygon_a, polygon_b)
    except KeyError as exc:
        raise ValueError("operation must be union, difference, or intersection") from exc
    session = store.get(doc_id)
    if layer not in session.doc.layers:
        session.doc.layers.new(layer)
    entities = [
        _layout(session, layout).add_lwpolyline(
            polygon, close=True, dxfattribs={"layer": layer}
        )
        for polygon in polygons
    ]
    session.dirty = bool(entities)
    return response(
        {
            "operation": operation,
            "handles": [entity.dxf.handle for entity in entities],
            "polygons": [[list(point) for point in polygon] for polygon in polygons],
        },
        response_format,
    )


def _corner_path(
    doc_id: str,
    points: list[list[float]],
    value: float,
    *,
    mode: str,
    closed: bool,
    layout: str | None,
    layer: str,
    response_format: str,
) -> dict[str, Any]:
    session = store.get(doc_id)
    vertices = [Vec3(point) for point in points]
    if closed and vertices[0] != vertices[-1]:
        vertices.append(vertices[0])
    result_path = path.fillet(vertices, value) if mode == "fillet" else path.chamfer(vertices, value)
    if layer not in session.doc.layers:
        session.doc.layers.new(layer)
    created = path.render_lwpolylines(
        _layout(session, layout), [result_path], dxfattribs={"layer": layer}
    )
    handles = [entity.dxf.handle for entity in created]
    session.dirty = bool(handles)
    return response({"mode": mode, "handles": handles}, response_format)


def dxf_fillet_corners(
    doc_id: str,
    points: list[list[float]],
    radius: float,
    closed: bool = True,
    layout: str | None = None,
    layer: str = "FILLET",
    response_format: str = "json",
) -> dict[str, Any]:
    """Create a new filleted path from vertices."""
    return _corner_path(
        doc_id, points, radius, mode="fillet", closed=closed, layout=layout, layer=layer,
        response_format=response_format
    )


def dxf_chamfer_corners(
    doc_id: str,
    points: list[list[float]],
    length: float,
    closed: bool = True,
    layout: str | None = None,
    layer: str = "CHAMFER",
    response_format: str = "json",
) -> dict[str, Any]:
    """Create a new chamfered path from vertices."""
    return _corner_path(
        doc_id, points, length, mode="chamfer", closed=closed, layout=layout, layer=layer,
        response_format=response_format
    )


def dxf_explode_blocks(
    doc_id: str,
    insert_handles: list[str],
    target_layout: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Explode selected INSERT entities into new layout entities."""
    session = store.get(doc_id)
    target = _layout(session, target_layout)
    created: list[str] = []
    for handle in insert_handles:
        entity = session.doc.entitydb.get(handle.upper())
        if not isinstance(entity, Insert):
            raise ValueError(f"handle is not an INSERT: {handle}")
        created.extend(item.dxf.handle for item in entity.explode(target_layout=target))
    session.dirty = bool(created)
    return response({"created": created, "exploded": insert_handles}, response_format)


def dxf_select_spatial(
    doc_id: str,
    mode: str,
    shape: str = "window",
    points: list[list[float]] | None = None,
    center: list[float] | None = None,
    radius: float | None = None,
    start_handle: str | None = None,
    layout: str | None = None,
    respect_layer_state: bool = True,
    response_format: str = "json",
) -> dict[str, Any]:
    """Select entities by window, circle, polygon, fence, or chained bounding boxes."""
    session = store.get(doc_id)
    entities = list(
        iter_entities(
            _layout(session, layout),
            session.doc,
            respect_layer_state=respect_layer_state,
        )
    )
    cache = bbox.Cache()
    if shape == "fence":
        selected = select.bbox_crosses_fence(points or [], entities, cache=cache)
    elif shape == "chained":
        if not start_handle:
            raise ValueError("chained selection requires start_handle")
        start = session.doc.entitydb.get(start_handle.upper())
        if start is None:
            raise ValueError(f"handle not found: {start_handle}")
        selected = select.bbox_chained(start, entities, cache=cache)
    else:
        if shape == "window":
            if not points or len(points) < 2:
                raise ValueError("window requires two points")
            selection_shape = select.Window(points[0], points[1])
        elif shape == "circle":
            if center is None or radius is None:
                raise ValueError("circle requires center and radius")
            selection_shape = select.Circle(center, radius)
        elif shape == "polygon":
            selection_shape = select.Polygon(points or [])
        else:
            raise ValueError("shape must be window, circle, polygon, fence, or chained")
        functions = {
            "inside": select.bbox_inside,
            "overlap": select.bbox_overlap,
            "outside": select.bbox_outside,
        }
        try:
            selected = functions[mode](selection_shape, entities, cache=cache)
        except KeyError as exc:
            raise ValueError("mode must be inside, overlap, or outside") from exc
    return response(
        {
            "handles": [entity.dxf.handle for entity in selected],
            "count": len(selected),
            "shape": shape,
            "mode": mode,
        },
        response_format,
    )


def register_tools(mcp: FastMCP) -> None:
    for read_func in (
        dxf_analyze_contours,
        dxf_sweep_tolerance,
        dxf_find_duplicates,
        dxf_check_2d_purity,
        dxf_measure_extents,
        dxf_measure_geometry,
        dxf_disassemble,
        dxf_select_spatial,
    ):
        register(mcp, read_func, read_only=True)
    for write_func in (
        dxf_normalize_extrusions,
        dxf_flatten_to_2d,
        dxf_close_contours,
        dxf_transform,
        dxf_convert_to_path,
        dxf_offset_contour,
        dxf_boolean_2d,
        dxf_fillet_corners,
        dxf_chamfer_corners,
        dxf_explode_blocks,
    ):
        register(mcp, write_func, read_only=False, idempotent=False)
