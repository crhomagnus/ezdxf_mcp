"""Persistent, confined job storage for the HTTP API."""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import ezdxf

from ..image.spatial import recognize_components
from ..image.vectorize import IMAGE_SUFFIXES, ImageVectorizationConfig, vectorize_image

JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def drawing_bounds(components: list[dict[str, Any]]) -> dict[str, list[float]]:
    boxes = [component["bbox"] for component in components if component.get("bbox")]
    if not boxes:
        raise ValueError("drawing has no positioned components")
    minimum = [
        min(float(box["min"][axis]) for box in boxes)
        for axis in range(3)
    ]
    maximum = [
        max(float(box["max"][axis]) for box in boxes)
        for axis in range(3)
    ]
    return {"min": minimum, "max": maximum}


class JobStore:
    """Create and resolve API job directories without caller-controlled paths."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def create(self, suffix: str) -> tuple[str, Path, Path]:
        normalized_suffix = suffix.lower()
        if normalized_suffix not in IMAGE_SUFFIXES:
            raise ValueError(f"image extension must be one of {sorted(IMAGE_SUFFIXES)}")
        job_id = uuid4().hex
        directory = self.root / job_id
        directory.mkdir(mode=0o700)
        return job_id, directory, directory / f"source{normalized_suffix}"

    def directory(self, job_id: str) -> Path:
        if not JOB_ID_PATTERN.fullmatch(job_id):
            raise KeyError("invalid job id")
        directory = self.root / job_id
        if not directory.is_dir():
            raise KeyError("job not found")
        return directory

    def remove(self, job_id: str) -> None:
        directory = self.directory(job_id)
        shutil.rmtree(directory)

    def result(self, job_id: str) -> dict[str, Any]:
        result_path = self.directory(job_id) / "result.json"
        if not result_path.is_file():
            raise KeyError("job result not found")
        return json.loads(result_path.read_text(encoding="utf-8"))

    def dxf_path(self, job_id: str) -> Path:
        path = self.directory(job_id) / "drawing.dxf"
        if not path.is_file():
            raise KeyError("job DXF not found")
        return path

    def convert(
        self,
        *,
        job_id: str,
        source_path: Path,
        config: ImageVectorizationConfig,
    ) -> dict[str, Any]:
        directory = self.directory(job_id)
        dxf_path = directory / "drawing.dxf"
        document, report = vectorize_image(
            source_path,
            config,
            raster_reference_base=directory,
        )
        document.saveas(dxf_path)
        recognition = recognize_components(
            document,
            layout=document.modelspace(),
            source_path=dxf_path,
            include_image_ocr=False,
            ocr_language=config.ocr_language,
            ocr_page_segmentation_mode=config.ocr_page_segmentation_mode,
            ocr_min_confidence=config.ocr_min_confidence,
            ocr_timeout=config.ocr_timeout,
            max_relationships=5000,
        )
        components = recognition["components"]
        result = {
            "job_id": job_id,
            "status": "complete",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_filename": source_path.name,
            "dxf_filename": dxf_path.name,
            "conversion": report.as_dict(),
            "recognition": recognition,
            "drawing_bounds": drawing_bounds(components),
        }
        _write_json(directory / "result.json", result)
        return result

    def open_document(self, job_id: str) -> ezdxf.document.Drawing:
        return ezdxf.readfile(self.dxf_path(job_id))
