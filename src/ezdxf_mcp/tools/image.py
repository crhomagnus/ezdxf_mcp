"""Image vectorization, OCR text creation, and spatial component recognition."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..config import settings
from ..formatting import paginate, response
from ..image.spatial import recognize_components
from ..image.vectorize import (
    IMAGE_SUFFIXES,
    ImageVectorizationConfig,
    vectorize_image,
)
from ..registry import register
from ..session import store
from ..validation import require_overwrite, safe_path
from .semantics import _layout

_PRIMITIVE_NAMES = {
    "circle": "circulo",
    "ellipse": "elipse",
    "line": "reta",
    "arc": "arco",
    "bezier": "bezier",
}


def dxf_image_to_dxf(
    image_path: str,
    output_path: str,
    width_mm: float | None = None,
    dpi: float | None = None,
    mm_per_pixel: float | None = None,
    curve_mode: str = "auto",
    binarization: str = "otsu",
    threshold: int = 127,
    invert: bool = False,
    blur: int = 3,
    canny_low: int = 50,
    canny_high: int = 150,
    fit_tolerance_px: float = 0.8,
    max_arc_angle: float = 120.0,
    simplify_fraction: float = 0.002,
    minimum_area_px: float = 20.0,
    allowed_primitives: list[str] | None = None,
    run_text_ocr: bool = True,
    ocr_language: str = "por+eng",
    ocr_page_segmentation_mode: int = 11,
    ocr_min_confidence: float = 50.0,
    ocr_max_height_fraction: float = 0.25,
    ocr_max_area_fraction: float = 0.20,
    exclude_ocr_from_vectors: bool = True,
    include_raster_reference: bool = False,
    dxf_version: str = "R2018",
    overwrite: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Convert workspace PNG/JPG pixels into native DXF vectors and positioned OCR TEXT."""
    source = safe_path(image_path, must_exist=True, suffixes=IMAGE_SUFFIXES)
    size_mb = source.stat().st_size / (1024 * 1024)
    if size_mb > settings.max_file_mb:
        raise ValueError(
            f"image is {size_mb:.1f} MB; configured limit is {settings.max_file_mb} MB"
        )
    target = safe_path(output_path, suffixes={".dxf"})
    require_overwrite(target, overwrite)

    requested = allowed_primitives or list(_PRIMITIVE_NAMES)
    unknown = sorted(set(requested) - set(_PRIMITIVE_NAMES))
    if unknown:
        raise ValueError(
            f"unknown allowed_primitives {unknown}; choose from {sorted(_PRIMITIVE_NAMES)}"
        )
    config = ImageVectorizationConfig(
        binarization=binarization,
        threshold=threshold,
        invert=invert,
        blur=blur,
        canny_low=canny_low,
        canny_high=canny_high,
        curve_mode=curve_mode,
        allowed_primitives={_PRIMITIVE_NAMES[name] for name in requested},
        fit_tolerance_px=fit_tolerance_px,
        max_arc_angle=max_arc_angle,
        simplify_fraction=simplify_fraction,
        minimum_area_px=minimum_area_px,
        width_mm=width_mm,
        dpi=dpi,
        mm_per_pixel=mm_per_pixel,
        dxf_version=dxf_version,
        run_text_ocr=run_text_ocr,
        ocr_language=ocr_language,
        ocr_page_segmentation_mode=ocr_page_segmentation_mode,
        ocr_min_confidence=ocr_min_confidence,
        ocr_max_height_fraction=ocr_max_height_fraction,
        ocr_max_area_fraction=ocr_max_area_fraction,
        ocr_timeout=settings.default_timeout,
        exclude_ocr_from_vectors=exclude_ocr_from_vectors,
        include_raster_reference=include_raster_reference,
    )
    doc, report = vectorize_image(
        source,
        config,
        raster_reference_base=target.parent,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(target)
    session = store.add(
        doc,
        source_path=target,
        loaded_with="image_to_dxf",
        warnings=list(report.warnings),
    )
    return response(
        {
            "doc_id": session.doc_id,
            "output": str(target),
            "bytes": target.stat().st_size,
            "source_image": str(source),
            "source_session_mutated": False,
            "report": report.as_dict(),
        },
        response_format,
    )


def dxf_recognize_components(
    doc_id: str,
    layout: str | None = None,
    include_image_ocr: bool = True,
    ocr_language: str = "por+eng",
    ocr_page_segmentation_mode: int = 11,
    ocr_min_confidence: float = 50.0,
    relationship_tolerance: float = 0.01,
    max_relationships: int = 5000,
    max_vertices: int = 100,
    component_limit: int = 1000,
    component_offset: int = 0,
    relationship_limit: int = 5000,
    relationship_offset: int = 0,
    response_format: str = "json",
) -> dict[str, Any]:
    """Identify DXF text/images/geometry and their exact WCS positions and relations."""
    session = store.get(doc_id)
    result = recognize_components(
        session.doc,
        layout=_layout(session, layout),
        source_path=session.source_path,
        include_image_ocr=include_image_ocr,
        ocr_language=ocr_language,
        ocr_page_segmentation_mode=ocr_page_segmentation_mode,
        ocr_min_confidence=ocr_min_confidence,
        ocr_timeout=settings.default_timeout,
        relationship_tolerance=relationship_tolerance,
        max_relationships=max_relationships,
        max_vertices=max_vertices,
    )
    components = result.pop("components")
    relationships = result.pop("relationships")
    result["components"] = paginate(components, component_limit, component_offset)
    result["relationships"] = paginate(
        relationships,
        relationship_limit,
        relationship_offset,
    )
    return response(result, response_format)


def register_tools(mcp: FastMCP) -> None:
    register(
        mcp,
        dxf_image_to_dxf,
        read_only=False,
        destructive=True,
        idempotent=False,
    )
    register(mcp, dxf_recognize_components, read_only=True)
