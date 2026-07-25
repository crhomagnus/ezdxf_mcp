"""Workspace confinement and input validation."""

from __future__ import annotations

from pathlib import Path

from .config import settings
from .errors import PathValidationError


def ensure_workspace() -> Path:
    settings.workspace.mkdir(parents=True, exist_ok=True)
    return settings.workspace


def safe_path(
    raw_path: str,
    *,
    must_exist: bool = False,
    suffixes: set[str] | None = None,
) -> Path:
    workspace = ensure_workspace().resolve()
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve(strict=must_exist)
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise PathValidationError(
            f"path escapes EZDXF_MCP_WORKSPACE ({workspace}): {raw_path}"
        ) from exc
    if suffixes and resolved.suffix.lower() not in suffixes:
        allowed = ", ".join(sorted(suffixes))
        raise PathValidationError(f"unsupported extension {resolved.suffix!r}; expected {allowed}")
    if must_exist and not resolved.is_file():
        raise PathValidationError(f"file does not exist: {resolved}")
    return resolved


def require_overwrite(path: Path, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise PathValidationError(
            f"refusing to overwrite {path}; pass overwrite=true explicitly"
        )
