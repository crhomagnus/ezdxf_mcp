"""Raster image vectorization into native DXF geometry and OCR text."""

from __future__ import annotations

import math
import os
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import cv2
import ezdxf
import numpy as np
from ezdxf import path as ezpath
from ezdxf import units, zoom
from ezdxf.document import Drawing
from ezdxf.entities import DXFEntity

from . import bezierfit, curvefit, primitives
from .ocr import OCRWord, run_ocr

APPID = "IMG2DXF"
LAYER_EXTERNAL = "IMG_OUTLINE"
LAYER_HOLE = "IMG_HOLE"
LAYER_ANALYTIC = "IMG_ANALYTIC"
LAYER_TEXT = "IMG_TEXT"
LAYER_RASTER = "IMG_RASTER"
LAYER_COLORS = {
    LAYER_EXTERNAL: 7,
    LAYER_HOLE: 1,
    LAYER_ANALYTIC: 3,
    LAYER_TEXT: 5,
    LAYER_RASTER: 8,
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
CURVE_MODES = {"auto", "arc", "bezier", "line", "spline"}
BINARIZATION_MODES = {"otsu", "fixed", "adaptive", "canny"}


@dataclass(slots=True)
class ImageVectorizationConfig:
    """Configuration for deterministic image-to-DXF conversion."""

    binarization: str = "otsu"
    threshold: int = 127
    invert: bool = False
    blur: int = 3
    canny_low: int = 50
    canny_high: int = 150
    curve_mode: str = "auto"
    allowed_primitives: set[str] = field(
        default_factory=lambda: {"circulo", "elipse", "reta", "arco", "bezier"}
    )
    fit_tolerance_px: float = 0.8
    max_arc_angle: float = 120.0
    simplify_fraction: float = 0.002
    minimum_area_px: float = 20.0
    detect_circles: bool = True
    minimum_circularity: float = 0.88
    width_mm: float | None = None
    dpi: float | None = None
    mm_per_pixel: float | None = None
    dxf_version: str = "R2018"
    run_text_ocr: bool = True
    ocr_language: str = "por+eng"
    ocr_page_segmentation_mode: int = 11
    ocr_min_confidence: float = 50.0
    ocr_max_height_fraction: float = 0.25
    ocr_max_area_fraction: float = 0.20
    ocr_timeout: float = 60.0
    exclude_ocr_from_vectors: bool = True
    ocr_mask_padding_px: int = 2
    include_raster_reference: bool = False
    max_pixels: int = 100_000_000

    def validate(self) -> None:
        if self.binarization not in BINARIZATION_MODES:
            raise ValueError(f"binarization must be one of {sorted(BINARIZATION_MODES)}")
        if self.curve_mode not in CURVE_MODES:
            raise ValueError(f"curve_mode must be one of {sorted(CURVE_MODES)}")
        if not 0 <= self.threshold <= 255:
            raise ValueError("threshold must be between 0 and 255")
        if self.blur < 0:
            raise ValueError("blur must be >= 0")
        if self.canny_low < 0 or self.canny_high <= self.canny_low:
            raise ValueError("canny thresholds must satisfy 0 <= low < high")
        if self.fit_tolerance_px <= 0:
            raise ValueError("fit_tolerance_px must be > 0")
        if not 0 < self.max_arc_angle <= 180:
            raise ValueError("max_arc_angle must be between 0 and 180")
        if self.simplify_fraction < 0:
            raise ValueError("simplify_fraction must be >= 0")
        if self.minimum_area_px < 0:
            raise ValueError("minimum_area_px must be >= 0")
        if self.max_pixels <= 0:
            raise ValueError("max_pixels must be > 0")
        scale_inputs = [self.width_mm, self.dpi, self.mm_per_pixel]
        if sum(value is not None for value in scale_inputs) > 1:
            raise ValueError("use only one of width_mm, dpi, or mm_per_pixel")
        for name, value in (
            ("width_mm", self.width_mm),
            ("dpi", self.dpi),
            ("mm_per_pixel", self.mm_per_pixel),
        ):
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be > 0")
        if self.ocr_mask_padding_px < 0:
            raise ValueError("ocr_mask_padding_px must be >= 0")
        if not 0 < self.ocr_max_height_fraction <= 1:
            raise ValueError("ocr_max_height_fraction must be between 0 and 1")
        if not 0 < self.ocr_max_area_fraction <= 1:
            raise ValueError("ocr_max_area_fraction must be between 0 and 1")
        if self.dxf_version.upper() in {"R12", "AC1009", "R13", "R14", "AC1012", "AC1014"}:
            raise ValueError("image vectorization requires DXF R2000 or newer")


@dataclass(slots=True)
class VectorizationReport:
    image_width_px: int
    image_height_px: int
    mm_per_pixel: float
    scale_source: str
    raw_contours: int = 0
    discarded_contours: int = 0
    external_contours: int = 0
    holes: int = 0
    ocr_words: int = 0
    vertices_before: int = 0
    vertices_after: int = 0
    audit_errors: int = 0
    audit_fixes: int = 0
    entity_types: Counter[str] = field(default_factory=Counter)
    components: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["entity_types"] = dict(sorted(self.entity_types.items()))
        if self.vertices_before:
            result["vertex_reduction_percent"] = round(
                100.0 * (1.0 - self.vertices_after / self.vertices_before),
                3,
            )
        else:
            result["vertex_reduction_percent"] = 0.0
        result["drawing_width_mm"] = round(self.image_width_px * self.mm_per_pixel, 9)
        result["drawing_height_mm"] = round(self.image_height_px * self.mm_per_pixel, 9)
        return result


def _load_image(path: Path, max_pixels: int) -> tuple[np.ndarray, np.ndarray]:
    encoded: np.ndarray = np.fromfile(str(path), dtype=np.uint8)
    color = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if color is None:
        raise ValueError(f"OpenCV could not decode image: {path}")
    height, width = color.shape[:2]
    if width * height > max_pixels:
        raise ValueError(
            f"image has {width * height:,} pixels; configured maximum is {max_pixels:,}"
        )
    return color, cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)


