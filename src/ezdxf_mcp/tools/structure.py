"""DXF structural validation, handles, ownership, tables, and purge safety."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from io import StringIO
from itertools import pairwise
from typing import Any

from ezdxf import blkrefs
from ezdxf.audit import AuditError, ErrorEntry
from ezdxf.lldxf.tagger import ascii_tags_loader
from ezdxf.lldxf.tagwriter import TagCollector
from mcp.server.fastmcp import FastMCP

from ..formatting import json_safe, paginate, response
from ..registry import register
from ..session import DocumentSession, store

_REFERENCE_RANGES = (
    (320, 329, "arbitrary", False, False),
    (330, 339, "soft_pointer", True, False),
    (340, 349, "hard_pointer", True, True),
    (350, 359, "soft_owner", True, False),
    (360, 369, "hard_owner", True, True),
)
_INVALID_NAME = re.compile(r'[<>/\\":;?*=`]')
_REQUIRED_R12 = {"TABLES", "BLOCKS", "ENTITIES"}
_REQUIRED_R13 = {"HEADER", "CLASSES", "TABLES", "BLOCKS", "ENTITIES", "OBJECTS"}


def reference_semantics(code: int) -> dict[str, Any] | None:
    """Return pointer/owner hardness and INSERT/XREF translation semantics."""
    for start, end, kind, translated, hard in _REFERENCE_RANGES:
        if start <= code <= end:
            return {
                "kind": kind,
                "translated": translated,
                "hard": hard,
                "protects_from_purge": hard,
            }
    if code == 1005:
        return {
            "kind": "xdata_soft_pointer",
            "translated": True,
            "hard": False,
            "protects_from_purge": False,
        }
    return None


def _audit_entry(entry: ErrorEntry) -> dict[str, Any]:
    try:
        symbolic = AuditError(entry.code).name
    except ValueError:
        symbolic = "UNKNOWN"
    entity = entry.entity
    return {
        "code": entry.code,
        "symbol": symbolic,
        "message": entry.message,
        "handle": entity.dxf.get("handle") if entity is not None else None,
        "entity_type": entity.dxftype() if entity is not None else None,
        "data": json_safe(entry.data),
        "highlight": entry.code == 104,
    }


def _section_rows(session: DocumentSession) -> list[dict[str, Any]]:
    stream = StringIO()
    session.doc.write(stream)
    stream.seek(0)
    raw = [(tag.code, tag.value) for tag in ascii_tags_loader(stream, skip_comments=False)]
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    index = 0
    while index < len(raw):
        code, value = raw[index][0], raw[index][1]
        if code == 0 and value == "SECTION" and index + 1 < len(raw) and raw[index + 1][0] == 2:
            current = {
                "name": str(raw[index + 1][1]),
                "order": len(rows),
                "tag_count": 2,
            }
            rows.append(current)
            index += 2
            continue
        if current is not None:
            current["tag_count"] += 1
            if code == 0 and value == "ENDSEC":
                current = None
        index += 1
    return rows


def _entity_references(session: DocumentSession) -> list[dict[str, Any]]:
    doc = session.doc
    references: list[dict[str, Any]] = []
    for entity in doc.entitydb.values():
        if not entity.is_alive:
            continue
        source = entity.dxf.get("handle")
        try:
            tags = TagCollector.dxftags(entity, doc.dxfversion)
        except Exception:  # noqa: S112 - malformed entities are reported by the audit tools
            continue
        for tag in tags:
            semantics = reference_semantics(tag.code)
            if semantics is None or not isinstance(tag.value, str):
                continue
            target = tag.value.upper()
            if not target or target == "0":
                continue
            references.append(
                {
                    "source": source,
                    "source_type": entity.dxftype(),
                    "target": target,
                    "code": tag.code,
                    **semantics,
                }
            )
    return references


def _name_entries(session: DocumentSession) -> list[tuple[str, str]]:
    doc = session.doc
    result: list[tuple[str, str]] = []
    for kind, collection in (
        ("LAYER", doc.layers),
        ("BLOCK", doc.blocks),
        ("LTYPE", doc.linetypes),
        ("STYLE", doc.styles),
        ("DIMSTYLE", doc.dimstyles),
        ("APPID", doc.appids),
        ("UCS", doc.ucs),
        ("VIEW", doc.views),
        ("VPORT", doc.viewports),
    ):
        for entry in collection:
            name = entry.dxf.get("name") if hasattr(entry, "dxf") else entry.name
            result.append((kind, str(name)))
    return result


def _raw_symbol_names(session: DocumentSession) -> list[tuple[str, str]]:
    """Read symbol names before ezdxf's case-insensitive tables merge collisions."""
    source = session.source_path
    if source is None or source.suffix.lower() != ".dxf":
        return []
    try:
        lines = source.read_text(
            encoding=session.doc.output_encoding, errors="surrogateescape"
        ).splitlines()
    except (OSError, UnicodeError):
        return []
    if len(lines) % 2:
        return []
    tags = []
    for index in range(0, len(lines), 2):
        try:
            tags.append((int(lines[index].strip()), lines[index + 1].strip()))
        except ValueError:
            return []
    names: list[tuple[str, str]] = []
    in_tables = False
    current_entry: str | None = None
    for index, (code, value) in enumerate(tags):
        if code == 0 and value == "SECTION":
            in_tables = index + 1 < len(tags) and tags[index + 1] == (2, "TABLES")
            current_entry = None
            continue
        if code == 0 and value == "ENDSEC":
            in_tables = False
            current_entry = None
            continue
        if not in_tables:
            continue
        if code == 0 and value in {
            "LAYER",
            "LTYPE",
            "STYLE",
            "DIMSTYLE",
            "APPID",
            "UCS",
            "VIEW",
            "VPORT",
            "BLOCK_RECORD",
        }:
            current_entry = value
            continue
        if current_entry and code == 2:
            names.append((current_entry, value))
            current_entry = None
    return names


