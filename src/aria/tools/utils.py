"""Shared utility functions for all tool modules.

This module provides common utilities that are used across multiple tool
subpackages to ensure consistency in timestamp handling, JSON serialization,
and response formatting.
"""

import inspect
import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def utc_timestamp() -> str:
    """Generate a UTC ISO timestamp string.

    Returns:
        str: ISO 8601 formatted timestamp in UTC timezone.
    """
    return datetime.now(UTC).isoformat()


def safe_json(
    data: dict[str, Any],
    *,
    default: Any = None,
    indent: int | None = 2,
    ensure_ascii: bool = False,
) -> str:
    """Safe JSON serialization with error handling.

    Args:
        data: Dictionary to serialize to JSON.
        default: Default handler for objects that can't be serialized.
                 If None, uses str() as fallback for unknown types.
        indent: JSON indentation level. None for compact output.
        ensure_ascii: Whether to escape non-ASCII characters.

    Returns:
        str: JSON string or error message if serialization fails.
    """
    if default is None:
        default = _default_json_handler

    try:
        return json.dumps(
            data,
            default=default,
            indent=indent,
            ensure_ascii=ensure_ascii,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        logger.error(f"JSON serialization failed: {exc}")
        return json.dumps({"error": "Serialization failed", "details": str(exc)})


def _default_json_handler(obj: Any) -> str:
    """Default handler for JSON serialization of non-serializable objects.

    Args:
        obj: Object that couldn't be serialized by default JSON encoder.

    Returns:
        str: String representation of the object.
    """
    return str(obj)


def tool_success_response(
    tool: str,
    reason: str,
    data: dict[str, Any],
    **context: Any,
) -> str:
    """Generate a standardized JSON success response.

    Returns a JSON string with standardized success format.

    Args:
        tool: Name of the tool that generated the response.
        reason: The agent's stated reason for calling this tool.
        data: The response data payload.
        **context: Additional tool-specific context fields.

    Returns:
        JSON string with standardized success format.
    """

    if not reason or not reason.strip():
        reason = f"unspecified_{tool}_operation"

    response: dict[str, Any] = {
        "status": "success",
        "tool": tool,
        "reason": reason,
        "timestamp": utc_timestamp(),
        "data": data,
    }
    if context:
        response["context"] = context

    return safe_json(response)


def tool_error_response(
    tool: str,
    reason: str,
    exc: Exception,
    **context: Any,
) -> str:
    """Generate a standardized JSON error response from an exception.

    Args:
        tool: Name of the tool that generated the error.
        reason: The agent's stated reason for calling this tool.
        exc: The exception that occurred.
        **context: Additional tool-specific context fields.

    Returns:
        JSON string with standardized error format.
    """
    error_code = getattr(exc, "code", type(exc).__name__.upper())
    recoverable = getattr(exc, "recoverable", False)
    how_to_fix = getattr(exc, "how_to_fix", None)

    error_block: dict[str, Any] = {
        "code": error_code,
        "message": str(exc),
        "type": type(exc).__name__,
        "recoverable": recoverable,
    }
    if how_to_fix:
        error_block["how_to_fix"] = how_to_fix

    response: dict[str, Any] = {
        "status": "error",
        "tool": tool,
        "reason": reason,
        "timestamp": utc_timestamp(),
        "error": error_block,
    }
    if context:
        response["context"] = context

    # Structured error logging for observability
    logger.error(
        "Tool error occurred",
        extra={
            "tool": tool,
            "reason": reason,
            "error_code": error_code,
            "recoverable": recoverable,
            "error_type": type(exc).__name__,
        },
        exc_info=True,
    )

    return safe_json(response)


def tool_response(
    tool: str,
    reason: str,
    data: dict[str, Any] | None = None,
    exc: Exception | None = None,
    **context: Any,
) -> str:
    """Convenience wrapper for generating tool responses.

    Automatically chooses between success and error response based on
    whether an exception is provided.

    Args:
        tool: Name of the tool that generated the response.
        reason: The agent's stated reason for calling this tool.
        data: The response data payload (for success responses).
        exc: The exception that occurred (for error responses).
        **context: Additional tool-specific context fields.

    Returns:
        JSON string with standardized format.
    """
    if exc is not None:
        return tool_error_response(tool, reason, exc, **context)

    if data is None:
        data = {}

    return tool_success_response(tool, reason, data, **context)


def get_function_name(depth: int = 1) -> str:
    """
    Get the name of the function at a specific call depth.

    Args:
        depth: Number of frames to go back from the caller of this function.
            Default is 1 (the immediate caller of the function that called
            this helper).

    Returns:
        The function name as a string, or ``"<unknown>"`` if unable
        to determine.

    Example:
        If ``function_a`` calls ``function_b`` which calls
        ``_get_function_name(1)``, it returns ``"function_a"`` (the caller
        of the function that invoked this helper).
    """
    try:
        frame = inspect.currentframe()
        if not frame:
            return "<unknown>"
        frame = frame.f_back
        for _ in range(depth - 1):
            if not frame:
                return "<unknown>"
            frame = frame.f_back
        if not frame:
            return "<unknown>"
        return frame.f_code.co_name
    except AttributeError:
        return "<unknown>"