def _resolve_scale(config: ImageVectorizationConfig, width_px: int) -> tuple[float, str]:
    if config.width_mm is not None:
        return config.width_mm / width_px, "width_mm"
    if config.dpi is not None:
        return 25.4 / config.dpi, "dpi"
    if config.mm_per_pixel is not None:
        return config.mm_per_pixel, "mm_per_pixel"
    return 1.0, "default_1_mm_per_pixel"


def _binarize(gray: np.ndarray, config: ImageVectorizationConfig) -> np.ndarray:
    work = gray
    if config.blur >= 3:
        kernel = config.blur if config.blur % 2 else config.blur + 1
        work = cv2.GaussianBlur(work, (kernel, kernel), 0)
    if config.binarization == "canny":
        binary = cv2.Canny(work, config.canny_low, config.canny_high)
    elif config.binarization == "adaptive":
        binary = cv2.adaptiveThreshold(
            work,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            31,
            5,
        )
    elif config.binarization == "fixed":
        _, binary = cv2.threshold(
            work,
            config.threshold,
            255,
            cv2.THRESH_BINARY_INV,
        )
    else:
        _, binary = cv2.threshold(
            work,
            0,
            255,
            cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
        )
    return cv2.bitwise_not(binary) if config.invert else binary


def _mask_ocr_regions(
    binary: np.ndarray,
    words: list[OCRWord],
    padding: int,
) -> np.ndarray:
    masked = binary.copy()
    image_height, image_width = masked.shape[:2]
    for word in words:
        left = max(word.left - padding, 0)
        top = max(word.top - padding, 0)
        right = min(word.left + word.width + padding, image_width)
        bottom = min(word.top + word.height + padding, image_height)
        cv2.rectangle(masked, (left, top), (right, bottom), 0, thickness=-1)
    return masked


