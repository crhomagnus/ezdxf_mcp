from __future__ import annotations

from pathlib import Path

import pytest

from ezdxf_mcp.errors import PathValidationError
from ezdxf_mcp.validation import safe_path


def test_relative_path_is_confined(workspace: Path) -> None:
    target = safe_path("r2000.dxf", must_exist=True)
    assert target == workspace / "r2000.dxf"


def test_absolute_external_path_is_rejected() -> None:
    with pytest.raises(PathValidationError):
        safe_path("/etc/passwd", must_exist=True)


def test_traversal_is_rejected() -> None:
    with pytest.raises(PathValidationError):
        safe_path("../escape.dxf")


def test_symlink_escape_is_rejected(workspace: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.dxf"
    outside.write_text("0\nEOF\n", encoding="ascii")
    link = workspace / "escape-link.dxf"
    link.unlink(missing_ok=True)
    link.symlink_to(outside)
    try:
        with pytest.raises(PathValidationError):
            safe_path(link.name, must_exist=True)
    finally:
        link.unlink(missing_ok=True)
