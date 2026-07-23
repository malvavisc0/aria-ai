"""Shell execution tool functions.

This module provides functions for executing shell commands with
proper timeout handling, output capture, and basic security constraints.

"""

from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from aria.tools import get_function_name, tool_response
from aria.tools.constants import DEFAULT_TIMEOUT, MAX_TIMEOUT
from aria.tools.decorators import log_tool_call
from aria.tools.shell.execution import _execute_command_internal
from aria.tools.shell.validation import (
    _validate_command,
    _validate_working_dir,
)


class ShellToolSchema(BaseModel):
    """Simplified schema exposed to the LLM for the shell tool.

    The actual ``shell`` function accepts Union types for batch execution,
    but the LLM only needs to see a plain string for ``commands``.
    This avoids confusing ``anyOf`` schemas that cause the LLM to
    retry with incorrect argument formats.
    """

    reason: str = Field(
        description="Required. Brief explanation of why you are executing this command"
    )
    commands: str = Field(description="The shell command string to execute")
    stop_on_error: bool = Field(default=True, description="Stop on first failure")
    timeout: int | None = Field(
        default=None,
        description="Timeout in seconds (default: 30, max: configurable via ARIA_MAX_TIMEOUT)",
    )
    working_dir: str | None = Field(default=None, description="Working directory path")
    env: dict[str, str] | None = Field(
        default=None,
        description="Additional environment variables to set for execution",
    )


def _run_shell_command(
    reason: str,
    command: str,
    timeout: int | None = None,
    working_dir: str | None = None,
    env: dict[str, str] | None = None,
) -> dict:
    """Execute a command string via the system shell.

    Args:
        reason: Why you're executing.
        command: Full command string (supports pipes, redirects, etc.).
        timeout: Timeout in seconds (default: 30, max: configurable).
        working_dir: Working directory (default: BASE_DIR).
        env: Additional environment variables (merged with current env).

    Returns:
        Dict with data payload (stdout, stderr, return_code, etc.).
    """
    logger.info(f"Executing shell command: {command}")
    _validate_command(command)

    actual_timeout = min(
        timeout if timeout is not None else DEFAULT_TIMEOUT,
        MAX_TIMEOUT,
    )
    resolved_working_dir = _validate_working_dir(working_dir)

    # Ensure ~/.aria/bin and the current Python env bin are on PATH
    from aria.config.folders import get_augmented_env

    proc_env = get_augmented_env()
    if env:
        proc_env.update(env)

    return _execute_command_internal(
        "shell",
        command,
        command,
        resolved_working_dir,
        actual_timeout,
        shell=True,
        env=proc_env,
    )


def _parse_json_array(commands: str) -> list[Any] | None:
    """Try to parse a string as a JSON array; return None if not an array."""
    import json as json_mod

    stripped = commands.strip()
    if not (stripped.startswith("[") and stripped.endswith("]")):
        return None
    try:
        parsed = json_mod.loads(stripped)
    except (json_mod.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, list) else None


def _normalize_list(items: list[Any]) -> list[dict[str, Any]]:
    result = []
    for item in items:
        if isinstance(item, str):
            result.append({"command": item})
        elif isinstance(item, dict):
            result.append(item)
    return result


def _normalize_commands(
    commands: str | dict[str, Any] | list[Any],
) -> list[dict[str, Any]]:
    """Normalize various command input formats into a uniform list.

    Supported formats:
        - ``"git status"`` — single string
        - ``["git status", "git push"]`` — list of strings
        - ``'["git status", "git push"]'`` — JSON array string
        - ``{"command": "git status"}`` — single dict with command key
        - ``[{"command": "git status"}, {"command": "git push"}]`` — list of dicts

    Args:
        commands: Input in any supported format.

    Returns:
        List of dicts, each with at least a ``command`` key.
    """
    if isinstance(commands, str):
        parsed = _parse_json_array(commands)
        if parsed is not None:
            return _normalize_commands(parsed)
        return [{"command": commands}]
    if isinstance(commands, dict):
        return [commands]
    if isinstance(commands, list):
        return _normalize_list(commands)
    return []


def _resolve_cmd_kwargs(
    cmd_dict: dict[str, Any],
    *,
    timeout: int | None,
    working_dir: str | None,
    env: dict[str, str] | None,
) -> tuple[str, int | None, str | None, dict[str, str] | None]:
    return (
        cmd_dict.get("command", ""),
        cmd_dict.get("timeout", timeout),
        cmd_dict.get("working_dir", working_dir),
        cmd_dict.get("env", env),
    )