def dxf_audit(
    doc_id: str,
    limit: int = 100,
    offset: int = 0,
    include_fixes: bool = True,
    response_format: str = "json",
) -> dict[str, Any]:
    """Run ezdxf's 64-code audit and expose symbolic codes, including block cycle 104."""
    auditor = store.get(doc_id).doc.audit()
    errors = [_audit_entry(item) for item in auditor.errors]
    data: dict[str, Any] = {
        "error_count": len(errors),
        "fix_count": len(auditor.fixes),
        "errors": paginate(errors, limit, offset),
    }
    if include_fixes:
        data["fixes"] = paginate([_audit_entry(item) for item in auditor.fixes], limit, offset)
    return response(data, response_format)


def dxf_validate_structure(
    doc_id: str, response_format: str = "json"
) -> dict[str, Any]:
    """Validate structural rules outside ezdxf.audit without duplicating its checks."""
    session = store.get(doc_id)
    doc = session.doc
    sections = _section_rows(session)
    present = {row["name"] for row in sections}
    required = _REQUIRED_R12 if doc.dxfversion <= "AC1009" else _REQUIRED_R13
    findings: list[dict[str, Any]] = []
    for missing in sorted(required - present):
        findings.append(
            {
                "check": "required_section",
                "severity": "error",
                "section": missing,
                "message": f"{missing} is required for {doc.acad_release}",
            }
        )
    if doc.dxfversion > "AC1009" and sections and sections[0]["name"] != "HEADER":
        findings.append(
            {
                "check": "header_order",
                "severity": "error",
                "message": "HEADER must be the first section for R13+",
            }
        )
    seed = str(doc.header.get("$HANDSEED", "0"))
    handles = [int(handle, 16) for handle in doc.entitydb.keys() if handle]
    largest = max(handles, default=0)
    try:
        seed_value = int(seed, 16)
    except ValueError:
        seed_value = -1
    if seed_value <= largest:
        findings.append(
            {
                "check": "handseed",
                "severity": "warning",
                "message": f"$HANDSEED ({seed}) <= largest handle ({largest:X})",
            }
        )
    if doc.dxfversion <= "AC1009" and int(doc.header.get("$HANDLING", 0)) not in {0, 1}:
        findings.append(
            {
                "check": "handling",
                "severity": "error",
                "message": "$HANDLING must be 0 or 1 in R12",
            }
        )
    collisions: dict[tuple[str, str], list[str]] = defaultdict(list)
    entries = _raw_symbol_names(session) or _name_entries(session)
    for kind, name in entries:
        collisions[(kind, name.casefold())].append(name)
    for (kind, _), names in collisions.items():
        if len(names) > 1:
            findings.append(
                {
                    "check": "name_collision",
                    "severity": "error",
                    "resource": kind,
                    "names": names,
                    "message": "case-insensitive names collide; AutoCAD may merge definitions",
                }
            )
    return response(
        {
            "valid": not any(item["severity"] == "error" for item in findings),
            "findings": findings,
            "audit_overlap_excluded": ["block_reference_cycle (AuditError 104)"],
        },
        response_format,
    )