def _depth(hierarchy: np.ndarray, index: int) -> int:
    depth = 0
    parent = int(hierarchy[index][3])
    while parent >= 0:
        depth += 1
        parent = int(hierarchy[parent][3])
    return depth


def _pixel_bbox(contour: np.ndarray) -> tuple[int, int, int, int]:
    left, top, width, height = cv2.boundingRect(contour)
    return int(left), int(top), int(width), int(height)


def _drawing_bbox(
    pixel_bbox: tuple[int, int, int, int],
    image_height: int,
    scale: float,
) -> dict[str, list[float]]:
    left, top, width, height = pixel_bbox
    minimum = [left * scale, (image_height - top - height) * scale, 0.0]
    maximum = [(left + width) * scale, (image_height - top) * scale, 0.0]
    return {
        "min": [round(value, 9) for value in minimum],
        "max": [round(value, 9) for value in maximum],
    }


def _metadata_tags(values: dict[str, Any]) -> list[tuple[int, str]]:
    tags: list[tuple[int, str]] = [(1000, "schema=img2dxf/1")]
    for key, value in values.items():
        clean = str(value).replace("\r", " ").replace("\n", " ")
        encoded = f"{key}={clean}"
        tags.append((1000, encoded[:255]))
    return tags


def set_component_metadata(entity: DXFEntity, **values: Any) -> None:
    entity.set_xdata(APPID, _metadata_tags(values))


def component_metadata(entity: DXFEntity) -> dict[str, str]:
    try:
        tags = entity.get_xdata(APPID)
    except ezdxf.DXFValueError:
        return {}
    result: dict[str, str] = {}
    for tag in tags:
        if tag.code != 1000 or "=" not in str(tag.value):
            continue
        key, value = str(tag.value).split("=", 1)
        result[key] = value
    return result


def _created_since(layout: Any, handles: set[str]) -> list[DXFEntity]:
    return [
        entity
        for entity in layout
        if entity.dxf.handle is not None and entity.dxf.handle not in handles
    ]


