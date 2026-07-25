"""Map DXF WCS coordinates into physical screen pixels."""

from __future__ import annotations

import math
from typing import Any


def _finite(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _round_pixel(value: float) -> int:
    return math.floor(value + 0.5)


def _screen_bounds(calibration: dict[str, Any]) -> tuple[int, int, int, int]:
    screen = calibration.get("screen")
    if not isinstance(screen, dict):
        raise ValueError("calibration.screen is required")
    left = int(screen.get("left", 0))
    top = int(screen.get("top", 0))
    width = int(screen.get("width", 0))
    height = int(screen.get("height", 0))
    if left < 0 or top < 0 or width <= 0 or height <= 0:
        raise ValueError("screen rectangle must have non-negative origin and positive size")
    return left, top, width, height


def _map_viewport(
    point: tuple[float, float],
    calibration: dict[str, Any],
    drawing_bounds: dict[str, list[float]],
) -> tuple[float, float, dict[str, Any]]:
    left, top, screen_width, screen_height = _screen_bounds(calibration)
    supplied_bounds = calibration.get("drawing")
    bounds = supplied_bounds if isinstance(supplied_bounds, dict) else drawing_bounds
    minimum = bounds.get("min")
    maximum = bounds.get("max")
    if not isinstance(minimum, list) or not isinstance(maximum, list):
        raise ValueError("drawing bounds require min/max")
    min_x = _finite(minimum[0], "drawing.min.x")
    min_y = _finite(minimum[1], "drawing.min.y")
    max_x = _finite(maximum[0], "drawing.max.x")
    max_y = _finite(maximum[1], "drawing.max.y")
    drawing_width = max_x - min_x
    drawing_height = max_y - min_y
    if drawing_width <= 0 or drawing_height <= 0:
        raise ValueError("drawing bounds must have positive width and height")
    fit = str(calibration.get("fit", "contain"))
    if fit not in {"contain", "stretch"}:
        raise ValueError("viewport fit must be contain or stretch")
    if fit == "stretch":
        scale_x = screen_width / drawing_width
        scale_y = screen_height / drawing_height
        offset_x = float(left)
        offset_y = float(top)
    else:
        scale_x = scale_y = min(
            screen_width / drawing_width,
            screen_height / drawing_height,
        )
        offset_x = left + (screen_width - drawing_width * scale_x) * 0.5
        offset_y = top + (screen_height - drawing_height * scale_y) * 0.5
    screen_x = offset_x + (point[0] - min_x) * scale_x
    screen_y = offset_y + (max_y - point[1]) * scale_y
    return screen_x, screen_y, {
        "mode": "viewport",
        "fit": fit,
        "scale_x": scale_x,
        "scale_y": scale_y,
        "offset_x": offset_x,
        "offset_y": offset_y,
        "y_axis_inverted": True,
        "drawing_bounds": {"min": [min_x, min_y], "max": [max_x, max_y]},
    }


def _affine_coefficients(
    pairs: list[dict[str, Any]],
    output_axis: int,
) -> tuple[float, float, float]:
    if len(pairs) != 3:
        raise ValueError("affine calibration requires exactly three point pairs")
    points = []
    values = []
    for index, pair in enumerate(pairs):
        drawing = pair.get("drawing")
        screen = pair.get("screen")
        if not isinstance(drawing, list) or not isinstance(screen, list):
            raise ValueError(f"affine pair {index} requires drawing and screen")
        points.append(
            (
                _finite(drawing[0], f"pair[{index}].drawing.x"),
                _finite(drawing[1], f"pair[{index}].drawing.y"),
            )
        )
        values.append(_finite(screen[output_axis], f"pair[{index}].screen[{output_axis}]"))
    (x1, y1), (x2, y2), (x3, y3) = points
    determinant = x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2)
    if abs(determinant) <= 1e-12:
        raise ValueError("affine drawing points must not be collinear")
    z1, z2, z3 = values
    coefficient_x = (z1 * (y2 - y3) + z2 * (y3 - y1) + z3 * (y1 - y2)) / determinant
    coefficient_y = (z1 * (x3 - x2) + z2 * (x1 - x3) + z3 * (x2 - x1)) / determinant
    constant = (
        z1 * (x2 * y3 - x3 * y2)
        + z2 * (x3 * y1 - x1 * y3)
        + z3 * (x1 * y2 - x2 * y1)
    ) / determinant
    return coefficient_x, coefficient_y, constant


def _map_affine(
    point: tuple[float, float],
    calibration: dict[str, Any],
) -> tuple[float, float, dict[str, Any]]:
    _screen_bounds(calibration)
    pairs = calibration.get("pairs")
    if not isinstance(pairs, list):
        raise ValueError("affine calibration requires pairs")
    x_coefficients = _affine_coefficients(pairs, 0)
    y_coefficients = _affine_coefficients(pairs, 1)

    def transform(coefficients: tuple[float, float, float]) -> float:
        return (
            coefficients[0] * point[0]
            + coefficients[1] * point[1]
            + coefficients[2]
        )

    return transform(x_coefficients), transform(y_coefficients), {
        "mode": "affine",
        "x_coefficients": list(x_coefficients),
        "y_coefficients": list(y_coefficients),
        "pairs": pairs,
    }


def map_wcs_to_screen(
    point_wcs: list[float],
    calibration: dict[str, Any],
    drawing_bounds: dict[str, list[float]],
) -> dict[str, Any]:
    """Transform WCS XY into a validated integer screen pixel."""
    if len(point_wcs) < 2:
        raise ValueError("point_wcs requires x and y")
    point = (_finite(point_wcs[0], "point_wcs.x"), _finite(point_wcs[1], "point_wcs.y"))
    mode = str(calibration.get("mode", "viewport"))
    if mode == "viewport":
        raw_x, raw_y, transform = _map_viewport(point, calibration, drawing_bounds)
    elif mode == "affine":
        raw_x, raw_y, transform = _map_affine(point, calibration)
    else:
        raise ValueError("calibration mode must be viewport or affine")
    pixel_x = _round_pixel(raw_x)
    pixel_y = _round_pixel(raw_y)
    left, top, width, height = _screen_bounds(calibration)
    if not left <= pixel_x < left + width or not top <= pixel_y < top + height:
        raise ValueError(
            f"mapped pixel ({pixel_x}, {pixel_y}) falls outside calibrated screen rectangle"
        )
    return {
        "point_wcs": [point[0], point[1], float(point_wcs[2]) if len(point_wcs) > 2 else 0.0],
        "screen_pixel": {"x": pixel_x, "y": pixel_y},
        "raw_screen_pixel": {"x": raw_x, "y": raw_y},
        "transform": transform,
        "screen": {"left": left, "top": top, "width": width, "height": height},
    }
