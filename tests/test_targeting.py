from __future__ import annotations

import math
from pathlib import Path

from ezdxf_mcp.api.calibration import map_wcs_to_screen
from ezdxf_mcp.image.spatial import recognize_components
from ezdxf_mcp.image.targeting import select_component_target
from ezdxf_mcp.image.vectorize import ImageVectorizationConfig, vectorize_image


def _converted_components(image_path: Path):
    document, _report = vectorize_image(
        image_path,
        ImageVectorizationConfig(
            width_mm=200,
            run_text_ocr=False,
            curve_mode="line",
            minimum_area_px=20,
        ),
    )
    recognized = recognize_components(
        document,
        layout=document.modelspace(),
        source_path=None,
        include_image_ocr=False,
    )
    return document, recognized["components"]


def test_interior_target_avoids_child_hole(workspace: Path) -> None:
    document, components = _converted_components(workspace / "componentes.png")
    outer = next(
        component
        for component in components
        if component["semantic_type"] == "vector_shape"
    )
    hole = next(
        component for component in components if component["semantic_type"] == "hole"
    )
    assert hole["parent_component_id"] == outer["component_id"]

    target = select_component_target(
        layout=document.modelspace(),
        components=components,
        component_id=outer["component_id"],
        strategy="interior",
    )
    x, y, _z = target["point_wcs"]
    hole_center = hole["bbox"]["center"]
    hole_radius = hole["bbox"]["size"][0] * 0.5
    assert target["inside_component"] is True
    assert target["excluded_hole_count"] == 1
    assert math.hypot(x - hole_center[0], y - hole_center[1]) > hole_radius


def test_circle_target_uses_exact_center(workspace: Path) -> None:
    document, components = _converted_components(workspace / "componentes.png")
    circle = next(
        component for component in components if component["semantic_type"] == "circle"
    )
    target = select_component_target(
        layout=document.modelspace(),
        components=components,
        component_id=circle["component_id"],
        strategy="interior",
    )
    assert target["point_wcs"] == [140.0, 52.5, 0.0]
    assert target["basis"].startswith("interior:exact_circle")


def test_viewport_calibration_inverts_cartesian_y() -> None:
    result = map_wcs_to_screen(
        [50.0, 25.0, 0.0],
        {
            "mode": "viewport",
            "fit": "stretch",
            "screen": {"left": 100, "top": 50, "width": 1000, "height": 500},
        },
        {"min": [0.0, 0.0, 0.0], "max": [100.0, 50.0, 0.0]},
    )
    assert result["screen_pixel"] == {"x": 600, "y": 300}
    assert result["transform"]["y_axis_inverted"] is True


def test_affine_calibration_maps_rotated_drawing() -> None:
    result = map_wcs_to_screen(
        [5.0, 5.0, 0.0],
        {
            "mode": "affine",
            "screen": {"left": 0, "top": 0, "width": 500, "height": 500},
            "pairs": [
                {"drawing": [0, 0], "screen": [100, 100]},
                {"drawing": [10, 0], "screen": [100, 200]},
                {"drawing": [0, 10], "screen": [200, 100]},
            ],
        },
        {"min": [0.0, 0.0, 0.0], "max": [10.0, 10.0, 0.0]},
    )
    assert result["screen_pixel"] == {"x": 150, "y": 150}
    assert result["transform"]["mode"] == "affine"
