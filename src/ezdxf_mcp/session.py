"""Resident document sessions keyed by opaque doc_id."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf import recover
from ezdxf.audit import Auditor
from ezdxf.document import Drawing

from .config import settings
from .errors import DocumentLimitError, DocumentNotFoundError
from .validation import safe_path


@dataclass(slots=True)
class DocumentSession:
    doc_id: str
    doc: Drawing
    source_path: Path | None
    loaded_with: str
    recovered: bool
    opened_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    initial_audit: Auditor | None = None
    warnings: list[str] = field(default_factory=list)
    dirty: bool = False

    def summary(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "source_path": str(self.source_path) if self.source_path else None,
            "loaded_with": self.loaded_with,
            "recovered": self.recovered,
            "dxfversion": self.doc.dxfversion,
            "acad_release": self.doc.acad_release,
            "encoding": self.doc.encoding,
            "output_encoding": self.doc.output_encoding,
            "opened_at": self.opened_at,
            "dirty": self.dirty,
            "warnings": list(self.warnings),
        }


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, DocumentSession] = {}
        self._lock = threading.RLock()

    def add(
        self,
        doc: Drawing,
        *,
        source_path: Path | None,
        loaded_with: str,
        recovered: bool = False,
        initial_audit: Auditor | None = None,
        warnings: list[str] | None = None,
    ) -> DocumentSession:
        with self._lock:
            if len(self._sessions) >= settings.max_docs:
                raise DocumentLimitError(
                    f"maximum resident documents reached ({settings.max_docs}); close one first"
                )
            doc_id = uuid.uuid4().hex
            session = DocumentSession(
                doc_id=doc_id,
                doc=doc,
                source_path=source_path,
                loaded_with=loaded_with,
                recovered=recovered,
                initial_audit=initial_audit,
                warnings=warnings or [],
            )
            self._sessions[doc_id] = session
            return session

    def get(self, doc_id: str) -> DocumentSession:
        with self._lock:
            try:
                return self._sessions[doc_id]
            except KeyError as exc:
                raise DocumentNotFoundError(f"unknown doc_id: {doc_id}") from exc

    def close(self, doc_id: str) -> DocumentSession:
        with self._lock:
            try:
                return self._sessions.pop(doc_id)
            except KeyError as exc:
                raise DocumentNotFoundError(f"unknown doc_id: {doc_id}") from exc

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [session.summary() for session in self._sessions.values()]

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


store = SessionStore()


def open_document(path: str, mode: str = "auto", errors: str = "surrogateescape") -> DocumentSession:
    if mode not in {"auto", "fast", "recover", "explore"}:
        raise ValueError("mode must be auto, fast, recover, or explore")
    if errors not in {"surrogateescape", "ignore", "strict"}:
        raise ValueError("errors must be surrogateescape, ignore, or strict")
    source = safe_path(path, must_exist=True, suffixes={".dxf", ".zip"})
    size_mb = source.stat().st_size / (1024 * 1024)
    if size_mb > settings.max_file_mb:
        raise ValueError(f"file is {size_mb:.1f} MB; limit is {settings.max_file_mb} MB")

    warnings: list[str] = []
    if source.suffix.lower() == ".zip":
        doc = ezdxf.readzip(source, errors=errors)
        return store.add(doc, source_path=source, loaded_with="readzip")

    if mode in {"auto", "fast"}:
        try:
            doc = ezdxf.readfile(source, errors=errors)
            return store.add(doc, source_path=source, loaded_with="readfile")
        except (ezdxf.DXFError, UnicodeError):
            if mode == "fast":
                raise
            warnings.append("readfile failed; loaded through recover.readfile")

    loader = recover.explore if mode == "explore" else recover.readfile
    doc, auditor = loader(source, errors=errors)
    loaded_with = "explore" if mode == "explore" else "recover"
    warnings.append(
        "Recovered documents may lose information or save as invalid DXF; inspect audit first."
    )
    return store.add(
        doc,
        source_path=source,
        loaded_with=loaded_with,
        recovered=True,
        initial_audit=auditor,
        warnings=warnings,
    )