def _emit_contour(
    layout: Any,
    contour: np.ndarray,
    config: ImageVectorizationConfig,
    image_height: int,
    scale: float,
    layer: str,
) -> tuple[list[DXFEntity], dict[str, int]]:
    points: np.ndarray = contour.reshape(-1, 2).astype(float)
    handles = {entity.dxf.handle for entity in layout if entity.dxf.handle is not None}
    counts = {"line": 0, "arc": 0, "bezier": 0, "circle": 0, "ellipse": 0}

    def transform(point: Any) -> tuple[float, float]:
        return float(point[0]) * scale, float(image_height - point[1]) * scale

    if config.curve_mode == "auto":
        shape = primitives.ajustar_contorno(
            points,
            tol=config.fit_tolerance_px,
            tol_bezier=max(config.fit_tolerance_px, 1.5),
            permitidas=config.allowed_primitives,
            fechado=True,
            ang_max=config.max_arc_angle,
        )
        container = primitives.emitir(
            layout,
            shape,
            points,
            image_height,
            scale,
            layer,
            LAYER_ANALYTIC,
        )
        if container == "descartado":
            return [], counts
        if container == "CIRCLE":
            counts["circle"] = 1
        elif container == "ELLIPSE":
            counts["ellipse"] = 1
        else:
            summary = shape.resumo()
            counts["line"] = summary["reta"]
            counts["arc"] = summary["arco"]
            counts["bezier"] = summary["bezier"]
        return _created_since(layout, handles), counts

    if config.curve_mode != "auto" and config.detect_circles and len(contour) >= 8:
        perimeter = cv2.arcLength(contour, True)
        circularity = (
            4.0 * math.pi * cv2.contourArea(contour) / (perimeter * perimeter)
            if perimeter > 0
            else 0.0
        )
        (center_x, center_y), enclosing_radius = cv2.minEnclosingCircle(contour)
        area = cv2.contourArea(contour)
        circle_area = math.pi * enclosing_radius * enclosing_radius
        if (
            enclosing_radius > 0
            and circularity >= config.minimum_circularity
            and circle_area > 0
            and abs(area - circle_area) / circle_area <= 0.15
        ):
            area_radius = math.sqrt(area / math.pi)
            layout.add_circle(
                (center_x * scale, (image_height - center_y) * scale),
                (enclosing_radius + area_radius) * scale / 2.0,
                dxfattribs={"layer": LAYER_ANALYTIC},
            )
            counts["circle"] = 1
            return _created_since(layout, handles), counts

    if config.curve_mode == "arc":
        segments = curvefit.segmentar(
            points,
            tol=config.fit_tolerance_px,
            ang_max=config.max_arc_angle,
        )
        vertices = curvefit.para_bulge(points, segments, transformar=transform)
        if len(vertices) >= 3:
            layout.add_lwpolyline(
                vertices,
                format="xyseb",
                close=True,
                dxfattribs={"layer": layer},
            )
        counts["arc"] = sum(segment.tipo == "arco" for segment in segments)
        counts["line"] = sum(segment.tipo == "reta" for segment in segments)
    elif config.curve_mode == "bezier":
        curves = bezierfit.ajustar(
            points,
            tol=max(config.fit_tolerance_px, 1.5),
            fechado=True,
        )
        path = bezierfit.para_path(curves, transformar=transform)
        if path is not None:
            for entity in ezpath.to_splines_and_polylines([path]):
                entity.dxf.layer = layer
                layout.add_entity(entity)
        counts["bezier"] = len(curves)
    elif config.curve_mode == "spline":
        epsilon = config.simplify_fraction * cv2.arcLength(contour, True)
        approximation = cv2.approxPolyDP(contour, epsilon, True) if epsilon > 0 else contour
        vertices = [transform(point) for point in approximation.reshape(-1, 2)]
        if len(vertices) >= 4:
            layout.add_spline(
                fit_points=[*vertices, vertices[0]],
                dxfattribs={"layer": layer},
            )
            counts["bezier"] = 1
    else:
        epsilon = config.simplify_fraction * cv2.arcLength(contour, True)
        approximation = cv2.approxPolyDP(contour, epsilon, True) if epsilon > 0 else contour
        vertices = [transform(point) for point in approximation.reshape(-1, 2)]
        if len(vertices) >= 3:
            layout.add_lwpolyline(vertices, close=True, dxfattribs={"layer": layer})
            counts["line"] = len(vertices)
    return _created_since(layout, handles), counts


def _add_ocr_text(
    doc: Drawing,
    words: list[OCRWord],
    image_height: int,
    scale: float,
    report: VectorizationReport,
) -> None:
    layout = doc.modelspace()
    for index, word in enumerate(words, start=1):
        component_id = f"text_{index:04d}"
        insertion = (
            word.left * scale,
            (image_height - word.top - word.height) * scale,
        )
        height = max(word.height * scale, scale)
        width_factor = word.width / max(len(word.text) * word.height * 0.6, 1.0)
        entity = layout.add_text(
            word.text,
            dxfattribs={
                "layer": LAYER_TEXT,
                "height": height,
                "width": max(0.1, min(width_factor, 10.0)),
            },
        ).set_placement(insertion)
        bbox_px = word.pixel_bbox
        set_component_metadata(
            entity,
            kind="ocr_text",
            component_id=component_id,
            pixel_bbox=",".join(str(value) for value in bbox_px),
            confidence=word.confidence,
            ocr_block=word.block,
            ocr_paragraph=word.paragraph,
            ocr_line=word.line,
            ocr_word=word.word,
        )
        report.entity_types["TEXT"] += 1
        report.components.append(
            {
                "component_id": component_id,
                "kind": "text",
                "handle": entity.dxf.handle,
                "text": word.text,
                "confidence": word.confidence,
                "pixel_bbox": {
                    "left": word.left,
                    "top": word.top,
                    "width": word.width,
                    "height": word.height,
                },
                "drawing_bbox": _drawing_bbox(bbox_px, image_height, scale),
            }
        )


