"""Semantic component inventory and deterministic spatial relationships."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ezdxf import bbox, units
from ezdxf.document import Drawing
from ezdxf.entities import DXFEntity
from ezdxf.math import Vec3

from ..validation import safe_path
from .ocr import OCRWord, run_ocr
from .vectorize import IMAGE_SUFFIXES, component_metadata


def _round_point(point: Any) -> list[float]:
    vector = Vec3(point)
    return [round(vector.x, 9), round(vector.y, 9), round(vector.z, 9)]


def _bbox_from_points(points: list[Any], accuracy: str) -> dict[str, Any] | None:
    if not points:
        return None
    vectors = [Vec3(point) for point in points]
    minimum = Vec3(
        min(point.x for point in vectors),
        min(point.y for point in vectors),
        min(point.z for point in vectors),
    )
    maximum = Vec3(
        max(point.x for point in vectors),
        max(point.y for point in vectors),
        max(point.z for point in vectors),
    )
    center = (minimum + maximum) * 0.5
    size = maximum - minimum
    return {
        "min": _round_point(minimum),
        "max": _round_point(maximum),
        "center": _round_point(center),
        "size": _round_point(size),
        "accuracy": accuracy,
    }


def _generic_entity_bbox(entity: DXFEntity) -> dict[str, Any] | None:
    entity_type = entity.dxftype()
    if entity_type == "LINE":
        return _bbox_from_points(
            [entity.dxf.start, entity.dxf.end],
            "exact_entity_geometry",
        )
    if entity_type == "POINT":
        return _bbox_from_points([entity.dxf.location], "exact_entity_geometry")
    if entity_type == "CIRCLE":
        center = Vec3(entity.dxf.center)
        radius = float(entity.dxf.radius)
        return _bbox_from_points(
            [
                center - Vec3(radius, radius, 0),
                center + Vec3(radius, radius, 0),
            ],
            "exact_entity_geometry",
        )
    if entity_type == "IMAGE":
        try:
            return _bbox_from_points(
                list(entity.boundary_path_wcs()),
                "exact_image_boundary_wcs",
            )
        except (AttributeError, TypeError, ValueError):
            pass

    box = bbox.extents([entity], fast=False)
    if not box.has_data:
        return None
    accuracy = "curve_flattened_0.01"
    if entity_type in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}:
        accuracy = "approximate_font_metrics"
    return {
        "min": _round_point(box.extmin),
        "max": _round_point(box.extmax),
        "center": _round_point(box.center),
        "size": _round_point(box.size),
        "accuracy": accuracy,
    }


def _metadata_bbox(metadata: dict[str, str], doc: Drawing) -> dict[str, Any] | None:
    raw_bbox = metadata.get("pixel_bbox")
    document_metadata = doc.ezdxf_metadata()
    if not raw_bbox or document_metadata.get("IMG2DXF_SCHEMA") != "1":
        return None
    try:
        left, top, width, height = (int(value) for value in raw_bbox.split(","))
        image_height = int(document_metadata["IMG2DXF_IMAGE_HEIGHT_PX"])
        scale = float(document_metadata["IMG2DXF_MM_PER_PIXEL"])
    except (KeyError, TypeError, ValueError):
        return None
    minimum = Vec3(left * scale, (image_height - top - height) * scale, 0)
    maximum = Vec3((left + width) * scale, (image_height - top) * scale, 0)
    center = (minimum + maximum) * 0.5
    return {
        "min": _round_point(minimum),
        "max": _round_point(maximum),
        "center": _round_point(center),
        "size": _round_point(maximum - minimum),
        "accuracy": "exact_source_pixel_bbox_transformed_to_wcs",
        "source_pixel_bbox": {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
        },
    }


def _semantic_type(entity: DXFEntity, metadata: dict[str, str]) -> str:
    source_kind = metadata.get("kind")
    if source_kind:
        return {
            "ocr_text": "text",
            "raster_image": "image",
            "hole": "hole",
            "circle": "circle",
            "ellipse": "ellipse",
            "vector_shape": "vector_shape",
        }.get(source_kind, source_kind)
    return {
        "TEXT": "text",
        "MTEXT": "text",
        "ATTRIB": "text",
        "ATTDEF": "text_definition",
        "IMAGE": "image",
        "WIPEOUT": "image_mask",
        "LINE": "line",
        "RAY": "ray",
        "XLINE": "infinite_line",
        "CIRCLE": "circle",
        "ARC": "arc",
        "ELLIPSE": "ellipse",
        "LWPOLYLINE": "polyline",
        "POLYLINE": "polyline",
        "SPLINE": "spline",
        "HATCH": "filled_region",
        "INSERT": "block_reference",
        "DIMENSION": "dimension",
        "LEADER": "leader",
        "MLEADER": "multileader",
        "POINT": "point",
        "SOLID": "filled_shape",
        "TRACE": "filled_shape",
        "3DFACE": "surface",
        "MESH": "mesh",
    }.get(entity.dxftype(), "other")


def _polyline_kind(entity: DXFEntity) -> str:
    if entity.dxftype() != "LWPOLYLINE":
        return "polyline"
    points = list(entity.get_points("xyb"))
    has_arcs = any(abs(float(point[2])) > 1e-12 for point in points)
    if has_arcs:
        return "closed_polyline_with_arcs" if entity.closed else "open_polyline_with_arcs"
    if entity.closed and len(points) == 4:
        vectors = [Vec3(point[0], point[1], 0) for point in points]
        edges = [vectors[(index + 1) % 4] - vectors[index] for index in range(4)]
        if all(
            abs(edges[index].dot(edges[(index + 1) % 4])) <= 1e-8
            * max(edges[index].magnitude * edges[(index + 1) % 4].magnitude, 1.0)
            for index in range(4)
        ):
            return "rectangle"
    return "closed_polygon" if entity.closed else "open_polyline"


def _entity_details(entity: DXFEntity, max_vertices: int) -> dict[str, Any]:
    entity_type = entity.dxftype()
    details: dict[str, Any] = {}
    if entity_type == "LINE":
        details = {
            "start": _round_point(entity.dxf.start),
            "end": _round_point(entity.dxf.end),
            "length": round((Vec3(entity.dxf.end) - Vec3(entity.dxf.start)).magnitude, 9),
        }
    elif entity_type == "CIRCLE":
        details = {
            "center": _round_point(entity.dxf.center),
            "radius": round(float(entity.dxf.radius), 9),
        }
    elif entity_type == "ARC":
        details = {
            "center": _round_point(entity.dxf.center),
            "radius": round(float(entity.dxf.radius), 9),
            "start_angle": round(float(entity.dxf.start_angle), 9),
            "end_angle": round(float(entity.dxf.end_angle), 9),
        }
    elif entity_type == "ELLIPSE":
        details = {
            "center": _round_point(entity.dxf.center),
            "major_axis": _round_point(entity.dxf.major_axis),
            "ratio": round(float(entity.dxf.ratio), 9),
            "start_parameter": round(float(entity.dxf.start_param), 9),
            "end_parameter": round(float(entity.dxf.end_param), 9),
        }
    elif entity_type == "LWPOLYLINE":
        all_points = list(entity.get_points("xyseb"))
        details = {
            "shape": _polyline_kind(entity),
            "closed": bool(entity.closed),
            "vertex_count": len(all_points),
            "vertices": [
                [round(float(value), 9) for value in point]
                for point in all_points[:max_vertices]
            ],
            "vertices_truncated": len(all_points) > max_vertices,
        }
    elif entity_type in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}:
        try:
            text = entity.plain_text()
        except AttributeError:
            text = str(entity.dxf.get("text", ""))
        height_attribute = "char_height" if entity_type == "MTEXT" else "height"
        details = {
            "text": text,
            "insert": _round_point(entity.dxf.get("insert", (0, 0, 0))),
            "height": float(entity.dxf.get(height_attribute, 0.0)),
            "rotation": float(entity.dxf.get("rotation", 0.0)),
            "style": str(entity.dxf.get("style", "Standard")),
        }
    elif entity_type == "IMAGE":
        try:
            filename = entity.image_def.dxf.filename
        except (AttributeError, TypeError):
            filename = None
        details = {
            "filename": filename,
            "insert": _round_point(entity.dxf.insert),
            "image_size_px": [
                round(float(entity.dxf.image_size.x), 9),
                round(float(entity.dxf.image_size.y), 9),
            ],
            "u_pixel": _round_point(entity.dxf.u_pixel),
            "v_pixel": _round_point(entity.dxf.v_pixel),
            "boundary_wcs": [
                _round_point(point)
                for point in entity.boundary_path_wcs()
            ],
        }
    elif entity_type == "INSERT":
        details = {
            "block_name": str(entity.dxf.name),
            "insert": _round_point(entity.dxf.insert),
            "scale": [
                float(entity.dxf.xscale),
                float(entity.dxf.yscale),
                float(entity.dxf.zscale),
            ],
            "rotation": float(entity.dxf.rotation),
        }
    elif entity_type == "POINT":
        details = {"location": _round_point(entity.dxf.location)}
    return details


def _combine_bboxes(boxes: list[dict[str, Any]]) -> dict[str, Any] | None:
    boxes = [box for box in boxes if box]
    if not boxes:
        return None
    minimum = Vec3(
        min(box["min"][0] for box in boxes),
        min(box["min"][1] for box in boxes),
        min(box["min"][2] for box in boxes),
    )
    maximum = Vec3(
        max(box["max"][0] for box in boxes),
        max(box["max"][1] for box in boxes),
        max(box["max"][2] for box in boxes),
    )
    center = (minimum + maximum) * 0.5
    accuracy_values = sorted({str(box["accuracy"]) for box in boxes})
    return {
        "min": _round_point(minimum),
        "max": _round_point(maximum),
        "center": _round_point(center),
        "size": _round_point(maximum - minimum),
        "accuracy": accuracy_values[0] if len(accuracy_values) == 1 else "mixed",
        "accuracy_sources": accuracy_values,
    }


def _resolve_image_file(filename: str, source_path: Path | None) -> Path:
    candidate = Path(filename)
    if not candidate.is_absolute() and source_path is not None:
        candidate = source_path.parent / candidate
    return safe_path(
        str(candidate),
        must_exist=True,
        suffixes=IMAGE_SUFFIXES,
    )


def _map_image_word(entity: DXFEntity, word: OCRWord) -> tuple[list[list[float]], dict[str, Any]]:
    image_height = float(entity.dxf.image_size.y)
    insertion = Vec3(entity.dxf.insert)
    u_pixel = Vec3(entity.dxf.u_pixel)
    v_pixel = Vec3(entity.dxf.v_pixel)
    left = float(word.left)
    right = float(word.left + word.width)
    bottom = image_height - float(word.top + word.height)
    top = image_height - float(word.top)

    def transform(x: float, y: float) -> Vec3:
        return insertion + u_pixel * x + v_pixel * y

    polygon = [
        transform(left, bottom),
        transform(right, bottom),
        transform(right, top),
        transform(left, top),
    ]
    box = _bbox_from_points(polygon, "exact_ocr_pixel_bbox_transformed_by_image_axes")
    if box is None:
        raise ValueError("OCR word produced no spatial bounding box")
    return [_round_point(point) for point in polygon], box


def _add_image_ocr_components(
    components: list[dict[str, Any]],
    grouped_entities: dict[str, list[DXFEntity]],
    source_path: Path | None,
    *,
    language: str,
    page_segmentation_mode: int,
    min_confidence: float,
    timeout: float,
    warnings: list[str],
) -> None:
    additions: list[dict[str, Any]] = []
    for component in components:
        if component["semantic_type"] != "image":
            continue
        entities = grouped_entities.get(component["component_id"], [])
        if not entities:
            continue
        entity = entities[0]
        metadata = component_metadata(entity)
        if metadata.get("kind") == "raster_image" and any(
            existing["semantic_type"] == "text" for existing in components
        ):
            continue
        try:
            filename = str(entity.image_def.dxf.filename)
            image_path = _resolve_image_file(filename, source_path)
            words = run_ocr(
                image_path,
                language=language,
                page_segmentation_mode=page_segmentation_mode,
                min_confidence=min_confidence,
                timeout=timeout,
            )
        except Exception as exc:
            warnings.append(
                f"could not OCR IMAGE component {component['component_id']}: "
                f"{type(exc).__name__}: {exc}"
            )
            continue
        for index, word in enumerate(words, start=1):
            polygon, word_bbox = _map_image_word(entity, word)
            additions.append(
                {
                    "component_id": f"{component['component_id']}:text:{index:04d}",
                    "handles": [],
                    "entity_types": ["VIRTUAL_OCR_WORD"],
                    "semantic_type": "text_in_image",
                    "layer": component["layer"],
                    "parent_component_id": component["component_id"],
                    "bbox": word_bbox,
                    "details": {
                        "text": word.text,
                        "confidence": word.confidence,
                        "source_image": filename,
                        "pixel_bbox": word.as_dict()["pixel_bbox"],
                        "boundary_wcs": polygon,
                    },
                    "source": "tesseract_tsv",
                }
            )
    components.extend(additions)


def _direction(delta_x: float, delta_y: float, tolerance: float) -> str:
    horizontal = "" if abs(delta_x) <= tolerance else ("right" if delta_x > 0 else "left")
    vertical = "" if abs(delta_y) <= tolerance else ("above" if delta_y > 0 else "below")
    if horizontal and vertical:
        return f"{vertical}_{horizontal}"
    return horizontal or vertical or "same_center"


def _contains(a: dict[str, Any], b: dict[str, Any], tolerance: float) -> bool:
    return (
        a["min"][0] <= b["min"][0] + tolerance
        and a["min"][1] <= b["min"][1] + tolerance
        and a["max"][0] >= b["max"][0] - tolerance
        and a["max"][1] >= b["max"][1] - tolerance
    )


def _pair_relation(
    first: dict[str, Any],
    second: dict[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    box_a = first["bbox"]
    box_b = second["bbox"]
    delta_x = box_b["center"][0] - box_a["center"][0]
    delta_y = box_b["center"][1] - box_a["center"][1]
    gap_x = max(box_a["min"][0] - box_b["max"][0], box_b["min"][0] - box_a["max"][0], 0)
    gap_y = max(box_a["min"][1] - box_b["max"][1], box_b["min"][1] - box_a["max"][1], 0)
    boundary_distance = math.hypot(gap_x, gap_y)
    center_distance = math.hypot(delta_x, delta_y)
    overlap_width = max(
        0.0,
        min(box_a["max"][0], box_b["max"][0])
        - max(box_a["min"][0], box_b["min"][0]),
    )
    overlap_height = max(
        0.0,
        min(box_a["max"][1], box_b["max"][1])
        - max(box_a["min"][1], box_b["min"][1]),
    )
    a_contains_b = _contains(box_a, box_b, tolerance)
    b_contains_a = _contains(box_b, box_a, tolerance)
    if a_contains_b and b_contains_a:
        topology = "coincident_bounds"
    elif a_contains_b:
        topology = "a_contains_b"
    elif b_contains_a:
        topology = "b_contains_a"
    elif overlap_width > tolerance and overlap_height > tolerance:
        topology = "overlaps"
    elif boundary_distance <= tolerance:
        topology = "touches"
    else:
        topology = "disjoint"
    return {
        "a": first["component_id"],
        "b": second["component_id"],
        "topology": topology,
        "b_relative_to_a": _direction(delta_x, delta_y, tolerance),
        "delta_center": [round(delta_x, 9), round(delta_y, 9), 0.0],
        "center_distance": round(center_distance, 9),
        "boundary_distance": round(boundary_distance, 9),
        "overlap_size": [round(overlap_width, 9), round(overlap_height, 9)],
        "basis": "axis_aligned_component_bounds_in_wcs",
    }


def recognize_components(
    doc: Drawing,
    *,
    layout: Any,
    source_path: Path | None,
    include_image_ocr: bool = True,
    ocr_language: str = "por+eng",
    ocr_page_segmentation_mode: int = 11,
    ocr_min_confidence: float = 50.0,
    ocr_timeout: float = 60.0,
    relationship_tolerance: float = 0.01,
    max_relationships: int = 5000,
    max_vertices: int = 100,
) -> dict[str, Any]:
    """Inventory components and calculate pairwise WCS relationships."""
    if relationship_tolerance < 0:
        raise ValueError("relationship_tolerance must be >= 0")
    if not 1 <= max_relationships <= 100_000:
        raise ValueError("max_relationships must be between 1 and 100000")
    if not 1 <= max_vertices <= 10_000:
        raise ValueError("max_vertices must be between 1 and 10000")

    groups: dict[str, list[DXFEntity]] = defaultdict(list)
    for entity in layout:
        metadata = component_metadata(entity)
        component_id = metadata.get("component_id") or f"entity_{entity.dxf.handle}"
        groups[component_id].append(entity)

    components: list[dict[str, Any]] = []
    for component_id, entities in groups.items():
        first = entities[0]
        metadata = component_metadata(first)
        metadata_box = _metadata_bbox(metadata, doc)
        entity_boxes = [_generic_entity_bbox(entity) for entity in entities]
        component_box = metadata_box or _combine_bboxes(
            [box for box in entity_boxes if box is not None]
        )
        components.append(
            {
                "component_id": component_id,
                "handles": [
                    entity.dxf.handle
                    for entity in entities
                    if entity.dxf.handle is not None
                ],
                "entity_types": [entity.dxftype() for entity in entities],
                "semantic_type": _semantic_type(first, metadata),
                "layer": str(first.dxf.get("layer", "0")),
                "parent_component_id": metadata.get("parent_component_id"),
                "bbox": component_box,
                "details": [_entity_details(entity, max_vertices) for entity in entities],
                "source_metadata": metadata or None,
                "source": "img2dxf_metadata" if metadata else "generic_dxf_entity",
            }
        )

    warnings: list[str] = []
    if include_image_ocr:
        _add_image_ocr_components(
            components,
            groups,
            source_path,
            language=ocr_language,
            page_segmentation_mode=ocr_page_segmentation_mode,
            min_confidence=ocr_min_confidence,
            timeout=ocr_timeout,
            warnings=warnings,
        )
    components.sort(key=lambda component: component["component_id"])

    positioned = [component for component in components if component["bbox"] is not None]
    unpositioned = [
        component["component_id"] for component in components if component["bbox"] is None
    ]
    relationships: list[dict[str, Any]] = []
    truncated = False
    for first_index, first in enumerate(positioned):
        for second in positioned[first_index + 1 :]:
            if len(relationships) >= max_relationships:
                truncated = True
                break
            relationships.append(_pair_relation(first, second, relationship_tolerance))
        if truncated:
            break

    nearest: dict[str, dict[str, Any]] = {}
    for relationship in relationships:
        for source_key, target_key in (("a", "b"), ("b", "a")):
            component_id = relationship[source_key]
            candidate = {
                "component_id": relationship[target_key],
                "boundary_distance": relationship["boundary_distance"],
                "center_distance": relationship["center_distance"],
            }
            previous = nearest.get(component_id)
            if previous is None or (
                candidate["boundary_distance"],
                candidate["center_distance"],
                candidate["component_id"],
            ) < (
                previous["boundary_distance"],
                previous["center_distance"],
                previous["component_id"],
            ):
                nearest[component_id] = candidate
    for component in components:
        component["nearest_component"] = nearest.get(component["component_id"])

    semantic_counts = Counter(
        component["semantic_type"] for component in components
    )
    unit_code = int(doc.units)
    return {
        "coordinate_system": "WCS XY",
        "drawing_units": {
            "code": unit_code,
            "name": units.unit_name(unit_code),
        },
        "components": components,
        "component_count": len(components),
        "positioned_component_count": len(positioned),
        "unpositioned_components": unpositioned,
        "semantic_counts": dict(sorted(semantic_counts.items())),
        "relationships": relationships,
        "relationship_count": len(relationships),
        "relationships_truncated": truncated,
        "relationship_tolerance": relationship_tolerance,
        "relationship_basis": (
            "axis-aligned WCS component bounds; each component reports its own "
            "bbox accuracy source"
        ),
        "warnings": warnings,
    }
