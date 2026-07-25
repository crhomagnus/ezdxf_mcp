"""Document lifecycle and global option tools."""

from __future__ import annotations

from typing import Any

import ezdxf
from mcp.server.fastmcp import FastMCP

from ..formatting import response
from ..registry import register
from ..session import open_document, store

_OPTION_ALLOWLIST = {
    "filter_invalid_xdata_group_codes",
    "ignore_xref_stream_clipping_flags",
    "load_proxy_graphics",
    "log_unprocessed_tags",
    "preserve_proxy_graphics",
    "store_proxy_graphics",
    "write_fixed_meta_data_for_testing",
}
_VERSION_TO_RELEASE = {
    "AC1009": "R12",
    "AC1012": "R13",
    "AC1014": "R14",
    "AC1015": "R2000",
    "AC1018": "R2004",
    "AC1021": "R2007",
    "AC1024": "R2010",
    "AC1027": "R2013",
    "AC1032": "R2018",
}


def dxf_open_document(
    path: str,
    mode: str = "auto",
    errors: str = "surrogateescape",
    response_format: str = "json",
) -> dict[str, Any]:
    """Open a DXF/ZIP into a resident session, falling back to recovery in auto mode."""
    session = open_document(path, mode=mode, errors=errors)
    audit = session.initial_audit
    data = session.summary()
    data["initial_audit"] = {
        "errors": len(audit.errors) if audit else 0,
        "fixes": len(audit.fixes) if audit else 0,
    }
    return response(data, response_format)


def dxf_new_document(
    version: str = "R2018",
    setup: bool = True,
    units: int | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Create a resident DXF document without writing it."""
    normalized = version.upper()
    if normalized.startswith("AC"):
        normalized = _VERSION_TO_RELEASE.get(normalized, normalized)
    kwargs: dict[str, Any] = {"setup": setup}
    if units is not None:
        kwargs["units"] = units
    doc = ezdxf.new(normalized, **kwargs)
    session = store.add(doc, source_path=None, loaded_with="new")
    return response(session.summary(), response_format)


def dxf_close_document(doc_id: str, response_format: str = "json") -> dict[str, Any]:
    """Close a resident document without saving it."""
    session = store.close(doc_id)
    return response(
        {"closed": doc_id, "dirty_changes_discarded": session.dirty}, response_format
    )


def dxf_list_documents(response_format: str = "json") -> dict[str, Any]:
    """List resident document sessions."""
    return response({"documents": store.list()}, response_format)


def dxf_set_option(
    name: str,
    value: bool,
    response_format: str = "json",
) -> dict[str, Any]:
    """Set an allow-listed ezdxf global boolean option."""
    if name not in _OPTION_ALLOWLIST:
        raise ValueError(f"option not allowed; choose one of {sorted(_OPTION_ALLOWLIST)}")
    if not hasattr(ezdxf.options, name):
        raise ValueError(f"ezdxf 1.4.4 does not expose option {name!r}")
    previous = getattr(ezdxf.options, name)
    setattr(ezdxf.options, name, value)
    return response({"name": name, "previous": previous, "value": value}, response_format)


def register_tools(mcp: FastMCP) -> None:
    register(mcp, dxf_open_document, read_only=True)
    register(mcp, dxf_new_document, read_only=False, idempotent=False)
    register(mcp, dxf_close_document, read_only=False)
    register(mcp, dxf_list_documents, read_only=True)
    register(mcp, dxf_set_option, read_only=False)
