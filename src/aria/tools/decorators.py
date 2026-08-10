"""Shared decorators for tool functions."""

import inspect
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from loguru import logger

# Dedicated logger for tool calls — tagged so the sink filter can match
# precisely via r["extra"].get("tool_call") instead of fragile string checks.
_tool_log = logger.bind(tool_call=True)


def _truncate(value: Any, max_len: int = 500) -> str:
    """Truncate a value for logging with an indicator of original size."""
    s = repr(value) if not isinstance(value, str) else value
    if len(s) > max_len:
        return s[:max_len] + f"... [{len(s)} chars total]"
    return s


def _extract_reason(args: tuple, kwargs: dict) -> str:
    """Extract the reason string from args or kwargs."""
    return kwargs.get("reason") or (
        args[0] if args and isinstance(args[0], str) else "unknown"
    )


def _extract_args_summary(kwargs: dict) -> str:
    """Build a truncated summary of non-reason kwargs for logging."""
    filtered = {k: v for k, v in kwargs.items() if k != "reason"}
    if not filtered:
        return ""
    return _truncate(filtered, max_len=400)


def log_tool_call(func: Callable) -> Callable:
    """Decorator that logs tool call entry and exit with structured data.

    Logs:
        - Entry: tool name, reason, truncated arguments
        - Exit:  tool name, duration, status (success/error), truncated result

    Args:
        func: The function to wrap.

    Returns:
        Wrapped function that logs calls.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        name = func.__name__
        reason = _extract_reason(args, kwargs)
        args_summary = _extract_args_summary(kwargs)
        start = time.time()

        _tool_log.debug(
            f'{name} → START | reason="{reason}"'
            + (f" | args={args_summary}" if args_summary else "")
        )

        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start
            _tool_log.debug(
                f"{name} → END | duration={elapsed:.2f}s | status=success"
                f" | result_len={len(str(result))}"
            )
            return result
        except Exception as exc:
            elapsed = time.time() - start
            _tool_log.debug(
                f'{name} → END | duration={elapsed:.2f}s | status=error | error="{exc}"'
            )
            raise

    @wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        name = func.__name__
        reason = _extract_reason(args, kwargs)
        args_summary = _extract_args_summary(kwargs)
        start = time.time()

        _tool_log.debug(
            f'{name} → START | reason="{reason}"'
            + (f" | args={args_summary}" if args_summary else "")
        )

        try:
            result = await func(*args, **kwargs)
            elapsed = time.time() - start
            _tool_log.debug(
                f"{name} → END | duration={elapsed:.2f}s | status=success"
                f" | result_len={len(str(result))}"
            )
            return result
        except Exception as exc:
            elapsed = time.time() - start
            _tool_log.debug(
                f'{name} → END | duration={elapsed:.2f}s | status=error | error="{exc}"'
            )
            raise

    if inspect.iscoroutinefunction(func):
        return async_wrapper
    return wrapper


def tool_function(
    operation_name: str,
    *,
    validate: dict[str, bool] | None = None,
    error_handler: Callable | None = None,
    validation_decorator: Callable | None = None,
) -> Callable:
    """Compose logging, validation, and error handling for tool functions.

    Wrapper order (outermost -> innermost):
    1. log_tool_call
    2. validation decorator (optional)
    3. error handler decorator (optional)

    Args:
        operation_name: Operation name passed to the decorator factory.
        validate: Keyword args for validation_decorator.
        error_handler: Decorator factory that accepts operation_name.
        validation_decorator: Decorator factory that accepts validation kwargs.

    Returns:
        Callable: A decorator that applies the composed wrappers.
    """

    def decorator(func: Callable) -> Callable:
        result = func

        if error_handler is not None:
            result = error_handler(operation_name)(result)

        if validation_decorator is not None and validate is not None:
            result = validation_decorator(**validate)(result)

        result = log_tool_call(result)
        return result

    return decorator
