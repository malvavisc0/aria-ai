"""Aria tool package.

This top-level package exports common helpers used by multiple tool
subpackages.
"""

from typing import Annotated, Any

from pydantic import Field

from aria.tools.decorators import log_tool_call
from aria.tools.utils import (
    get_function_name,
    safe_json,
    tool_error_response,
    tool_response,
    tool_success_response,
    utc_timestamp,
)

#: Annotated type for the ``reason`` parameter shared by all tools.
#: Ensures the JSON schema sent to the LLM includes both a description
#: and marks the field as required.
Reason = Annotated[
    str,
    Field(description="Required. Brief explanation of why you are calling this tool."),
]


def ok(*, tool: str, reason: str, data: dict[str, Any]) -> str:
    """Build a success response for *tool*."""
    return tool_response(tool=tool, reason=reason, data=data)


def err(
    *,
    tool: str,
    reason: str,
    code: str,
    message: str,
    how_to_fix: str | None = None,
    **extra: Any,
) -> str:
    """Build a structured error response for *tool*."""
    e: dict[str, Any] = {"code": code, "message": message, "recoverable": True}
    if how_to_fix:
        e["how_to_fix"] = how_to_fix
    e.update(extra)
    return tool_response(tool=tool, reason=reason, data={"error": e})


__all__: list[str] = [
    "Reason",
    "err",
    "get_function_name",
    "log_tool_call",
    "ok",
    "safe_json",
    "tool_error_response",
    "tool_response",
    "tool_success_response",
    "utc_timestamp",
]
