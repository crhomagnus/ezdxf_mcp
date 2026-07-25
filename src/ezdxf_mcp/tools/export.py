"""Safe DXF save, version export, JSON tags, meshes, code, binary, and ZIP."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import ezdxf
from ezdxf import disassemble, r12strict
from ezdxf.addons import dxf2code, meshex, r12export
from ezdxf.render import MeshBuilder
from mcp.server.fastmcp import FastMCP

from ..formatting import response
from ..registry import register
from ..session import DocumentSession, store
from ..validation import require_overwrite, safe_path
from .lexical import document_tag_pairs
from .units import _target_code, _version_findings


def _clone_document(session: DocumentSession):
    stream = io.StringIO()
    session.doc.write(stream)
    stream.seek(0)
    return ezdxf.read(stream)


def _prepare_r12_source(doc: Any) -> int:
    """Replace MESH entities by bound POLYFACE entities before R12 export.

    ezdxf 1.4.4 creates an unbound virtual POLYFACE without the mandatory
    SEQEND while exporting MESH directly. Rendering into the cloned document
    first creates a valid linked-entity structure and leaves the resident
    session untouched.
    """
    converted = 0
    for layout in doc.layouts_and_blocks():
        for mesh in list(layout.query("MESH")):
            MeshBuilder.from_mesh(mesh).render_polyface(
                layout,
                dxfattribs={
                    "layer": mesh.dxf.layer,
                    "linetype": mesh.dxf.linetype,
                    "color": mesh.dxf.color,
                },
            )
            layout.delete_entity(mesh)
            converted += 1
    return converted


def _guard_recovered(session: DocumentSession, allow_recovered_write: bool) -> None:
    if session.recovered and not allow_recovered_write:
        raise ValueError(
            "document was loaded by recovery; pass allow_recovered_write=true only after audit"
        )


def dxf_save(
    doc_id: str,
    overwrite: bool = False,
    allow_recovered_write: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Save to the original workspace DXF only with explicit overwrite permission."""
    session = store.get(doc_id)
    _guard_recovered(session, allow_recovered_write)
    if session.source_path is None or session.source_path.suffix.lower() != ".dxf":
        raise ValueError("session has no original DXF path; use dxf_save_as")
    if not overwrite:
        raise ValueError("dxf_save requires overwrite=true")
    target = safe_path(str(session.source_path), must_exist=True, suffixes={".dxf"})
    session.doc.saveas(target)
    session.dirty = False
    return response(
        {"output": str(target), "bytes": target.stat().st_size, "overwritten": True},
        response_format,
    )


