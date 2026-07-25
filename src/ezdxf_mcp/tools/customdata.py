"""XDATA, extension dictionaries, XRecords, AppData, and reactors."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ezdxf.lldxf.types import DXFTag
from ezdxf.urecord import UserRecord
from mcp.server.fastmcp import FastMCP

from ..formatting import json_safe, paginate, response
from ..registry import register
from ..session import store


def _entity(doc_id: str, handle: str):
    session = store.get(doc_id)
    entity = session.doc.entitydb.get(handle.upper())
    if entity is None:
        raise ValueError(f"handle not found: {handle}")
    return session, entity


def _tag_rows(tags) -> list[dict[str, Any]]:
    return [{"code": tag.code, "value": json_safe(tag.value)} for tag in tags]


def dxf_inventory_custom_data(
    doc_id: str,
    limit: int = 100,
    offset: int = 0,
    response_format: str = "json",
) -> dict[str, Any]:
    """Inventory third-party extension surfaces by APPID and entity handle."""
    doc = store.get(doc_id).doc
    rows = []
    appids: Counter[str] = Counter()
    xrecords = 0
    extension_dicts = 0
    reactor_entities = 0
    appdata_entities = 0
    for entity in doc.entitydb.values():
        if not entity.is_alive:
            continue
        entry: dict[str, Any] = {
            "handle": entity.dxf.get("handle"),
            "type": entity.dxftype(),
            "xdata_appids": [],
            "extension_dict_keys": [],
            "appdata_ids": [],
            "reactors": entity.get_reactors(),
        }
        xdata = getattr(entity, "xdata", None)
        if xdata is not None:
            names = list(xdata.data.keys())
            entry["xdata_appids"] = names
            appids.update(names)
        if entity.has_extension_dict:
            extension_dicts += 1
            xdict = entity.get_extension_dict()
            entry["extension_dict_keys"] = list(xdict.keys())
            xrecords += sum(1 for _, item in xdict.items() if item.dxftype() == "XRECORD")
        appdata = getattr(entity, "appdata", None)
        if appdata is not None:
            names = list(appdata.data.keys())
            entry["appdata_ids"] = names
            if names:
                appdata_entities += 1
        if entry["reactors"]:
            reactor_entities += 1
        if (
            entry["xdata_appids"]
            or entry["extension_dict_keys"]
            or entry["appdata_ids"]
            or entry["reactors"]
        ):
            rows.append(entry)
    return response(
        {
            "xdata_by_appid": dict(appids),
            "entities_with_extensions": len(rows),
            "extension_dictionaries": extension_dicts,
            "xrecords": xrecords,
            "entities_with_appdata": appdata_entities,
            "entities_with_reactors": reactor_entities,
            "entities": paginate(rows, limit, offset),
        },
        response_format,
    )


def dxf_get_xdata(
    doc_id: str, handle: str, appid: str, response_format: str = "json"
) -> dict[str, Any]:
    """Read XDATA tags for an APPID."""
    _, entity = _entity(doc_id, handle)
    return response(
        {"handle": handle.upper(), "appid": appid, "tags": _tag_rows(entity.get_xdata(appid))},
        response_format,
    )


def dxf_set_xdata(
    doc_id: str,
    handle: str,
    appid: str,
    tags: list[list[Any]] | None = None,
    action: str = "set",
    response_format: str = "json",
) -> dict[str, Any]:
    """Set or discard XDATA, creating its APPID table entry when needed."""
    session, entity = _entity(doc_id, handle)
    if action == "discard":
        entity.discard_xdata(appid)
    elif action == "set":
        if appid not in session.doc.appids:
            session.doc.appids.new(appid)
        entity.set_xdata(appid, [DXFTag(int(code), value) for code, value in (tags or [])])
    else:
        raise ValueError("action must be set or discard")
    session.dirty = True
    current = [] if action == "discard" else _tag_rows(entity.get_xdata(appid))
    return response({"handle": handle.upper(), "appid": appid, "tags": current}, response_format)


def dxf_get_extension_dict(
    doc_id: str, handle: str, response_format: str = "json"
) -> dict[str, Any]:
    """Inspect an entity extension dictionary and its object types."""
    _, entity = _entity(doc_id, handle)
    if not entity.has_extension_dict:
        return response({"handle": handle.upper(), "exists": False, "items": []}, response_format)
    xdict = entity.get_extension_dict()
    rows = [
        {"name": name, "handle": item.dxf.get("handle"), "type": item.dxftype()}
        for name, item in xdict.items()
    ]
    return response({"handle": handle.upper(), "exists": True, "items": rows}, response_format)


def dxf_manage_xrecord(
    doc_id: str,
    handle: str,
    name: str,
    action: str = "get",
    data: list[Any] | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Get, set, or delete a typed UserRecord stored in an extension dictionary."""
    session, entity = _entity(doc_id, handle)
    if action == "set":
        xdict = entity.get_extension_dict() if entity.has_extension_dict else entity.new_extension_dict()
        try:
            xrecord = xdict.get(name)
        except KeyError:
            xrecord = xdict.add_xrecord(name)
        with UserRecord(xrecord, name=name) as record:
            record.data[:] = data or []
        session.dirty = True
    elif action == "delete":
        if not entity.has_extension_dict:
            raise ValueError("entity has no extension dictionary")
        entity.get_extension_dict().discard(name)
        session.dirty = True
        return response({"deleted": name, "handle": handle.upper()}, response_format)
    elif action == "get":
        if not entity.has_extension_dict:
            raise ValueError("entity has no extension dictionary")
        xrecord = entity.get_extension_dict().get(name)
    else:
        raise ValueError("action must be get, set, or delete")
    record = UserRecord(xrecord, name=name)
    return response(
        {
            "handle": handle.upper(),
            "name": name,
            "xrecord_handle": record.handle,
            "data": json_safe(record.data),
        },
        response_format,
    )


