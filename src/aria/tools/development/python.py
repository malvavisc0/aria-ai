"""Python execution and syntax-check tools."""

import ast
import os
import traceback
from pathlib import Path
from typing import Any

from loguru import logger

from aria.tools import Reason
from aria.tools.constants import DEFAULT_TIMEOUT, MAX_TIMEOUT
from aria.tools.decorators import tool_function
from aria.tools.development._internals import (
    _build_response,
    _capture_execution_output,
    _create_safe_globals,
    _read_file_safely,
    _validate_timeout,
)
from aria.tools.development.decorators import (
    with_input_validation,
    with_runner_error_handling,
)
from aria.tools.development.exceptions import PythonSecurityError


def _has_content(file_path: str) -> bool:
    """Return True if *file_path* exists and has non-zero size."""
    return bool(file_path) and Path(file_path).stat().st_size > 0


def _setup_file_context(
    safe_globals: dict[str, Any], is_file: bool, filename: str
) -> None:
    """Populate ``__file__`` and ``__dir__`` when executing a file."""
    if not is_file:
        return
    safe_globals["__file__"] = os.path.abspath(filename)
    safe_globals["__dir__"] = os.path.dirname(os.path.abspath(filename))
    logger.debug(f"Set __file__ to: {safe_globals['__file__']}")


@tool_function(
    "python",
    validate={},
    error_handler=with_runner_error_handling,
    validation_decorator=with_input_validation,
)
def python(
    reason: Reason,
    code: str | None = None,
    file: str | None = None,
    args: list[str] | None = None,
    timeout: int | None = DEFAULT_TIMEOUT,
    check_only: bool = False,
) -> str:
    """Execute or validate Python code with sandboxed output capture.

    When to use:
        - Run Python code snippets, scripts, or test files.
        - Use check_only=True to validate syntax without executing.
        - Do NOT use for shell commands (git, pip, npm) — use `shell`.

    Args:
        reason: Required. Brief explanation of why you are running this code.
        code: Python code string to execute or validate.
        file: Path to a Python file to execute or validate.
        args: CLI arguments for sys.argv (execution only).
        timeout: Max seconds (default: 30, max: 300).
        check_only: If True, validate syntax without executing.

    Returns:
        JSON with result data (stdout_file, stderr_file, traceback, etc.).
    """
    if code is None and file is None:
        raise PythonSecurityError("Provide exactly one of 'code' or 'file'.")
    if code is not None and file is not None:
        raise PythonSecurityError("Provide exactly one of 'code' or 'file', not both.")

    if check_only:
        return _python_check(reason, code, file)
    else:
        return _python_execute(reason, code, file, args, timeout)


def _python_check(
    reason: str,
    code: str | None,
    file: str | None,
) -> str:
    """Validate Python syntax without executing."""
    if code is not None:
        filename: str = "<block>"
        source: str = code
    else:
        filename = file  # type: ignore[assignment]
        source = _read_file_safely(file)  # type: ignore[arg-type]

    logger.info(f"Checking Python syntax for: {filename}")

    try:
        ast.parse(source, filename=filename)
        logger.info(f"Syntax validation passed for: {filename}")
        return _build_response(
            operation="python",
            result={"valid": True, "message": "Syntax is valid"},
            filename=filename,
            source="code" if code is not None else "file",
        )

    except SyntaxError as e:
        logger.error(f"Syntax error in {filename} at line {e.lineno or 0}: {e.msg}")
        return _build_response(
            operation="python",
            result={
                "valid": False,
                "error_type": "SyntaxError",
                "message": e.msg or "Syntax error",
                "line_number": e.lineno,
                "column": e.offset,
                "text": e.text.rstrip() if e.text else None,
            },
            filename=filename,
            source="code" if code is not None else "file",
        )


