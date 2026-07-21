"""
Internal helper functions for Python code execution.

This module contains private helper functions used by the main Python runner
module. These functions should not be imported directly by external modules.
"""

import io
import signal
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from typing import Any

from loguru import logger

from aria.tools import get_function_name, tool_error_response, utc_timestamp
from aria.tools.constants import MAX_TIMEOUT
from aria.tools.development.constants import RESTRICTED_BUILTINS
from aria.tools.development.exceptions import PythonSecurityError


def _build_response(
    operation: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    **metadata_fields,
) -> str:
    """Build standardized response structure as JSON string.

    Args:
        operation: Name of the operation
        result: Operation result data (None if error)
        error: Error message if operation failed
        **metadata_fields: Additional metadata fields

    Returns:
        str: JSON formatted response string
    """
    from aria.tools import tool_response

    metadata: dict[str, Any] = {"timestamp": utc_timestamp()}
    if error:
        metadata["error"] = error
    metadata.update(metadata_fields)

    if error:
        return tool_response(
            tool=operation,
            reason="",
            data={"error": error},
            **metadata,
        )

    return tool_response(
        tool=operation,
        reason="",
        data={"result": result, "tool": operation},
        **metadata,
    )


def _error_response(
    operation: str,
    identifier: str,
    exc: Exception,
    reason: str = "",
) -> str:
    """Generate error response for Python runner operations.

    Args:
        operation: The operation that failed (unused, kept for API compatibility)
        identifier: Code snippet or filename involved in the operation
        exc: The exception that occurred
        reason: The agent's stated reason for calling this tool

    Returns:
        str: JSON formatted error response string
    """
    return tool_error_response(
        tool=get_function_name(depth=2),
        reason=reason,
        exc=exc,
        identifier=identifier,
    )


def _validate_inputs(
    code: str | None = None,
    timeout: int | None = None,
    filename: str | None = None,
    file_path: str | None = None,
) -> None:
    """Comprehensive input validation for Python runner operations.

    Validates code, timeout, and filename parameters to prevent
    security vulnerabilities and invalid operations.

    Args:
        code: Python code to validate (default: None)
        timeout: Timeout value to validate (default: None)
        filename: Filename for error reporting (default: None)
        file_path: File path to validate (default: None)

    Raises:
        PythonSecurityError: If validation fails due to security violations
        ValueError: If validation fails due to invalid values
    """
    # Validate code if provided
    if code is not None:
        if not isinstance(code, str):
            raise PythonSecurityError("Code must be a string")

        # Allow empty code (it's valid Python)
        # Check for extremely large code (potential DoS)
        if len(code) > 10_000_000:  # 10MB limit
            raise PythonSecurityError("Code size exceeds maximum limit (10MB)")

    # Validate timeout if provided
    if timeout is not None:
        if not isinstance(timeout, int):
            raise ValueError("Timeout must be an integer")

        if timeout <= 0:
            raise ValueError("Timeout must be positive")

        if timeout > MAX_TIMEOUT:
            raise ValueError(
                f"Timeout {timeout} exceeds maximum limit of {MAX_TIMEOUT} seconds"
            )

    # Validate filename if provided
    if filename is not None:
        if not isinstance(filename, str):
            raise PythonSecurityError("Filename must be a string")

        # Check for path traversal attempts
        if ".." in filename:
            raise PythonSecurityError("Path traversal attempt detected in filename")

    # Validate file_path if provided
    if file_path is not None:
        if not isinstance(file_path, str):
            raise PythonSecurityError("File path must be a string")

        if len(file_path) == 0:
            raise PythonSecurityError("File path cannot be empty")

        # Check for path traversal attempts
        if ".." in file_path:
            raise PythonSecurityError("Path traversal attempt detected in file path")


def _create_safe_globals() -> dict[str, Any]:
    """Create restricted global namespace for safe execution.

    Returns:
        Dict: Safe globals with restricted builtins

    Note:
        Removes dangerous builtins like open, __import__, eval, exec, etc.
    """
    # Get standard builtins
    if isinstance(__builtins__, dict):
        builtins_dict = __builtins__
    else:
        builtins_dict = __builtins__.__dict__

    # Filter out dangerous builtins
    safe_builtins = {
        name: builtin
        for name, builtin in builtins_dict.items()
        if name not in RESTRICTED_BUILTINS
    }

    # DIAGNOSTIC: Log what builtins are available
    logger.debug(f"Safe globals created with {len(safe_builtins)} builtins")
    logger.debug(f"Restricted builtins removed: {RESTRICTED_BUILTINS}")

    # Check if __import__ is available
    if "__import__" in safe_builtins:
        logger.debug("__import__ is available in safe globals")
    else:
        logger.warning("__import__ is NOT available - imports may fail!")

    return {"__builtins__": safe_builtins, "__name__": "__main__"}


