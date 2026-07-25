"""Units, real scaling, and target-version compatibility checks."""

from __future__ import annotations

from typing import Any

from ezdxf import transform, units
from ezdxf.enums import InsertUnits
from ezdxf.math import Matrix44
from mcp.server.fastmcp import FastMCP

from ..formatting import response
from ..registry import register
from ..session import store
from .structure import dxf_check_name_conformance, dxf_validate_structure

_RELEASE_TO_CODE = {
    "R12": "AC1009",
    "R13": "AC1012",
    "R14": "AC1014",
    "R2000": "AC1015",
    "R2004": "AC1018",
    "R2007": "AC1021",
    "R2010": "AC1024",
    "R2013": "AC1027",
    "R2018": "AC1032",
}


def _unit(value: int | str) -> InsertUnits:
    if isinstance(value, int) or str(value).isdigit():
        return InsertUnits(int(value))
    try:
        return InsertUnits[str(value).upper()]
    except KeyError as exc:
        raise ValueError(
            f"unknown units; choose numeric DXF code or {[item.name for item in InsertUnits]}"
        ) from exc


def _target_code(version: str) -> str:
    upper = version.upper()
    if upper.startswith("AC"):
        return upper
    try:
        return _RELEASE_TO_CODE[upper]
    except KeyError as exc:
        raise ValueError(f"unsupported target version: {version}") from exc


def dxf_inspect_units(doc_id: str, response_format: str = "json") -> dict[str, Any]:
    """Inspect document/header units and unit declarations for every block."""
    doc = store.get(doc_id).doc
    block_rows = []
    for block in doc.blocks:
        raw = int(block.block_record.dxf.get("units", 0))
        block_rows.append(
            {"name": block.name, "units": raw, "unit_name": units.unit_name(raw)}
        )
    return response(
        {
            "document_units": int(doc.units),
            "document_unit_name": units.unit_name(doc.units),
            "header": {
                "$INSUNITS": doc.header.get("$INSUNITS"),
                "$MEASUREMENT": doc.header.get("$MEASUREMENT"),
                "$LUNITS": doc.header.get("$LUNITS"),
                "$AUNITS": doc.header.get("$AUNITS"),
            },
            "blocks": block_rows,
        },
        response_format,
    )


def dxf_set_units(
    doc_id: str, unit: int | str, response_format: str = "json"
) -> dict[str, Any]:
    """Set the document unit declaration without rescaling geometry."""
    session = store.get(doc_id)
    target = _unit(unit)
    previous = int(session.doc.units)
    session.doc.units = target
    session.dirty = True
    return response(
        {
            "previous": previous,
            "units": int(target),
            "unit_name": units.unit_name(target),
            "geometry_rescaled": False,
            "warning": "This operation only changes the declaration; use dxf_convert_units to rescale.",
        },
        response_format,
    )