def _single_command_response(
    reason: str, cmd_dict: dict[str, Any], *, timeout, working_dir, env
) -> str:
    cmd_str, cmd_timeout, cmd_working_dir, cmd_env = _resolve_cmd_kwargs(
        cmd_dict, timeout=timeout, working_dir=working_dir, env=env
    )
    tool_name = get_function_name(depth=2)
    try:
        result = _run_shell_command(
            reason=reason,
            command=cmd_str,
            timeout=cmd_timeout,
            working_dir=cmd_working_dir,
            env=cmd_env,
        )
        return tool_response(
            tool=tool_name,
            reason=reason,
            data=result["data"],
        )
    except Exception as e:
        return tool_response(
            tool=tool_name,
            reason=reason,
            data={
                "command": cmd_str.strip(),
                "error": str(e),
                "return_code": 1,
            },
        )


def _run_batch_commands(
    normalized: list[dict[str, Any]],
    *,
    reason: str,
    stop_on_error: bool,
    timeout: int | None,
    working_dir: str | None,
    env: dict[str, str] | None,
) -> tuple[list[dict[str, Any]], float, bool]:
    results: list[dict[str, Any]] = []
    total_execution_time = 0.0
    stopped_early = False

    for i, cmd_dict in enumerate(normalized):
        cmd_str, cmd_timeout, cmd_working_dir, cmd_env = _resolve_cmd_kwargs(
            cmd_dict, timeout=timeout, working_dir=working_dir, env=env
        )
        continue_on_error = cmd_dict.get("continue_on_error", False)
        try:
            result = _run_shell_command(
                reason=f"Command {i + 1}/{len(normalized)}",
                command=cmd_str,
                timeout=cmd_timeout,
                working_dir=cmd_working_dir,
                env=cmd_env,
            )
            cmd_data = result["data"]
            results.append(cmd_data)
            total_execution_time += cmd_data.get("execution_time", 0)
            if cmd_data.get("return_code", -1) != 0 and _should_stop(
                continue_on_error, stop_on_error
            ):
                stopped_early = True
                break
        except Exception as e:
            results.append(
                {
                    "command": cmd_str.strip(),
                    "error": str(e),
                    "return_code": 1,
                }
            )
            if _should_stop(continue_on_error, stop_on_error):
                stopped_early = True
                break

    return results, total_execution_time, stopped_early


def _should_stop(continue_on_error: bool, stop_on_error: bool) -> bool:
    return not continue_on_error and stop_on_error


@log_tool_call
def shell(
    reason: str,
    commands: str | list[str] | dict[str, Any] | list[dict[str, Any]],
    stop_on_error: bool = True,
    timeout: int | None = None,
    working_dir: str | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Execute shell commands with timeout and security constraints.

    When to use:
        - Run shell commands.
        - Batch multiple commands with per-command timeout and error handling.

    Args:
        reason: Required. Brief explanation of why you are executing this command.
        commands: str | list[str] | dict | list[dict].
            Dict keys: command, timeout, working_dir, env, continue_on_error.
        stop_on_error: Stop on first failure (default: True).
        timeout: Default timeout seconds (default: 30, max: configurable).
        working_dir: Default working directory.
        env: Additional environment variables for all commands.

    Returns:
        JSON with command output. Single commands return flat response;
        batch commands return results array.
    """
    normalized = _normalize_commands(commands)

    if not normalized:
        return tool_response(
            tool=get_function_name(),
            reason=reason,
            data={"error": "No commands provided"},
        )

    if len(normalized) == 1:
        return _single_command_response(
            reason,
            normalized[0],
            timeout=timeout,
            working_dir=working_dir,
            env=env,
        )

    results, total_execution_time, stopped_early = _run_batch_commands(
        normalized,
        reason=reason,
        stop_on_error=stop_on_error,
        timeout=timeout,
        working_dir=working_dir,
        env=env,
    )

    data: dict[str, Any] = {
        "results": results,
        "execution_time": round(total_execution_time, 3),
    }
    if stopped_early:
        data["stopped_early"] = True

    return tool_response(
        tool=get_function_name(),
        reason=reason,
        data=data,
    )