def _error_response(
    filename: str,
    timeout: int,
    source: str,
    exc: Exception,
    error_type: str | None = None,
    security_note: str | None = None,
    include_tb: bool = True,
) -> str:
    """Build an error response for Python execution.

    Args:
        filename: Source file or block name.
        timeout: Execution timeout in seconds.
        source: 'code' or 'file'.
        exc: The exception that occurred.
        error_type: Override for exception type name.
        security_note: Optional security-related note.
        include_tb: Whether to include traceback.

    Returns:
        JSON response string.
    """
    result: dict[str, Any] = {
        "success": False,
        "error_type": error_type or type(exc).__name__,
        "message": str(exc),
    }
    if include_tb:
        result["traceback"] = traceback.format_exc()
    if security_note:
        result["security_note"] = security_note

    return _build_response(
        operation="python",
        result=result,
        filename=filename,
        timeout=timeout,
        source=source,
    )


# Exception type -> (error_type label, optional security note).
_EXECUTION_ERRORS: dict[type[Exception], tuple[str, str | None]] = {
    TimeoutError: ("TimeoutError", None),
    NameError: ("NameError", "This may be due to restricted builtins"),
    ImportError: ("ImportError", "Imports are restricted for security"),
}


def _dispatch_execution_error(
    exc: Exception, filename: str, timeout: int, source: str
) -> str:
    """Build the error response for a failed Python execution."""
    error_type, security_note = type(exc).__name__, None
    for exc_type, (label, note) in _EXECUTION_ERRORS.items():
        if isinstance(exc, exc_type):
            error_type, security_note = label, note
            break
    logger.error(f"{error_type} in {filename}: {exc}")
    return _error_response(
        filename,
        timeout,
        source,
        exc,
        error_type=error_type,
        security_note=security_note,
    )


def _system_exit_response(
    exc: SystemExit,
    filename: str,
    timeout: int,
    source: str,
    stdout_file: str = "",
    stderr_file: str = "",
) -> str:
    """Build the response for a script that called ``sys.exit()``."""
    exit_code = exc.code if exc.code is not None else 0
    logger.info(f"Script exited with code {exit_code} in {filename}")
    message = (
        "Script completed successfully"
        if exit_code == 0
        else f"Script exited with code {exit_code}"
    )
    result: dict[str, Any] = {
        "success": exit_code == 0,
        "exit_code": exit_code,
        "message": message,
    }
    if _has_content(stdout_file):
        result["stdout_file"] = stdout_file
    if _has_content(stderr_file):
        result["stderr_file"] = stderr_file
    return _build_response(
        operation="python",
        result=result,
        filename=filename,
        timeout=timeout,
        source=source,
    )


def _python_execute(
    reason: str,
    code: str | None,
    file: str | None,
    args: list[str] | None,
    timeout: int | None,
) -> str:
    """Execute Python code or file."""
    is_file = file is not None
    source_kind = "file" if is_file else "code"

    if is_file:
        filename = file
        source = _read_file_safely(file)
    else:
        filename = "<block>"
        source = code

    logger.info(f"Executing Python {source_kind}: {filename} (timeout={timeout}s)")

    if not timeout:
        raise ValueError(
            f"Invalid timeout: {timeout} (must be 1-{MAX_TIMEOUT} seconds)"
        )
    _validate_timeout(timeout)

    if is_file:
        filename = os.path.abspath(file) if os.path.exists(file) else file

    safe_globals = _create_safe_globals()
    _setup_file_context(safe_globals, is_file, filename)

    try:
        stdout_file, stderr_file = _capture_execution_output(
            source,  # type: ignore[arg-type]
            safe_globals,
            timeout,
            filename,  # type: ignore[arg-type]
            args,
        )

        result: dict[str, Any] = {
            "success": True,
            "exit_code": 0,
        }
        if _has_content(stdout_file):
            result["stdout_file"] = stdout_file
        if _has_content(stderr_file):
            result["stderr_file"] = stderr_file

        logger.info(f"{source_kind.capitalize()} executed successfully: {filename}")

        return _build_response(
            operation="python",
            result=result,
            filename=filename,
            timeout=timeout,
            source=source_kind,
        )

    except SystemExit as e:
        return _system_exit_response(
            e,
            filename,
            timeout,
            source_kind,
            stdout_file=getattr(e, "stdout_file", ""),
            stderr_file=getattr(e, "stderr_file", ""),
        )

    except Exception as e:
        return _dispatch_execution_error(e, filename, timeout, source_kind)