def dxf_save_as(
    doc_id: str,
    output_path: str,
    target_version: str | None = None,
    overwrite: bool = False,
    allow_recovered_write: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Export a copy, optionally changing DXF version, with a mandatory degradation report."""
    session = store.get(doc_id)
    _guard_recovered(session, allow_recovered_write)
    target = safe_path(output_path, suffixes={".dxf"})
    require_overwrite(target, overwrite)
    out_doc = _clone_document(session)
    findings: list[dict[str, Any]] = []
    version = session.doc.dxfversion
    if target_version:
        version = _target_code(target_version)
        findings = _version_findings(doc_id, version)
        if version == "AC1009":
            _prepare_r12_source(out_doc)
            out_doc = r12export.convert(out_doc)
        else:
            out_doc.dxfversion = version
    target.parent.mkdir(parents=True, exist_ok=True)
    out_doc.saveas(target)
    return response(
        {
            "output": str(target),
            "bytes": target.stat().st_size,
            "target_version": version,
            "degradation_findings": findings,
            "source_session_mutated": False,
        },
        response_format,
    )


def dxf_export_r12_strict(
    doc_id: str,
    output_path: str,
    overwrite: bool = False,
    max_sagitta: float = 0.01,
    translate_names: bool = True,
    allow_recovered_write: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Export strict R12 on a copy; destructive symbol translation never touches the session."""
    session = store.get(doc_id)
    _guard_recovered(session, allow_recovered_write)
    target = safe_path(output_path, suffixes={".dxf"})
    require_overwrite(target, overwrite)
    source_doc = _clone_document(session)
    converted_meshes = _prepare_r12_source(source_doc)
    out_doc = r12export.convert(source_doc, max_sagitta=max_sagitta)
    r12strict.make_acad_compatible(out_doc)
    if translate_names:
        r12strict.translate_names(out_doc)
    target.parent.mkdir(parents=True, exist_ok=True)
    out_doc.saveas(target)
    return response(
        {
            "output": str(target),
            "bytes": target.stat().st_size,
            "version": out_doc.dxfversion,
            "translated_names": translate_names,
            "source_session_mutated": False,
            "meshes_preconverted": converted_meshes,
            "degradation_findings": _version_findings(doc_id, "AC1009"),
        },
        response_format,
    )


def dxf_export_json_tags(
    doc_id: str,
    output_path: str,
    compact: bool = True,
    overwrite: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Export raw JSON-encoded DXF tags."""
    target = safe_path(output_path, suffixes={".json"})
    require_overwrite(target, overwrite)
    pairs = document_tag_pairs(store.get(doc_id).doc)
    content = json.dumps(
        pairs if compact else [[str(code), str(value)] for code, value in pairs],
        ensure_ascii=False,
        indent=2,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return response(
        {"output": str(target), "bytes": target.stat().st_size, "compact": compact},
        response_format,
    )


def dxf_export_mesh(
    doc_id: str,
    output_path: str,
    format: str = "stl",
    layout: str | None = None,
    overwrite: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Export renderable 3D primitives as STL, OBJ, OFF, or binary PLY."""
    session = store.get(doc_id)
    target = safe_path(output_path, suffixes={".stl", ".obj", ".off", ".ply"})
    require_overwrite(target, overwrite)
    source = (
        session.doc.modelspace()
        if layout in {None, "", "Model", "Modelspace"}
        else session.doc.layouts.get(layout)
    )
    meshes = list(disassemble.to_meshes(disassemble.to_primitives(source)))
    combined = MeshBuilder()
    for mesh in meshes:
        combined.add_mesh(mesh=mesh)
    kind = format.lower()
    if kind == "stl":
        content: str | bytes = meshex.stl_dumps(combined)
    elif kind == "obj":
        content = meshex.obj_dumps(combined)
    elif kind == "off":
        content = meshex.off_dumps(combined)
    elif kind == "ply":
        content = meshex.ply_dumpb(combined)
    else:
        raise ValueError("format must be stl, obj, off, or ply")
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    return response(
        {"output": str(target), "bytes": target.stat().st_size, "mesh_count": len(meshes)},
        response_format,
    )


def dxf_generate_code(
    doc_id: str,
    output_path: str,
    handles: list[str] | None = None,
    block_name: str | None = None,
    overwrite: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Generate executable ezdxf Python code for selected entities or one block."""
    session = store.get(doc_id)
    target = safe_path(output_path, suffixes={".py"})
    require_overwrite(target, overwrite)
    if block_name:
        code = dxf2code.block_to_code(session.doc.blocks[block_name])
    else:
        entities = (
            [
                session.doc.entitydb.get(handle.upper())
                for handle in handles or []
                if session.doc.entitydb.get(handle.upper()) is not None
            ]
            if handles
            else list(session.doc.modelspace())
        )
        code = dxf2code.entities_to_code(entities)
    content = f"{code.import_str()}\\n\\n{code.code_str()}\\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return response({"output": str(target), "bytes": target.stat().st_size}, response_format)


def dxf_export_binary(
    doc_id: str,
    output_path: str,
    overwrite: bool = False,
    allow_recovered_write: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Export binary DXF without mutating the resident document."""
    session = store.get(doc_id)
    _guard_recovered(session, allow_recovered_write)
    target = safe_path(output_path, suffixes={".dxf"})
    require_overwrite(target, overwrite)
    target.parent.mkdir(parents=True, exist_ok=True)
    _clone_document(session).saveas(target, fmt="bin")
    return response(
        {"output": str(target), "bytes": target.stat().st_size, "format": "binary"},
        response_format,
    )


def dxf_export_zip(
    doc_id: str,
    output_path: str,
    member_name: str = "drawing.dxf",
    overwrite: bool = False,
    allow_recovered_write: bool = False,
    response_format: str = "json",
) -> dict[str, Any]:
    """Export an ASCII DXF inside a ZIP archive."""
    session = store.get(doc_id)
    _guard_recovered(session, allow_recovered_write)
    target = safe_path(output_path, suffixes={".zip"})
    require_overwrite(target, overwrite)
    if "/" in member_name or "\\" in member_name or not member_name.lower().endswith(".dxf"):
        raise ValueError("member_name must be a plain .dxf filename")
    stream = io.StringIO()
    session.doc.write(stream)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, stream.getvalue())
    return response(
        {"output": str(target), "bytes": target.stat().st_size, "member": member_name},
        response_format,
    )


def register_tools(mcp: FastMCP) -> None:
    for func in (
        dxf_save,
        dxf_save_as,
        dxf_export_r12_strict,
        dxf_export_json_tags,
        dxf_export_mesh,
        dxf_generate_code,
        dxf_export_binary,
        dxf_export_zip,
    ):
        register(mcp, func, read_only=False, destructive=True, idempotent=False)