def dxf_manage_appdata(
    doc_id: str,
    handle: str,
    appid: str,
    action: str = "get",
    tags: list[list[Any]] | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Get, set, or discard application-defined `{APPID ...}` data."""
    session, entity = _entity(doc_id, handle)
    if action == "set":
        entity.set_app_data(appid, [DXFTag(int(code), value) for code, value in (tags or [])])
        session.dirty = True
    elif action == "discard":
        entity.discard_app_data(appid)
        session.dirty = True
        return response({"discarded": appid, "handle": handle.upper()}, response_format)
    elif action != "get":
        raise ValueError("action must be get, set, or discard")
    return response(
        {"handle": handle.upper(), "appid": appid, "tags": _tag_rows(entity.get_app_data(appid))},
        response_format,
    )


def dxf_manage_reactors(
    doc_id: str,
    handle: str,
    action: str = "get",
    reactor_handle: str | None = None,
    handles: list[str] | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Get, append, discard, or replace persistent reactor handles."""
    session, entity = _entity(doc_id, handle)
    if action == "append":
        if not reactor_handle:
            raise ValueError("append requires reactor_handle")
        entity.append_reactor_handle(reactor_handle.upper())
        session.dirty = True
    elif action == "discard":
        if not reactor_handle:
            raise ValueError("discard requires reactor_handle")
        entity.discard_reactor_handle(reactor_handle.upper())
        session.dirty = True
    elif action == "set":
        entity.set_reactors([item.upper() for item in (handles or [])])
        session.dirty = True
    elif action != "get":
        raise ValueError("action must be get, append, discard, or set")
    return response(
        {"handle": handle.upper(), "reactors": entity.get_reactors()}, response_format
    )


def register_tools(mcp: FastMCP) -> None:
    for read_func in (dxf_inventory_custom_data, dxf_get_xdata, dxf_get_extension_dict):
        register(mcp, read_func, read_only=True)
    for write_func in (
        dxf_set_xdata,
        dxf_manage_xrecord,
        dxf_manage_appdata,
        dxf_manage_reactors,
    ):
        register(mcp, write_func, read_only=False, idempotent=False)
