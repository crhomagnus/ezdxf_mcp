"""Raw DXF tags, encoding, comments, and file-format tools."""

from __future__ import annotations

import base64
import io
import re
import zipfile
from typing import Any

from ezdxf import comments
from ezdxf.lldxf.tagger import ascii_tags_loader
from ezdxf.lldxf.tagwriter import TagCollector
from mcp.server.fastmcp import FastMCP

from ..formatting import json_safe, paginate, response
from ..registry import register
from ..session import store
from ..validation import require_overwrite, safe_path

_UNICODE_ESCAPE = re.compile(r"\\U\\+[0-9A-Fa-f]{4,8}")
_CODEPAGES = {
    "ANSI_874": "cp874",
    "ANSI_932": "cp932",
    "ANSI_936": "gbk",
    "ANSI_949": "cp949",
    "ANSI_950": "cp950",
    **{f"ANSI_{number}": f"cp{number}" for number in range(1250, 1259)},
}


def _group_code_type(code: int) -> str:
    if 0 <= code <= 9 or code in {100, 102, 999} or 1000 <= code <= 1004:
        return "string"
    if 10 <= code <= 39:
        return "point_component"
    if (
        40 <= code <= 59
        or 110 <= code <= 149
        or 210 <= code <= 239
        or 460 <= code <= 469
        or code in {1010, 1020, 1030, 1040, 1041, 1042}
    ):
        return "float64"
    if (
        60 <= code <= 79
        or 170 <= code <= 179
        or 270 <= code <= 289
        or 370 <= code <= 389
        or 400 <= code <= 409
        or code == 1070
    ):
        return "int16"
    if 90 <= code <= 99 or 420 <= code <= 429 or 440 <= code <= 449 or code == 1071:
        return "int32"
    if 160 <= code <= 169:
        return "int64"
    if code in {5, 105}:
        return "handle"
    if 290 <= code <= 299:
        return "bool"
    if 310 <= code <= 319 or 1004 == code:
        return "binary_hex"
    if 320 <= code <= 369 or code == 1005:
        return "handle_reference"
    return "unknown"


def _reference_semantics(code: int) -> dict[str, Any] | None:
    ranges = (
        (320, 329, "arbitrary", False, False),
        (330, 339, "soft_pointer", True, False),
        (340, 349, "hard_pointer", True, True),
        (350, 359, "soft_owner", True, False),
        (360, 369, "hard_owner", True, True),
    )
    for start, end, kind, translated, protects in ranges:
        if start <= code <= end:
            return {
                "kind": kind,
                "translated_in_insert_xref": translated,
                "protects_from_purge": protects,
            }
    if code == 1005:
        return {
            "kind": "xdata_soft_pointer",
            "translated_in_insert_xref": True,
            "protects_from_purge": False,
        }
    return None


def document_tag_pairs(doc: Any) -> list[list[Any]]:
    """Return valid JSON-safe tags even when MTEXT contains backslash controls."""
    stream = io.StringIO()
    doc.write(stream)
    stream.seek(0)
    return [
        [tag.code, json_safe(tag.value)]
        for tag in ascii_tags_loader(stream, skip_comments=False)
    ]


def dxf_inspect_encoding(
    doc_id: str, response_format: str = "json"
) -> dict[str, Any]:
    """Show declared codepage, input encoding, and actual output encoding separately."""
    doc = store.get(doc_id).doc
    declared = doc.header.get("$DWGCODEPAGE", "ANSI_1252")
    return response(
        {
            "dxfversion": doc.dxfversion,
            "acad_release": doc.acad_release,
            "declared_dwgcodepage": declared,
            "declared_python_codec": _CODEPAGES.get(str(declared), "cp1252"),
            "encoding": doc.encoding,
            "output_encoding": doc.output_encoding,
            "utf8_output": doc.dxfversion >= "AC1021",
        },
        response_format,
    )


def dxf_find_encoding_issues(
    doc_id: str,
    target_encoding: str | None = None,
    limit: int = 100,
    offset: int = 0,
    response_format: str = "json",
) -> dict[str, Any]:
    """Find strings that do not survive a target encoding and DXF Unicode escapes."""
    doc = store.get(doc_id).doc
    encoding = target_encoding or doc.output_encoding
    findings: list[dict[str, Any]] = []
    for entity in doc.entitydb.values():
        if not entity.is_alive:
            continue
        for tag in TagCollector.dxftags(entity, doc.dxfversion):
            if not isinstance(tag.value, str):
                continue
            escapes = _UNICODE_ESCAPE.findall(tag.value)
            try:
                tag.value.encode(encoding, errors="strict")
            except UnicodeEncodeError as exc:
                findings.append(
                    {
                        "handle": entity.dxf.get("handle"),
                        "type": entity.dxftype(),
                        "code": tag.code,
                        "issue": "not_encodable",
                        "encoding": encoding,
                        "detail": str(exc),
                    }
                )
            if escapes:
                findings.append(
                    {
                        "handle": entity.dxf.get("handle"),
                        "type": entity.dxftype(),
                        "code": tag.code,
                        "issue": "dxf_unicode_escape",
                        "escapes": escapes,
                    }
                )
    return response({"encoding": encoding, **paginate(findings, limit, offset)}, response_format)