def dxf_map_sections(doc_id: str, response_format: str = "json") -> dict[str, Any]:
    """Map section presence, canonical order, and raw tag counts."""
    session = store.get(doc_id)
    rows = _section_rows(session)
    expected = ["HEADER", "CLASSES", "TABLES", "BLOCKS", "ENTITIES", "OBJECTS"]
    positions = {name: index for index, name in enumerate(expected)}
    canonical = all(
        positions.get(row["name"], 999) <= positions.get(next_row["name"], 999)
        for row, next_row in pairwise(rows)
    )
    return response({"sections": rows, "canonical_core_order": canonical}, response_format)


def dxf_inspect_header(
    doc_id: str,
    prefix: str | None = None,
    limit: int = 200,
    offset: int = 0,
    response_format: str = "json",
) -> dict[str, Any]:
    """Inspect HEADER variables and ezdxf custom properties."""
    doc = store.get(doc_id).doc
    rows = [
        {"name": name, "value": json_safe(doc.header[name])}
        for name in doc.header.varnames()
        if prefix is None or name.startswith(prefix)
    ]
    metadata = doc.ezdxf_metadata()
    custom = {
        key: metadata.get(key)
        for key in ("CREATED_BY_EZDXF", "WRITTEN_BY_EZDXF")
        if key in metadata
    }
    return response({"variables": paginate(rows, limit, offset), "ezdxf_metadata": custom}, response_format)


def dxf_set_header_var(
    doc_id: str,
    name: str,
    value: Any,
    response_format: str = "json",
) -> dict[str, Any]:
    """Set a supported HEADER variable in a resident document."""
    if not name.startswith("$"):
        raise ValueError("HEADER variable must start with '$'")
    session = store.get(doc_id)
    previous = session.doc.header.get(name)
    session.doc.header[name] = value
    session.dirty = True
    return response({"name": name, "previous": json_safe(previous), "value": json_safe(value)}, response_format)


def dxf_list_tables(doc_id: str, response_format: str = "json") -> dict[str, Any]:
    """List the nine resource tables using real counts."""
    doc = store.get(doc_id).doc
    rows = []
    for name, table in (
        ("LAYER", doc.layers),
        ("LTYPE", doc.linetypes),
        ("STYLE", doc.styles),
        ("DIMSTYLE", doc.dimstyles),
        ("APPID", doc.appids),
        ("UCS", doc.ucs),
        ("VIEW", doc.views),
        ("VPORT", doc.viewports),
        ("BLOCK_RECORD", doc.block_records),
    ):
        rows.append({"name": name, "actual_count": len(table), "declared_count_70": None})
    return response({"tables": rows, "note": "DXF group-code 70 table counts are advisory"}, response_format)


def dxf_inspect_classes(
    doc_id: str,
    limit: int = 100,
    offset: int = 0,
    response_format: str = "json",
) -> dict[str, Any]:
    """Inspect CLASSES using (DXF name, C++ name) as the non-unique key."""
    doc = store.get(doc_id).doc
    rows = []
    for item in doc.classes:
        rows.append(
            {
                "dxf_name": item.dxf.get("name"),
                "cpp_name": item.dxf.get("cpp_class_name"),
                "app_name": item.dxf.get("app_name"),
                "flags": item.dxf.get("flags"),
                "instance_count": item.dxf.get("instance_count"),
                "was_a_proxy": item.dxf.get("was_a_proxy"),
                "is_an_entity": item.dxf.get("is_an_entity"),
            }
        )
    return response(paginate(rows, limit, offset), response_format)


