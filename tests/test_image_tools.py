from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest

from ezdxf_mcp.session import store
from ezdxf_mcp.tools.image import dxf_image_to_dxf, dxf_recognize_components


def test_png_to_dxf_with_ocr_and_spatial_relationships(workspace: Path) -> None:
    converted = dxf_image_to_dxf(
        "componentes.png",
        "converted_components.dxf",
        width_mm=200,
        curve_mode="auto",
        ocr_page_segmentation_mode=11,
        ocr_min_confidence=35,
        overwrite=True,
    )["data"]
    report = converted["report"]
    assert Path(converted["output"]).is_file()
    assert report["drawing_width_mm"] == pytest.approx(200.0)
    assert report["raw_contours"] == 3
    assert report["external_contours"] == 2
    assert report["holes"] == 1
    assert report["ocr_words"] == 2

    recognized = dxf_recognize_components(
        converted["doc_id"],
        max_relationships=100,
        component_limit=100,
        relationship_limit=100,
    )["data"]
    components = recognized["components"]["items"]
    assert recognized["component_count"] == 5
    assert recognized["semantic_counts"] == {
        "circle": 1,
        "hole": 1,
        "text": 2,
        "vector_shape": 1,
    }
    texts = {
        component["details"][0]["text"]
        for component in components
        if component["semantic_type"] == "text"
    }
    assert texts == {"MOTOR", "25"}
    outer_circle = next(
        component
        for component in components
        if component["semantic_type"] == "circle"
    )
    assert outer_circle["details"][0]["center"] == pytest.approx([140.0, 52.5, 0.0])

    relations = recognized["relationships"]["items"]
    assert any(
        relation["a"] == "vector_0002"
        and relation["b"] == "vector_0003"
        and relation["topology"] == "a_contains_b"
        for relation in relations
    )


def test_jpg_to_dxf_without_ocr(workspace: Path) -> None:
    converted = dxf_image_to_dxf(
        "componentes.jpg",
        "converted_components_jpg.dxf",
        dpi=100,
        curve_mode="line",
        run_text_ocr=False,
        minimum_area_px=40,
        overwrite=True,
    )["data"]
    assert Path(converted["output"]).is_file()
    assert converted["report"]["mm_per_pixel"] == pytest.approx(0.254)
    assert converted["report"]["ocr_words"] == 0
    reopened = ezdxf.readfile(converted["output"])
    assert len(reopened.modelspace()) > 0


def test_ocr_inside_generic_dxf_image_is_mapped_to_wcs(workspace: Path) -> None:
    doc = ezdxf.new("R2018", setup=True)
    image_definition = doc.add_image_def(
        filename="componentes.png",
        size_in_pixel=(800, 500),
    )
    image = doc.modelspace().add_image(
        insert=(10, 20),
        size_in_units=(80, 50),
        image_def=image_definition,
    )
    source_path = workspace / "generic_image.dxf"
    doc.saveas(source_path)
    session = store.add(doc, source_path=source_path, loaded_with="test")

    result = dxf_recognize_components(
        session.doc_id,
        include_image_ocr=True,
        ocr_page_segmentation_mode=11,
        ocr_min_confidence=90,
        component_limit=100,
        relationship_limit=100,
    )["data"]
    components = result["components"]["items"]
    image_component = next(
        component for component in components if component["semantic_type"] == "image"
    )
    virtual_text = [
        component
        for component in components
        if component["semantic_type"] == "text_in_image"
    ]
    assert {component["details"]["text"] for component in virtual_text} == {"MOTOR", "25"}
    assert all(
        component["parent_component_id"] == image_component["component_id"]
        for component in virtual_text
    )
    motor = next(component for component in virtual_text if component["details"]["text"] == "MOTOR")
    assert motor["bbox"]["min"] == pytest.approx([46.9, 60.7, 0.0])
    assert motor["bbox"]["max"] == pytest.approx([62.1, 64.4, 0.0])
    assert image.dxf.handle in image_component["handles"]