def _add_raster_reference(
    doc: Drawing,
    image_path: Path,
    image_width: int,
    image_height: int,
    scale: float,
    reference_base: Path,
    report: VectorizationReport,
) -> None:
    relative_name = os.path.relpath(image_path, reference_base)
    image_definition = doc.add_image_def(
        filename=relative_name,
        size_in_pixel=(image_width, image_height),
    )
    image = doc.modelspace().add_image(
        insert=(0, 0),
        size_in_units=(image_width * scale, image_height * scale),
        image_def=image_definition,
    )
    image.dxf.layer = LAYER_RASTER
    image.dxf.fade = 70
    set_component_metadata(
        image,
        kind="raster_image",
        component_id="raster_0001",
        pixel_bbox=f"0,0,{image_width},{image_height}",
    )
    report.entity_types["IMAGE"] += 1
    report.components.append(
        {
            "component_id": "raster_0001",
            "kind": "image",
            "handle": image.dxf.handle,
            "filename": relative_name,
            "pixel_bbox": {
                "left": 0,
                "top": 0,
                "width": image_width,
                "height": image_height,
            },
            "drawing_bbox": _drawing_bbox(
                (0, 0, image_width, image_height),
                image_height,
                scale,
            ),
        }
    )
    report.warnings.append(
        "DXF IMAGE is an external reference; the raster file is not embedded in the DXF"
    )