def dxf_trace_handle(
    doc_id: str, handle: str, response_format: str = "json"
) -> dict[str, Any]:
    """Trace an entity handle, its owner, and all incoming typed references."""
    session = store.get(doc_id)
    target = handle.upper()
    entity = session.doc.entitydb.get(target)
    incoming = [item for item in _entity_references(session) if item["target"] == target]
    return response(
        {
            "handle": target,
            "exists": entity is not None,
            "entity_type": entity.dxftype() if entity is not None else None,
            "owner": entity.dxf.get("owner") if entity is not None else None,
            "incoming_references": incoming,
        },
        response_format,
    )


def dxf_find_dangling_handles(
    doc_id: str,
    limit: int = 100,
    offset: int = 0,
    response_format: str = "json",
) -> dict[str, Any]:
    """Find pointer/owner/XDATA handle references whose target does not exist."""
    session = store.get(doc_id)
    handles = {handle.upper() for handle in session.doc.entitydb.keys() if handle}
    rows = [item for item in _entity_references(session) if item["target"] not in handles]
    return response(paginate(rows, limit, offset), response_format)


def dxf_analyze_ownership(
    doc_id: str,
    limit: int = 100,
    offset: int = 0,
    response_format: str = "json",
) -> dict[str, Any]:
    """Build owner-child statistics and report orphaned or multiply-owned objects."""
    session = store.get(doc_id)
    handles = {handle.upper() for handle in session.doc.entitydb.keys() if handle}
    children: dict[str, list[str]] = defaultdict(list)
    orphans: list[dict[str, Any]] = []
    for entity in session.doc.entitydb.values():
        handle = entity.dxf.get("handle")
        owner = str(entity.dxf.get("owner", "0")).upper()
        if not handle or owner == "0":
            continue
        children[owner].append(handle)
        if owner not in handles:
            orphans.append({"handle": handle, "type": entity.dxftype(), "owner": owner})
    hard_owner_refs = [
        ref for ref in _entity_references(session) if ref["kind"] == "hard_owner"
    ]
    owner_counts = Counter(ref["target"] for ref in hard_owner_refs)
    multiple = [
        {"handle": handle, "hard_owner_reference_count": count}
        for handle, count in owner_counts.items()
        if count > 1
    ]
    return response(
        {
            "owners": len(children),
            "owned_entities": sum(map(len, children.values())),
            "orphans": paginate(orphans, limit, offset),
            "multiple_hard_owners": multiple,
        },
        response_format,
    )


