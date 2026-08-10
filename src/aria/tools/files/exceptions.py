"""
Custom exceptions for file operations.

This module defines specific exceptions used throughout the file operations
system to provide clear error information and proper exception handling.
"""

from aria.tools.errors import ToolError


class FileSecurityError(ToolError):
    """Raised when file operation violates security constraints."""

    code = "SECURITY_VIOLATION"
    recoverable = False
    how_to_fix = "Avoid using symlinks or restricted file types."


class FileOperationError(ToolError):
    """Raised when file operation fails."""

    code = "OPERATION_FAILED"
    recoverable = True
    how_to_fix = "Check file permissions and try again."
