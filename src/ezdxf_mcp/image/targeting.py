"""Select deterministic Cartesian target points inside recognized DXF components."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ezdxf import path as ezpath
from ezdxf.entities import DXFEntity
from ezdxf.math import Vec3

from .vectorize import component_metadata

Point2D = tuple[float, float]
TARGET_STRATEGIES = {"interior", "center", "boundary", "text_baseline", "relative"}


def _distance(first: Point2D, second: Point2D) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def _point_segment_distance(point: Point2D, start: Point2D, end: Point2D) -> float:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared <= 1e-24:
        return _distance(point, start)
    projection = (
        (point[0] - start[0]) * delta_x + (point[1] - start[1]) * delta_y
    ) / length_squared
    projection = max(0.0, min(1.0, projection))
    closest = (start[0] + projection * delta_x, start[1] + projection * delta_y)
    return _distance(point, closest)


class Region:
    """Closed planar region used by the target selection algorithm."""

    def contains(self, point: Point2D, tolerance: float = 1e-9) -> bool:
        raise NotImplementedError

    def boundary_distance(self, point: Point2D) -> float:
        raise NotImplementedError

    def boundary_point(self) -> Point2D:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class CircleRegion(Region):
    center: Point2D
    radius: float

    def contains(self, point: Point2D, tolerance: float = 1e-9) -> bool:
        return _distance(point, self.center) <= self.radius + tolerance

    def boundary_distance(self, point: Point2D) -> float:
        return abs(_distance(point, self.center) - self.radius)

    def boundary_point(self) -> Point2D:
        return self.center[0] + self.radius, self.center[1]


@dataclass(frozen=True, slots=True)
class PolygonRegion(Region):
    vertices: tuple[Point2D, ...]

    def contains(self, point: Point2D, tolerance: float = 1e-9) -> bool:
        inside = False
        previous = self.vertices[-1]
        for current in self.vertices:
            if _point_segment_distance(point, previous, current) <= tolerance:
                return True
            crosses = (current[1] > point[1]) != (previous[1] > point[1])
            if crosses:
                denominator = previous[1] - current[1]
                intersection_x = (
                    (previous[0] - current[0])
                    * (point[1] - current[1])
                    / denominator
                    + current[0]
                )
                if point[0] < intersection_x:
                    inside = not inside
            previous = current
        return inside

    def boundary_distance(self, point: Point2D) -> float:
        return min(
            _point_segment_distance(point, self.vertices[index - 1], vertex)
            for index, vertex in enumerate(self.vertices)
        )

    def boundary_point(self) -> Point2D:
        start = self.vertices[0]
        end = self.vertices[1]
        return (start[0] + end[0]) * 0.5, (start[1] + end[1]) * 0.5


@dataclass(frozen=True, slots=True)
class BoxRegion(Region):
    minimum: Point2D
    maximum: Point2D

    def contains(self, point: Point2D, tolerance: float = 1e-9) -> bool:
        return (
            self.minimum[0] - tolerance <= point[0] <= self.maximum[0] + tolerance
            and self.minimum[1] - tolerance <= point[1] <= self.maximum[1] + tolerance
        )

    def boundary_distance(self, point: Point2D) -> float:
        if self.contains(point):
            return min(
                point[0] - self.minimum[0],
                self.maximum[0] - point[0],
                point[1] - self.minimum[1],
                self.maximum[1] - point[1],
            )
        closest = (
            max(self.minimum[0], min(self.maximum[0], point[0])),
            max(self.minimum[1], min(self.maximum[1], point[1])),
        )
        return _distance(point, closest)

    def boundary_point(self) -> Point2D:
        return self.maximum[0], (self.minimum[1] + self.maximum[1]) * 0.5


def _component_box(component: dict[str, Any]) -> BoxRegion:
    box = component.get("bbox")
    if not isinstance(box, dict):
        raise ValueError(f"component {component.get('component_id')} has no spatial bbox")
    return BoxRegion(
        (float(box["min"][0]), float(box["min"][1])),
        (float(box["max"][0]), float(box["max"][1])),
    )


def _flatten_entity(entity: DXFEntity, distance: float = 0.01) -> list[Point2D]:
    try:
        path = ezpath.make_path(entity)
        return [(float(point.x), float(point.y)) for point in path.flattening(distance)]
    except (AttributeError, TypeError, ValueError):
        return []


def _join_entity_paths(entities: list[DXFEntity]) -> list[Point2D]:
    chain: list[Point2D] = []
    for entity in entities:
        points = _flatten_entity(entity)
        if not points:
            continue
        if chain and _distance(chain[-1], points[-1]) < _distance(chain[-1], points[0]):
            points.reverse()
        if chain and _distance(chain[-1], points[0]) <= 1e-7:
            points = points[1:]
        chain.extend(points)
    if len(chain) >= 3 and _distance(chain[0], chain[-1]) <= 1e-5:
        chain.pop()
    return chain


def _region_from_entities(
    entities: list[DXFEntity],
    fallback: BoxRegion,
) -> tuple[Region, str]:
    if len(entities) == 1 and entities[0].dxftype() == "CIRCLE":
        entity = entities[0]
        center = Vec3(entity.dxf.center)
        return (
            CircleRegion((float(center.x), float(center.y)), float(entity.dxf.radius)),
            "exact_circle",
        )
    points = _join_entity_paths(entities)
    if len(points) >= 3:
        return PolygonRegion(tuple(points)), "flattened_closed_entity_paths"
    return fallback, "component_bbox_fallback"


def _entities_for_component(layout: Iterable[DXFEntity], component_id: str) -> list[DXFEntity]:
    result: list[DXFEntity] = []
    for entity in layout:
        metadata = component_metadata(entity)
        entity_component_id = metadata.get("component_id") or f"entity_{entity.dxf.handle}"
        if entity_component_id == component_id:
            result.append(entity)
    return result


def _component_children(
    component: dict[str, Any],
    components: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    component_id = str(component["component_id"])
    metadata = component.get("source_metadata") or {}
    contour_index = str(metadata.get("contour_index", ""))
    children = []
    for candidate in components:
        if candidate.get("semantic_type") != "hole":
            continue
        candidate_metadata = candidate.get("source_metadata") or {}
        direct_parent = candidate.get("parent_component_id") or candidate_metadata.get(
            "parent_component_id"
        )
        contour_parent = str(candidate_metadata.get("contour_parent_index", ""))
        if direct_parent == component_id or (
            contour_index and contour_parent == contour_index
        ):
            children.append(candidate)
    return children


def _polygon_centroid(vertices: tuple[Point2D, ...]) -> Point2D | None:
    twice_area = 0.0
    weighted_x = 0.0
    weighted_y = 0.0
    for index, current in enumerate(vertices):
        following = vertices[(index + 1) % len(vertices)]
        cross = current[0] * following[1] - following[0] * current[1]
        twice_area += cross
        weighted_x += (current[0] + following[0]) * cross
        weighted_y += (current[1] + following[1]) * cross
    if abs(twice_area) <= 1e-18:
        return None
    return weighted_x / (3.0 * twice_area), weighted_y / (3.0 * twice_area)


def _valid_interior(point: Point2D, outer: Region, holes: list[Region]) -> bool:
    return outer.contains(point) and not any(hole.contains(point) for hole in holes)


def _safe_interior_point(
    outer: Region,
    holes: list[Region],
    bounds: BoxRegion,
    *,
    grid_size: int = 41,
) -> tuple[Point2D, str]:
    candidates: list[Point2D] = [
        (
            (bounds.minimum[0] + bounds.maximum[0]) * 0.5,
            (bounds.minimum[1] + bounds.maximum[1]) * 0.5,
        )
    ]
    if isinstance(outer, CircleRegion):
        candidates.insert(0, outer.center)
    elif isinstance(outer, PolygonRegion):
        centroid = _polygon_centroid(outer.vertices)
        if centroid is not None:
            candidates.insert(0, centroid)

    valid_candidates = [
        candidate for candidate in candidates if _valid_interior(candidate, outer, holes)
    ]
    if valid_candidates and not holes:
        return valid_candidates[0], "analytic_or_centroid"

    width = bounds.maximum[0] - bounds.minimum[0]
    height = bounds.maximum[1] - bounds.minimum[1]
    for row in range(grid_size):
        y = bounds.minimum[1] + (row + 0.5) * height / grid_size
        for column in range(grid_size):
            x = bounds.minimum[0] + (column + 0.5) * width / grid_size
            candidate = (x, y)
            if _valid_interior(candidate, outer, holes):
                valid_candidates.append(candidate)
    if not valid_candidates:
        raise ValueError("could not find a safe interior point for the component")

    def clearance(point: Point2D) -> tuple[float, float, float]:
        distances = [outer.boundary_distance(point)]
        distances.extend(hole.boundary_distance(point) for hole in holes)
        center = candidates[0]
        return min(distances), -_distance(point, center), -point[1]

    return max(valid_candidates, key=clearance), "maximum_clearance_grid_41"


def select_component_target(
    *,
    layout: Iterable[DXFEntity],
    components: list[dict[str, Any]],
    component_id: str,
    strategy: str = "interior",
    relative_x: float = 0.5,
    relative_y: float = 0.5,
) -> dict[str, Any]:
    """Return a deterministic WCS target for one recognized component."""
    if strategy not in TARGET_STRATEGIES:
        raise ValueError(f"strategy must be one of {sorted(TARGET_STRATEGIES)}")
    component = next(
        (item for item in components if item.get("component_id") == component_id),
        None,
    )
    if component is None:
        raise KeyError(f"unknown component_id: {component_id}")
    bounds = _component_box(component)
    entities = _entities_for_component(layout, component_id)
    outer, geometry_basis = _region_from_entities(entities, bounds)
    center = (
        (bounds.minimum[0] + bounds.maximum[0]) * 0.5,
        (bounds.minimum[1] + bounds.maximum[1]) * 0.5,
    )

    holes: list[Region] = []
    for child in _component_children(component, components):
        child_bounds = _component_box(child)
        child_entities = _entities_for_component(layout, str(child["component_id"]))
        child_region, _ = _region_from_entities(child_entities, child_bounds)
        holes.append(child_region)

    basis = "component_bbox_center"
    if strategy == "center":
        target = center
    elif strategy == "relative":
        if not 0.0 <= relative_x <= 1.0 or not 0.0 <= relative_y <= 1.0:
            raise ValueError("relative_x and relative_y must be between 0 and 1")
        target = (
            bounds.minimum[0]
            + relative_x * (bounds.maximum[0] - bounds.minimum[0]),
            bounds.minimum[1]
            + relative_y * (bounds.maximum[1] - bounds.minimum[1]),
        )
        basis = "relative_component_bbox"
    elif strategy == "boundary":
        target = outer.boundary_point()
        basis = f"boundary:{geometry_basis}"
    elif strategy == "text_baseline":
        details = component.get("details")
        detail = details[0] if isinstance(details, list) and details else details
        insertion = detail.get("insert") if isinstance(detail, dict) else None
        if not insertion:
            raise ValueError("component has no text baseline/insertion point")
        target = float(insertion[0]), float(insertion[1])
        basis = "text_insertion_point"
    else:
        target, interior_basis = _safe_interior_point(outer, holes, bounds)
        basis = f"interior:{geometry_basis}:{interior_basis}"

    inside = _valid_interior(target, outer, holes)
    return {
        "component_id": component_id,
        "semantic_type": component.get("semantic_type"),
        "strategy": strategy,
        "point_wcs": [round(target[0], 9), round(target[1], 9), 0.0],
        "inside_component": inside,
        "basis": basis,
        "excluded_hole_count": len(holes),
        "bbox_accuracy": (component.get("bbox") or {}).get("accuracy"),
    }