def dxf_check_purge_safety(
    doc_id: str,
    handle: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Classify purge candidates by hard and soft incoming reference semantics."""
    session = store.get(doc_id)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ref in _entity_references(session):
        grouped[ref["target"]].append(ref)
    candidates = [handle.upper()] if handle else sorted(session.doc.entitydb.keys())
    rows = []
    for target in candidates:
        refs = grouped.get(target, [])
        hard = [ref for ref in refs if ref["hard"]]
        rows.append(
            {
                "handle": target,
                "safe_by_reference_rules": not hard,
                "hard_references": hard,
                "soft_references": [ref for ref in refs if not ref["hard"]],
            }
        )
    return response({"candidates": rows}, response_format)


def _used_resource_names(session: DocumentSession) -> dict[str, set[str]]:
    used: dict[str, set[str]] = {
        "layers": {"0", "Defpoints"},
        "linetypes": {"BYLAYER", "BYBLOCK", "Continuous"},
        "styles": {"Standard"},
        "dimstyles": {"Standard"},
    }
    for entity in session.doc.entitydb.values():
        if not entity.is_alive:
            continue
        for attr, key in (
            ("layer", "layers"),
            ("linetype", "linetypes"),
            ("style", "styles"),
            ("dimstyle", "dimstyles"),
        ):
            if not entity.dxf.is_supported(attr):
                continue
            value = entity.dxf.get(attr)
            if value:
                used[key].add(str(value))
    return used


def dxf_purge_unused(
    doc_id: str,
    dry_run: bool = True,
    response_format: str = "json",
) -> dict[str, Any]:
    """Preview or purge unreferenced blocks and unused resource table entries."""
    session = store.get(doc_id)
    doc = session.doc
    blocks = sorted(
        name
        for name in blkrefs.find_unreferenced_blocks(doc)
        if not name.startswith("*") and name not in {"_ARCHTICK", "_CLOSEDBLANK"}
    )
    used = _used_resource_names(session)
    tables: dict[str, list[str]] = {}
    for key, table in (
        ("layers", doc.layers),
        ("linetypes", doc.linetypes),
        ("styles", doc.styles),
        ("dimstyles", doc.dimstyles),
    ):
        tables[key] = [
            str(entry.dxf.name)
            for entry in table
            if str(entry.dxf.name) not in used[key]
        ]
    removed: dict[str, list[str]] = {"blocks": [], **{key: [] for key in tables}}
    if not dry_run:
        for name in blocks:
            doc.blocks.delete_block(name, safe=True)
            removed["blocks"].append(name)
        for key, table in (
            ("layers", doc.layers),
            ("linetypes", doc.linetypes),
            ("styles", doc.styles),
            ("dimstyles", doc.dimstyles),
        ):
            for name in tables[key]:
                table.remove(name)
                removed[key].append(name)
        session.dirty = any(removed.values())
    return response(
        {
            "dry_run": dry_run,
            "candidates": {"blocks": blocks, **tables},
            "removed": removed,
            "warning": "Reference hardness rules are necessary but third-party DXF files may violate them.",
        },
        response_format,
    )


def dxf_inspect_entitydb(
    doc_id: str, response_format: str = "json"
) -> dict[str, Any]:
    """Report entity database size, type counts, handle range, and collisions."""
    doc = store.get(doc_id).doc
    types = Counter(entity.dxftype() for entity in doc.entitydb.values() if entity.is_alive)
    handles = [int(handle, 16) for handle in doc.entitydb.keys() if handle]
    normalized = [handle.casefold() for handle in doc.entitydb.keys() if handle]
    collisions = [handle for handle, count in Counter(normalized).items() if count > 1]
    return response(
        {
            "total": len(doc.entitydb),
            "alive_by_type": dict(sorted(types.items())),
            "min_handle": f"{min(handles):X}" if handles else None,
            "max_handle": f"{max(handles):X}" if handles else None,
            "casefold_collisions": collisions,
        },
        response_format,
    )


def dxf_check_name_conformance(
    doc_id: str,
    target_version: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Check forbidden characters, R12 length/case, and case-insensitive collisions."""
    session = store.get(doc_id)
    r12 = (target_version or session.doc.dxfversion).upper() in {"R12", "AC1009"}
    findings: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for kind, name in _name_entries(session):
        grouped[(kind, name.casefold())].append(name)
        if _INVALID_NAME.search(name):
            findings.append({"resource": kind, "name": name, "issue": "forbidden_character"})
        if r12 and len(name) > 31:
            findings.append({"resource": kind, "name": name, "issue": "r12_length_gt_31"})
        if r12 and name != name.upper():
            findings.append({"resource": kind, "name": name, "issue": "r12_not_uppercase"})
    for (kind, _), names in grouped.items():
        if len(names) > 1:
            findings.append({"resource": kind, "names": names, "issue": "case_collision"})
    return response({"target_r12": r12, "findings": findings}, response_format)


def register_tools(mcp: FastMCP) -> None:
    read_only = (
        dxf_audit,
        dxf_validate_structure,
        dxf_map_sections,
        dxf_inspect_header,
        dxf_list_tables,
        dxf_inspect_classes,
        dxf_trace_handle,
        dxf_find_dangling_handles,
        dxf_analyze_ownership,
        dxf_check_purge_safety,
        dxf_inspect_entitydb,
        dxf_check_name_conformance,
    )
    for func in read_only:
        register(mcp, func, read_only=True)
    register(mcp, dxf_set_header_var, read_only=False)
    register(mcp, dxf_purge_unused, read_only=False, destructive=True, idempotent=False)
