"""MCP tool registration with runtime evidence and safety annotations."""

from __future__ import annotations

import functools
import inspect
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar, cast

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .errors import DxfMcpError

F = TypeVar("F", bound=Callable[..., Any])
LOGGER = logging.getLogger("ezdxf_mcp.runtime")


def _annotate_result(result: Any, tool_name: str, started: float) -> Any:
    runtime = {
        "tool": tool_name,
        "status": "success",
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    if isinstance(result, dict):
        result.setdefault("_runtime", runtime)
        return result
    return {"result": result, "_runtime": runtime}


def runtime_logged(func: F) -> F:
    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            LOGGER.info("tool_start name=%s", func.__name__)
            try:
                result = await func(*args, **kwargs)
            except Exception:
                LOGGER.exception("tool_failure name=%s", func.__name__)
                raise
            LOGGER.info(
                "tool_success name=%s duration_ms=%.3f",
                func.__name__,
                (time.perf_counter() - started) * 1000,
            )
            return _annotate_result(result, func.__name__, started)

        return cast(F, async_wrapper)

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        LOGGER.info("tool_start name=%s", func.__name__)
        try:
            result = func(*args, **kwargs)
        except DxfMcpError:
            LOGGER.exception("tool_failure name=%s", func.__name__)
            raise
        except Exception:
            LOGGER.exception("tool_failure name=%s", func.__name__)
            raise
        LOGGER.info(
            "tool_success name=%s duration_ms=%.3f",
            func.__name__,
            (time.perf_counter() - started) * 1000,
        )
        return _annotate_result(result, func.__name__, started)

    return cast(F, wrapper)


def register(
    mcp: FastMCP,
    func: F,
    *,
    read_only: bool,
    destructive: bool = False,
    idempotent: bool = True,
) -> F:
    wrapped = runtime_logged(func)
    mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=read_only,
            destructiveHint=destructive,
            idempotentHint=idempotent,
            openWorldHint=False,
        ),
        structured_output=True,
    )(wrapped)
    return func