@contextmanager
def _time_limit(seconds: int):
    """Context manager to enforce execution timeout.

    Args:
        seconds: Maximum execution time in seconds

    Raises:
        TimeoutError: If execution exceeds time limit

    Note:
        Uses threading-based timeout for compatibility with
        multi-threaded environments. Signal-based timeout only
        works in the main thread.
    """
    import threading

    # Check if we're in the main thread
    is_main_thread = threading.current_thread() is threading.main_thread()

    if is_main_thread:
        # Use signal-based timeout in main thread
        def signal_handler(signum, frame):
            raise TimeoutError(f"Execution exceeded {seconds} second(s)")

        old_handler = signal.signal(signal.SIGALRM, signal_handler)
        signal.alarm(seconds)

        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
    else:
        # Use threading-based timeout in worker threads
        logger.debug("Using thread-based timeout (not in main thread)")

        # Create a flag to track if execution completed
        execution_complete = threading.Event()
        timeout_occurred = [False]

        def timeout_handler():
            if not execution_complete.is_set():
                timeout_occurred[0] = True

        # Start timeout timer
        timer = threading.Timer(seconds, timeout_handler)
        timer.daemon = True
        timer.start()

        try:
            yield
            execution_complete.set()

            # Check if timeout occurred during execution
            if timeout_occurred[0]:
                raise TimeoutError(f"Execution exceeded {seconds} second(s)")
        finally:
            execution_complete.set()
            timer.cancel()


def _capture_execution_output(
    code: str,
    safe_globals: dict[str, Any],
    timeout: int,
    filename: str = "<string>",
    argv: list[str] | None = None,
) -> tuple[str, str]:
    """Execute code and capture stdout/stderr.

    Args:
        code: Python code to execute
        safe_globals: Safe global namespace
        timeout: Execution timeout in seconds
        filename: Filename for context (default: "<string>")
        argv: Custom sys.argv for the script (default: [filename])

    Returns:
        tuple: (stdout_text, stderr_text)

    Raises:
        TimeoutError: If execution exceeds timeout
        Exception: Any exception raised during execution

    Note:
        Uses the same dictionary for both global and local namespaces
        to ensure imports work correctly. This is required for Python's
        import statement to properly bind module names.
    """
    import sys

    # Save original sys.argv and set clean argv for execution
    # This prevents argparse from trying to parse parent process arguments
    original_argv = sys.argv.copy()

    # Set sys.argv to custom value or default to script name only
    # This allows argparse.parse_args() to work correctly
    if argv is None:
        sys.argv = [filename]
    else:
        sys.argv = argv.copy()

    logger.debug(f"Executing code: {filename}")
    logger.debug(f"Set sys.argv to: {sys.argv}")

    try:
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            with _time_limit(timeout):
                # FIX: Use same dict for global and local namespaces
                # This ensures imports bind correctly to the namespace
                exec(code, safe_globals, safe_globals)

        return stdout_capture.getvalue(), stderr_capture.getvalue()
    finally:
        # Always restore original sys.argv
        sys.argv = original_argv
        logger.debug(f"Restored sys.argv to: {sys.argv}")


def _execute_without_capture(
    code: str,
    safe_globals: dict[str, Any],
    timeout: int,
    filename: str = "<string>",
    argv: list[str] | None = None,
) -> None:
    """Execute code without capturing output.

    Args:
        code: Python code to execute
        safe_globals: Safe global namespace
        timeout: Execution timeout in seconds
        filename: Filename for context (default: "<string>")
        argv: Custom sys.argv for the script (default: [filename])

    Raises:
        TimeoutError: If execution exceutes timeout
        Exception: Any exception raised during execution

    Note:
        Uses the same dictionary for both global and local namespaces
        to ensure imports work correctly.
    """
    import sys

    # Save original sys.argv and set clean argv for execution
    original_argv = sys.argv.copy()

    # Set sys.argv to custom value or default to script name only
    if argv is None:
        sys.argv = [filename]
    else:
        sys.argv = argv.copy()

    try:
        with _time_limit(timeout):
            # FIX: Use same dict for global and local namespaces
            # This ensures imports bind correctly to the namespace
            exec(code, safe_globals, safe_globals)
    finally:
        # Always restore original sys.argv
        sys.argv = original_argv


def _validate_timeout(timeout: int) -> None:
    """Validate timeout parameter.

    Args:
        timeout: Timeout value to validate

    Raises:
        ValueError: If timeout is invalid
    """
    if timeout <= 0 or timeout > MAX_TIMEOUT:
        raise ValueError(
            f"Invalid timeout: {timeout} (must be 1-{MAX_TIMEOUT} seconds)"
        )


def _read_file_safely(file_path: str) -> str:
    """Read file with proper error handling.

    Args:
        file_path: Path to file to read

    Returns:
        str: File contents

    Raises:
        FileNotFoundError: If file doesn't exist
        PermissionError: If file can't be read
        OSError: For other file reading errors
    """
    import os

    # Try to resolve the file path
    # First try as-is, then try with BASE_DIR prefix
    resolved_path = None

    if os.path.exists(file_path):
        resolved_path = file_path
    else:
        # Try with BASE_DIR prefix
        try:
            from aria.tools.constants import BASE_DIR

            potential_path = BASE_DIR / file_path
            if potential_path.exists():
                resolved_path = str(potential_path)
                logger.debug(f"Resolved {file_path} to {resolved_path} using BASE_DIR")
        except Exception:
            pass

    if resolved_path is None:
        logger.error(f"File not found: {file_path}")
        raise FileNotFoundError(f"File not found: {file_path}")

    try:
        with open(resolved_path, encoding="utf-8") as f:
            return f.read()
    except PermissionError:
        logger.error(f"Permission denied reading file: {resolved_path}")
        raise
    except Exception as e:
        logger.error(f"Error reading file {resolved_path}: {e}")
        raise OSError(f"Error reading file: {str(e)}") from e
