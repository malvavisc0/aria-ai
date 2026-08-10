"""Shell execution exceptions.

This module provides custom exception classes for shell execution errors.
"""

from aria.tools.errors import ToolError


class ShellExecutionError(ToolError):
    """Base exception for shell execution errors."""

    code = "SHELL_ERROR"
    recoverable = True
    how_to_fix = "Check the command and try again."


class CommandBlockedError(ShellExecutionError):
    """Raised when a command is blocked or not in the safe list."""

    code = "COMMAND_BLOCKED"
    recoverable = False
    how_to_fix = "This command is not allowed. Use a different command."


class WorkingDirectoryError(ShellExecutionError):
    """Raised when the working directory is invalid or not allowed."""

    code = "INVALID_WORKING_DIR"
    recoverable = True
    how_to_fix = "Verify the directory exists and is accessible."
