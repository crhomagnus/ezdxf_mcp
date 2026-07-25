"""Actionable server exceptions."""

from __future__ import annotations


class DxfMcpError(RuntimeError):
    """Base class for errors safe to return through MCP."""

    code = "dxf_mcp_error"

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class PathValidationError(DxfMcpError):
    code = "invalid_path"


class DocumentNotFoundError(DxfMcpError):
    code = "document_not_found"


class DocumentLimitError(DxfMcpError):
    code = "document_limit"


class UnsafeOperationError(DxfMcpError):
    code = "unsafe_operation"


class UnsupportedOperationError(DxfMcpError):
    code = "unsupported_operation"
