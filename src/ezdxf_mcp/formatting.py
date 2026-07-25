"""Pagination and stable MCP response formatting."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def paginate(items: Sequence[Any], limit: int = 100, offset: int = 0) -> dict[str, Any]:
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if not 1 <= limit <= 10_000:
        raise ValueError("limit must be between 1 and 10000")
    page = list(items[offset : offset + limit])
    return {
        "items": page,
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(page) < len(items),
    }


def _markdown_value(value: Any, depth: int = 0) -> str:
    if isinstance(value, Mapping):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (Mapping, list, tuple)):
                lines.append(f"{'#' * min(depth + 2, 6)} {key}")
                lines.append(_markdown_value(item, depth + 1))
            else:
                lines.append(f"- **{key}:** {item}")
        return "\n".join(lines)
    if isinstance(value, (list, tuple)):
        return "\n".join(f"- {_markdown_value(item, depth + 1)}" for item in value)
    return str(value)


def response(data: Any, response_format: str = "json") -> dict[str, Any]:
    if response_format not in {"json", "markdown"}:
        raise ValueError("response_format must be 'json' or 'markdown'")
    if response_format == "markdown":
        return {"format": "markdown", "content": _markdown_value(data), "data": data}
    return {"format": "json", "data": data}


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray)):
        return [json_safe(item) for item in value]
    if hasattr(value, "xyz"):
        return list(value.xyz)
    if hasattr(value, "__dict__"):
        return json_safe(vars(value))
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value