def dxf_convert_units(
    doc_id: str,
    target_unit: int | str,
    source_unit: int | str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Scale actual geometry and update the document unit declaration."""
    session = store.get(doc_id)
    source = _unit(source_unit if source_unit is not None else int(session.doc.units))
    target = _unit(target_unit)
    if source == InsertUnits.Unitless or target == InsertUnits.Unitless:
        raise ValueError("real conversion requires non-Unitless source and target")
    factor = units.conversion_factor(source, target)
    entities = [
        entity
        for entity in session.doc.entitydb.values()
        if entity.is_alive and entity.dxftype() not in {"LAYOUT", "DICTIONARY", "XRECORD"}
    ]
    logger = transform.inplace(entities, Matrix44.scale(factor))
    session.doc.units = target
    session.dirty = True
    return response(
        {
            "source": source.name,
            "target": target.name,
            "factor": factor,
            "factor_display": round(factor, 12),
            "entities_considered": len(entities),
            "transform_errors": [
                {
                    "error": str(error),
                    "message": message,
                    "handle": entity.dxf.get("handle"),
                    "type": entity.dxftype(),
                }
                for error, message, entity in logger
            ],
        },
        response_format,
    )


def dxf_check_block_scale(
    doc_id: str, tolerance: float = 1e-9, response_format: str = "json"
) -> dict[str, Any]:
    """Find INSERT scales that do not compensate for block/document unit differences."""
    doc = store.get(doc_id).doc
    findings = []
    document_unit = InsertUnits(int(doc.units))
    if document_unit == InsertUnits.Unitless:
        return response(
            {"findings": [], "warning": "document units are Unitless; compensation is undefined"},
            response_format,
        )
    for insert in doc.query("INSERT"):
        block = doc.blocks.get(insert.dxf.name)
        block_unit = InsertUnits(int(block.block_record.dxf.get("units", 0)))
        if block_unit in {InsertUnits.Unitless, document_unit}:
            continue
        expected = units.conversion_factor(block_unit, document_unit)
        actual = [insert.dxf.xscale, insert.dxf.yscale, insert.dxf.zscale]
        if any(abs(scale - expected) > tolerance for scale in actual):
            findings.append(
                {
                    "handle": insert.dxf.handle,
                    "block": insert.dxf.name,
                    "block_units": block_unit.name,
                    "document_units": document_unit.name,
                    "expected_scale": expected,
                    "actual_scale": actual,
                }
            )
    return response({"findings": findings}, response_format)


def _version_findings(doc_id: str, target_version: str) -> list[dict[str, Any]]:
    doc = store.get(doc_id).doc
    target = _target_code(target_version)
    findings = []
    for entity in doc.entitydb.values():
        if not entity.is_alive:
            continue
        minimum = getattr(entity, "MIN_DXF_VERSION_FOR_EXPORT", "AC1009")
        if minimum and minimum > target:
            findings.append(
                {
                    "handle": entity.dxf.get("handle"),
                    "type": entity.dxftype(),
                    "minimum_version": minimum,
                    "target": target,
                    "degradation": "entity is not exportable to target",
                }
            )
    if target == "AC1009":
        for entity_type in ("MTEXT", "LWPOLYLINE", "HATCH", "SPLINE", "ELLIPSE", "IMAGE"):
            count = len(doc.query(entity_type))
            if count:
                findings.append(
                    {
                        "type": entity_type,
                        "count": count,
                        "target": target,
                        "degradation": "requires R12 export conversion or omission",
                    }
                )
    return findings


def dxf_check_version_compat(
    doc_id: str, target_version: str, response_format: str = "json"
) -> dict[str, Any]:
    """Simulate a target version and list degradation without writing."""
    target = _target_code(target_version)
    findings = _version_findings(doc_id, target)
    return response(
        {
            "target_version": target,
            "compatible_without_degradation": not findings,
            "findings": findings,
            "written": False,
        },
        response_format,
    )


def dxf_check_r12_compat(
    doc_id: str, response_format: str = "json"
) -> dict[str, Any]:
    """Run R12 entity and symbol-name compatibility checks."""
    version = _version_findings(doc_id, "AC1009")
    names = dxf_check_name_conformance(doc_id, target_version="R12", response_format="json")
    return response(
        {
            "version_findings": version,
            "name_findings": names["data"]["findings"],
        },
        response_format,
    )


def dxf_check_acad_compat(
    doc_id: str, response_format: str = "json"
) -> dict[str, Any]:
    """Combine structural, class/name, and audit checks relevant to AutoCAD loading."""
    structure = dxf_validate_structure(doc_id, response_format="json")["data"]
    doc = store.get(doc_id).doc
    auditor = doc.audit()
    return response(
        {
            "structural": structure,
            "audit_error_count": len(auditor.errors),
            "blocking_audit_codes": sorted({entry.code for entry in auditor.errors}),
            "class_count": sum(1 for _ in doc.classes),
        },
        response_format,
    )


def register_tools(mcp: FastMCP) -> None:
    for func in (
        dxf_inspect_units,
        dxf_check_block_scale,
        dxf_check_version_compat,
        dxf_check_r12_compat,
        dxf_check_acad_compat,
    ):
        register(mcp, func, read_only=True)
    register(mcp, dxf_set_units, read_only=False)
    register(mcp, dxf_convert_units, read_only=False, idempotent=False)
