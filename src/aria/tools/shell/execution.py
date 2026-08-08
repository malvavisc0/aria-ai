"""Command execution internals for shell execution tools.

This module provides internal helpers for command execution and
response building.
"""

import hashlib
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from aria.tools.constants import BASE_DIR
from aria.tools.shell.validation import _extract_command_name

# Strip ANSI escape sequences (colors, cursor movement, etc.)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\].*?\x07")

_OUTPUT_DIR = BASE_DIR / "shell_output"

# Max chars for head/tail preview embedded in the JSON response.
_HEAD_TAIL_PREVIEW = 500


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return _ANSI_RE.sub("", text) if text else ""


def _write_output_file(text: str, suffix: str) -> str:
    """Write text to a timestamped file and return the path string.

    Args:
        text: Content to persist.
        suffix: Filename suffix for the file (e.g. 'stdout').

    Returns:
        Absolute path to the written file.
    """
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _OUTPUT_DIR / f"{ts}_{suffix}_{digest}.txt"
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def _head_tail_preview(text: str) -> str:
    """Return a short head + tail preview of *text* for the JSON envelope.

    Args:
        text: Full text to preview.

    Returns:
        Short head/tail preview string.
    """
    if not text:
        return ""
    head = text[:_HEAD_TAIL_PREVIEW]
    tail_start = max(0, len(text) - _HEAD_TAIL_PREVIEW)
    tail = text[tail_start:]
    preview = head
    if len(text) > _HEAD_TAIL_PREVIEW * 2:
        preview = f"{head}...[{len(text) - _HEAD_TAIL_PREVIEW * 2} chars omitted]{tail}"
    return preview


def _build_response(
    operation: str,
    command: str,
    working_dir: str,
    *,
    stdout: str = "",
    stderr: str = "",
    return_code: int = -1,
    execution_time: float = 0.0,
    timed_out: bool = False,
) -> dict[str, Any]:
    """Build a lean command execution response dict.

    Outputs are persisted to files; the response contains file paths
    plus small head/tail previews so the agent can read more if needed.

    Args:
        operation: The operation name (unused, kept for API compat).
        command: The command that was executed.
        working_dir: The resolved working directory path.
        stdout: Captured standard output.
        stderr: Captured standard error.
        return_code: Process exit code.
        execution_time: Duration in seconds.
        timed_out: Whether the command timed out.

    Returns:
        Response dictionary with minimal data payload.
    """
    clean_stdout = _strip_ansi(stdout)
    clean_stderr = _strip_ansi(stderr)

    data: dict[str, Any] = {
        "command": command,
        "return_code": return_code,
        "execution_time": round(execution_time, 3),
    }

    # Persist to files so the agent can read in chunks
    if clean_stdout:
        data["stdout_file"] = _write_output_file(clean_stdout, "stdout")
        data["stdout_head_tail"] = _head_tail_preview(clean_stdout)
    if clean_stderr:
        data["stderr_file"] = _write_output_file(clean_stderr, "stderr")
        data["stderr_head_tail"] = _head_tail_preview(clean_stderr)
    if timed_out:
        data["timed_out"] = True

    return {"data": data}


def _execute_command_internal(
    operation: str,
    display_command: str,
    run_target: str | list[str],
    working_dir: Path,
    timeout: int,
    *,
    shell: bool,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute a command and return a standardized response dict.

    Args:
        operation: The operation name (e.g. ``execute_command``).
        display_command: Human-readable command for response payload.
        run_target: Command passed to ``subprocess.run``.
            When ``shell=True`` this should be a string.
            When ``shell=False`` this should be a list of strings.
        working_dir: Resolved working directory.
        timeout: Timeout in seconds.
        shell: Whether to execute via the system shell.
        env: Optional environment variables passed to subprocess.

    Returns:
        Standardized response dictionary from :func:`_build_response`.
    """
    start_time = time.time()
    working_dir_str = str(working_dir)

    try:
        result = subprocess.run(
            run_target,
            shell=shell,
            cwd=working_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start_time

        logger.info("Command executed with return code {}", result.returncode)
        if result.stdout:
            logger.info("stdout: {}", result.stdout[:2000])
        if result.stderr:
            logger.debug("stderr: {}", result.stderr[:2000])
        return _build_response(
            operation,
            display_command,
            working_dir_str,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
            execution_time=elapsed,
        )

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        logger.warning(f"Command timed out after {timeout}s")
        return _build_response(
            operation,
            display_command,
            working_dir_str,
            execution_time=elapsed,
            timed_out=True,
        )

    except FileNotFoundError:
        cmd_name = _extract_command_name(display_command)
        logger.error(f"Command not found: {cmd_name}")
        return _build_response(
            operation,
            display_command,
            working_dir_str,
            stderr=f"Command not found: {cmd_name}",
            return_code=127,
        )

    except PermissionError:
        logger.error(f"Permission denied executing command: {display_command}")
        return _build_response(
            operation,
            display_command,
            working_dir_str,
            stderr="Permission denied",
            return_code=1,
        )

    except Exception as exc:
        logger.error(f"Unexpected error executing command: {exc}")
        return _build_response(
            operation,
            display_command,
            working_dir_str,
            stderr=str(exc),
            return_code=1,
        )