def dxf_check_string_limits(
    doc_id: str,
    limit: int = 100,
    offset: int = 0,
    response_format: str = "json",
) -> dict[str, Any]:
    """Report raw string tags over 255 bytes and the hard 2049-byte boundary."""
    doc = store.get(doc_id).doc
    findings: list[dict[str, Any]] = []
    for entity in doc.entitydb.values():
        if not entity.is_alive:
            continue
        for tag in TagCollector.dxftags(entity, doc.dxfversion):
            if isinstance(tag.value, str):
                size = len(tag.value.encode(doc.output_encoding, errors="backslashreplace"))
                if size > 255:
                    findings.append(
                        {
                            "handle": entity.dxf.get("handle"),
                            "type": entity.dxftype(),
                            "code": tag.code,
                            "bytes": size,
                            "severity": "error" if size > 2049 else "warning",
                        }
                    )
    return response(paginate(findings, limit, offset), response_format)


def dxf_dump_tags(
    doc_id: str,
    handle: str | None = None,
    compact: bool = True,
    limit: int = 500,
    offset: int = 0,
    response_format: str = "json",
) -> dict[str, Any]:
    """Dump typed group-code tags for one entity or the entire document."""
    doc = store.get(doc_id).doc
    if handle:
        entity = doc.entitydb.get(handle.upper())
        if entity is None:
            raise ValueError(f"handle not found: {handle}")
        tags = TagCollector.dxftags(entity, doc.dxfversion)
        rows = [
            {"code": tag.code, "type": _group_code_type(tag.code), "value": str(tag.value)}
            for tag in tags
        ]
        return response({"handle": handle.upper(), **paginate(rows, limit, offset)}, response_format)
    raw = document_tag_pairs(doc)
    rows = [
        {
            "code": int(tag[0]),
            "type": _group_code_type(int(tag[0])),
            "value": tag[1],
        }
        for tag in raw
    ]
    return response(paginate(rows, limit, offset), response_format)


def dxf_explain_group_code(code: int, response_format: str = "json") -> dict[str, Any]:
    """Explain a DXF group code including reference translation and purge semantics."""
    if not 0 <= code <= 1071:
        raise ValueError("group code must be between 0 and 1071")
    special = {
        0: "entity/section/table structure marker",
        1: "primary text",
        2: "name",
        5: "entity handle (except DIMSTYLE)",
        8: "layer name",
        9: "HEADER variable name",
        102: "application-defined group marker",
        105: "DIMSTYLE handle",
        999: "comment",
    }
    return response(
        {
            "code": code,
            "type": _group_code_type(code),
            "semantic": special.get(code),
            "reference": _reference_semantics(code),
        },
        response_format,
    )


def dxf_read_comments(
    path: str,
    limit: int = 100,
    offset: int = 0,
    response_format: str = "json",
) -> dict[str, Any]:
    """Read code-999 comments directly from an ASCII DXF file."""
    source = safe_path(path, must_exist=True, suffixes={".dxf"})
    rows = [{"code": tag.code, "value": tag.value} for tag in comments.from_file(str(source), {999})]
    return response(paginate(rows, limit, offset), response_format)


def dxf_strip_file(
    path: str,
    output_path: str,
    remove_comments: bool = True,
    remove_thumbnail: bool = True,
    overwrite: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Strip comments and/or THUMBNAILIMAGE from an ASCII DXF without in-place writes."""
    source = safe_path(path, must_exist=True, suffixes={".dxf"})
    target = safe_path(output_path, suffixes={".dxf"})
    require_overwrite(target, overwrite)
    raw = source.read_text(encoding="utf-8", errors="surrogateescape").splitlines(keepends=True)
    if len(raw) % 2:
        raise ValueError("malformed ASCII DXF: odd number of tag lines")
    out: list[str] = []
    in_thumbnail = False
    for index in range(0, len(raw), 2):
        code_line, value_line = raw[index], raw[index + 1]
        try:
            code = int(code_line.strip())
        except ValueError as exc:
            raise ValueError(f"invalid group code at line {index + 1}") from exc
        value = value_line.strip()
        if code == 0 and value == "SECTION":
            next_value = raw[index + 3].strip() if index + 3 < len(raw) else ""
            in_thumbnail = next_value == "THUMBNAILIMAGE"
        if in_thumbnail and remove_thumbnail:
            if code == 0 and value == "ENDSEC":
                in_thumbnail = False
            continue
        if code == 999 and remove_comments:
            continue
        out.extend((code_line, value_line))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(out), encoding="utf-8", errors="surrogateescape")
    return response({"source": str(source), "output": str(target), "bytes": target.stat().st_size}, response_format)


def dxf_detect_format(path: str, response_format: str = "json") -> dict[str, Any]:
    """Detect ASCII, binary, ZIP, or base64-encoded DXF input."""
    source = safe_path(path, must_exist=True)
    head = source.read_bytes()[:512]
    kind = "unknown"
    lines: int | None = None
    if zipfile.is_zipfile(source):
        kind = "zip"
    elif head.startswith(b"AutoCAD Binary DXF"):
        kind = "binary"
    elif b"SECTION" in head or source.suffix.lower() == ".dxf":
        kind = "ascii"
        with source.open("rb") as stream:
            lines = sum(1 for _ in stream)
    else:
        try:
            decoded = base64.b64decode(source.read_bytes(), validate=True)
            if b"SECTION" in decoded[:512] or decoded.startswith(b"AutoCAD Binary DXF"):
                kind = "base64"
        except ValueError:
            pass
    return response(
        {"path": str(source), "format": kind, "size_bytes": source.stat().st_size, "line_count": lines},
        response_format,
    )


def register_tools(mcp: FastMCP) -> None:
    for func in (
        dxf_inspect_encoding,
        dxf_find_encoding_issues,
        dxf_check_string_limits,
        dxf_dump_tags,
        dxf_explain_group_code,
        dxf_read_comments,
        dxf_detect_format,
    ):
        register(mcp, func, read_only=True)
    register(mcp, dxf_strip_file, read_only=False, destructive=False)
