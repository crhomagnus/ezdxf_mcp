"""Small, dependency-light wrapper around Tesseract's official TSV output."""

from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_LANGUAGE_RE = re.compile(r"^[A-Za-z0-9_.+-]+$")


@dataclass(frozen=True, slots=True)
class OCRWord:
    """One OCR word and its source-image bounding box."""

    text: str
    confidence: float
    left: int
    top: int
    width: int
    height: int
    block: int
    paragraph: int
    line: int
    word: int

    @property
    def pixel_bbox(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.width, self.height

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "pixel_bbox": {
                "left": self.left,
                "top": self.top,
                "width": self.width,
                "height": self.height,
            },
            "block": self.block,
            "paragraph": self.paragraph,
            "line": self.line,
            "word": self.word,
        }


def tesseract_executable() -> str:
    executable = shutil.which("tesseract")
    if executable is None:
        raise RuntimeError(
            "OCR requested but the tesseract executable is unavailable; "
            "install tesseract-ocr plus the requested language packs"
        )
    return executable


def _integer(row: dict[str, str], key: str) -> int:
    try:
        return int(row.get(key, "0"))
    except ValueError:
        return 0


def run_ocr(
    image_path: Path,
    *,
    language: str = "por+eng",
    page_segmentation_mode: int = 11,
    min_confidence: float = 50.0,
    timeout: float = 60.0,
) -> list[OCRWord]:
    """Run Tesseract once and parse level-5 (word) TSV records."""
    if not _LANGUAGE_RE.fullmatch(language):
        raise ValueError("OCR language must contain only letters, digits, '.', '_', '+', or '-'")
    if not 0 <= page_segmentation_mode <= 13:
        raise ValueError("page_segmentation_mode must be between 0 and 13")
    if not 0.0 <= min_confidence <= 100.0:
        raise ValueError("min_confidence must be between 0 and 100")

    command = [
        tesseract_executable(),
        str(image_path),
        "stdout",
        "-l",
        language,
        "--psm",
        str(page_segmentation_mode),
        "tsv",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Tesseract exceeded the {timeout:g}s timeout") from exc
    if completed.returncode != 0:
        message = completed.stderr.strip() or "unknown Tesseract failure"
        raise RuntimeError(f"Tesseract failed with exit code {completed.returncode}: {message}")

    words: list[OCRWord] = []
    reader = csv.DictReader(io.StringIO(completed.stdout), delimiter="\t")
    for row in reader:
        if row.get("level") != "5":
            continue
        text = (row.get("text") or "").strip()
        try:
            confidence = float(row.get("conf", "-1"))
        except ValueError:
            confidence = -1.0
        width = _integer(row, "width")
        height = _integer(row, "height")
        if not text or confidence < min_confidence or width <= 0 or height <= 0:
            continue
        words.append(
            OCRWord(
                text=text,
                confidence=round(confidence, 3),
                left=_integer(row, "left"),
                top=_integer(row, "top"),
                width=width,
                height=height,
                block=_integer(row, "block_num"),
                paragraph=_integer(row, "par_num"),
                line=_integer(row, "line_num"),
                word=_integer(row, "word_num"),
            )
        )
    return words