def vectorize_image(
    image_path: Path,
    config: ImageVectorizationConfig,
    *,
    raster_reference_base: Path | None = None,
) -> tuple[Drawing, VectorizationReport]:
    """Convert PNG/JPG pixels into native DXF entities and optional OCR TEXT."""
    config.validate()
    if image_path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError(f"image extension must be one of {sorted(IMAGE_SUFFIXES)}")
    _, gray = _load_image(image_path, config.max_pixels)
    image_height, image_width = gray.shape[:2]
    scale, scale_source = _resolve_scale(config, image_width)
    report = VectorizationReport(
        image_width_px=image_width,
        image_height_px=image_height,
        mm_per_pixel=scale,
        scale_source=scale_source,
    )
    if scale_source == "default_1_mm_per_pixel":
        report.warnings.append(
            "no physical scale supplied; defaulted to 1 drawing millimetre per pixel"
        )

    words: list[OCRWord] = []
    if config.run_text_ocr:
        raw_words = run_ocr(
            image_path,
            language=config.ocr_language,
            page_segmentation_mode=config.ocr_page_segmentation_mode,
            min_confidence=config.ocr_min_confidence,
            timeout=config.ocr_timeout,
        )
        words = [
            word
            for word in raw_words
            if word.height / image_height <= config.ocr_max_height_fraction
            and (word.width * word.height) / (image_width * image_height)
            <= config.ocr_max_area_fraction
        ]
        rejected_words = len(raw_words) - len(words)
        if rejected_words:
            report.warnings.append(
                f"rejected {rejected_words} implausibly large OCR word box(es)"
            )
        report.ocr_words = len(words)
        if not words:
            report.warnings.append("OCR completed but found no words above the confidence threshold")

    binary = _binarize(gray, config)
    if words and config.exclude_ocr_from_vectors:
        binary = _mask_ocr_regions(binary, words, config.ocr_mask_padding_px)
    contours, hierarchy_raw = cv2.findContours(
        binary,
        cv2.RETR_TREE,
        cv2.CHAIN_APPROX_NONE,
    )
    hierarchy = hierarchy_raw[0] if hierarchy_raw is not None else None
    report.raw_contours = len(contours)
    if not contours:
        report.warnings.append(
            "no vector contours found; try invert=true, another binarization mode, "
            "or a lower minimum_area_px"
        )

    doc = ezdxf.new(config.dxf_version, setup=True, units=units.MM)
    doc.appids.add(APPID)
    metadata = doc.ezdxf_metadata()
    metadata["IMG2DXF_SCHEMA"] = "1"
    metadata["IMG2DXF_SOURCE"] = image_path.name
    metadata["IMG2DXF_IMAGE_WIDTH_PX"] = str(image_width)
    metadata["IMG2DXF_IMAGE_HEIGHT_PX"] = str(image_height)
    metadata["IMG2DXF_MM_PER_PIXEL"] = f"{scale:.17g}"
    metadata["IMG2DXF_SCALE_SOURCE"] = scale_source
    for layer_name, color in LAYER_COLORS.items():
        doc.layers.add(layer_name, color=color)
    doc.layers.get(LAYER_RASTER).off()

    if config.include_raster_reference:
        _add_raster_reference(
            doc,
            image_path,
            image_width,
            image_height,
            scale,
            raster_reference_base or image_path.parent,
            report,
        )

    contour_components: dict[int, str] = {}
    for contour_index, contour in enumerate(contours):
        area = abs(float(cv2.contourArea(contour)))
        if area < config.minimum_area_px:
            report.discarded_contours += 1
            continue
        depth = _depth(hierarchy, contour_index) if hierarchy is not None else 0
        is_hole = depth % 2 == 1
        layer = LAYER_HOLE if is_hole else LAYER_EXTERNAL
        report.vertices_before += len(contour)
        created, primitive_counts = _emit_contour(
            doc.modelspace(),
            contour,
            config,
            image_height,
            scale,
            layer,
        )
        if not created:
            report.discarded_contours += 1
            continue

        component_id = f"vector_{len(contour_components) + 1:04d}"
        contour_components[contour_index] = component_id
        parent_index = int(hierarchy[contour_index][3]) if hierarchy is not None else -1
        bbox_px = _pixel_bbox(contour)
        geometry_kind = "vector_shape"
        if primitive_counts["circle"]:
            geometry_kind = "circle"
        elif primitive_counts["ellipse"]:
            geometry_kind = "ellipse"
        kind = "hole" if is_hole else geometry_kind
        for entity in created:
            set_component_metadata(
                entity,
                kind=kind,
                geometry_kind=geometry_kind,
                component_id=component_id,
                parent_component_id=contour_components.get(parent_index, ""),
                contour_index=contour_index,
                contour_parent_index=parent_index,
                contour_depth=depth,
                pixel_bbox=",".join(str(value) for value in bbox_px),
            )
            report.entity_types[entity.dxftype()] += 1
        report.vertices_after += sum(primitive_counts.values())
        if is_hole:
            report.holes += 1
        else:
            report.external_contours += 1
        report.components.append(
            {
                "component_id": component_id,
                "kind": kind,
                "geometry_kind": geometry_kind,
                "handles": [entity.dxf.handle for entity in created],
                "entity_types": [entity.dxftype() for entity in created],
                "layer": created[0].dxf.get("layer", layer),
                "contour_index": contour_index,
                "parent_component_id": contour_components.get(parent_index),
                "contour_depth": depth,
                "pixel_area": area,
                "pixel_bbox": {
                    "left": bbox_px[0],
                    "top": bbox_px[1],
                    "width": bbox_px[2],
                    "height": bbox_px[3],
                },
                "drawing_bbox": _drawing_bbox(bbox_px, image_height, scale),
                "primitives": primitive_counts,
            }
        )

    if words:
        _add_ocr_text(doc, words, image_height, scale, report)
    if config.binarization == "canny":
        report.warnings.append(
            "Canny extracts edges rather than filled regions; hole hierarchy is heuristic"
        )

    zoom.extents(doc.modelspace())
    auditor = doc.audit()
    report.audit_errors = len(auditor.errors)
    report.audit_fixes = len(auditor.fixes)
    return doc, report
