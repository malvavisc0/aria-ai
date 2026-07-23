"""
Internal helper functions for file operations.

This module contains private helper functions used by the main file operations
module. These functions should not be imported directly by external modules.
"""

import shutil
from pathlib import Path

from loguru import logger

from aria.tools import safe_json, utc_timestamp
from aria.tools.constants import BASE_DIR, MAX_FILE_SIZE
from aria.tools.files.constants import (
    BLOCKED_EXTENSIONS,
    BLOCKED_PATTERNS,
    MAX_CHUNK_SIZE,
    MAX_LINE_LENGTH,
)
from aria.tools.files.exceptions import FileOperationError, FileSecurityError


def _error_response(
    operation: str,
    file_name: str,
    exc: Exception,
    reason: str = "",
) -> str:
    """Generate secure error response without information disclosure.

    Args:
        operation: The operation that failed
        file_name: The file name involved in the operation
        exc: The exception that occurred
        reason: The agent's stated reason for calling this tool

    Returns:
        str: JSON formatted error response
    """
    # Extract error metadata from exception
    error_code = getattr(exc, "code", type(exc).__name__.upper())
    recoverable = getattr(exc, "recoverable", False)
    how_to_fix = getattr(exc, "how_to_fix", None)

    if isinstance(exc, FileSecurityError):
        error_msg = f"Security validation failed: {str(exc)}"
        logger.warning(f"Security validation failed for {file_name}: {exc}")
    elif isinstance(exc, FileOperationError):
        error_msg = f"File operation failed: {str(exc)}"
        logger.error(f"File operation failed for {file_name}: {exc}")
    elif isinstance(exc, (OSError, PermissionError)):
        error_msg = "File access denied or not found"
        logger.warning(f"File access denied for {file_name}")
    else:
        error_msg = f"Unexpected error: {str(exc)}"
        logger.error(f"Unexpected error for {file_name}: {exc}")

    # Build error block with standard fields
    error_block = {
        "code": error_code,
        "message": error_msg,
        "type": type(exc).__name__,
        "recoverable": recoverable,
    }
    if how_to_fix:
        error_block["how_to_fix"] = how_to_fix

    response = {
        "status": "error",
        "tool": operation,
        "reason": reason,
        "timestamp": utc_timestamp(),
        "error": error_block,
    }

    return safe_json(response)


def _validate_filename(file_name: str) -> None:
    if not file_name or not isinstance(file_name, str):
        raise FileSecurityError("Invalid file name provided")
    if ".." in file_name:
        raise FileSecurityError("Path traversal attempt detected in file name")
    if any(pattern in file_name for pattern in BLOCKED_PATTERNS):
        raise FileSecurityError("File name contains blocked patterns")


def _validate_numeric_params(chunk_size: int, offset: int, length: int) -> None:
    if chunk_size > MAX_CHUNK_SIZE:
        raise FileSecurityError(f"chunk_size must be between 1 and {MAX_CHUNK_SIZE}")
    if offset < 0 or length < 0:
        raise FileSecurityError("Negative offset or length not allowed")


def _validate_content(contents: str | None) -> None:
    if not contents:
        return
    if len(contents) > MAX_FILE_SIZE:
        raise FileSecurityError(
            f"Content size {len(contents)} exceeds limit: {MAX_FILE_SIZE}"
        )


def _validate_line_lengths(new_lines: list[str] | None) -> None:
    if not new_lines:
        return
    for line in new_lines:
        line_length = len(line)
        if line_length > MAX_LINE_LENGTH:
            raise FileSecurityError(
                f"Line length {line_length} exceeds limit: {MAX_LINE_LENGTH}"
            )


def _validate_inputs(
    file_name: str,
    chunk_size: int = 0,
    offset: int = 0,
    length: int = 0,
    contents: str | None = None,
    new_lines: list[str] | None = None,
) -> None:
    """Comprehensive input validation for file operations.

    Validates file name, size limits, and content parameters to prevent
    security vulnerabilities and resource exhaustion.

    Args:
        file_name: Name of the file to validate
        chunk_size: Size of chunks for operations (default: 0)
        offset: Offset for file operations (default: 0)
        length: Length of operations (default: 0)
        contents: File content to validate (default: None)
        new_lines: List of new lines to validate (default: None)

    Raises:
        FileSecurityError: If validation fails due to security violations
    """
    _validate_filename(file_name)
    _validate_numeric_params(chunk_size, offset, length)
    _validate_content(contents)
    _validate_line_lengths(new_lines)


def _enforce_base_dir(file_path: Path, base_dir_resolved: Path, enforce: bool) -> None:
    if enforce and not str(file_path).startswith(str(base_dir_resolved)):
        raise FileSecurityError("Path traversal attempt detected")


def _check_blocked_extension(file_path: Path) -> None:
    suffix = file_path.suffix.lower()
    if file_path.suffix and suffix in BLOCKED_EXTENSIONS:
        raise FileSecurityError(f"File type not allowed: {file_path.suffix}")


def _secure_resolve_path(
    file_name: str, check_exists: bool = True, enforce_base_dir: bool = False
) -> Path:
    """Secure path resolution with validation.

    Resolves file path while validating file type restrictions.
    By default, paths can be anywhere on the filesystem.

    Args:
        file_name: Absolute path (e.g., /home/user/data/downloads/file.txt)
        check_exists: Whether to check if file exists (default: True)
        enforce_base_dir: If True, restrict paths to BASE_DIR (default: False)

    Returns:
        Path: Resolved absolute path to the file

    Raises:
        FileSecurityError: If path resolution fails due to security violations
        FileOperationError: If path is a directory or not absolute
    """
    try:
        base_dir_resolved = BASE_DIR.resolve()
        file_path = Path(file_name)
        if not file_path.is_absolute():
            raise FileOperationError(f"Path must be absolute: {file_name}")
        if file_path.is_symlink():
            raise FileSecurityError("Symlinks not allowed")
        file_path = file_path.resolve()
        _enforce_base_dir(file_path, base_dir_resolved, enforce_base_dir)
        if file_path.is_dir():
            raise FileOperationError(f"Path is a directory, not a file: {file_name}")
        _check_blocked_extension(file_path)
        if check_exists and not file_path.exists():
            raise FileOperationError(f"File not found: {file_name}")
        return file_path
    except (FileSecurityError, FileOperationError):
        raise
    except Exception as exc:
        raise FileSecurityError(f"Path resolution failed: {exc}") from exc


def _secure_resolve_dir(
    dir_name: str, enforce_base_dir: bool = False, check_exists: bool = True
) -> Path:
    """Secure directory path resolution.

    Directory can be anywhere on the filesystem by default.

    Args:
        dir_name: Name of the directory to resolve
        enforce_base_dir: If True, restrict paths to BASE_DIR (default: False)
        check_exists: Whether to check if directory exists (default: True)

    Returns:
        Path: Resolved absolute path to the directory

    Raises:
        FileSecurityError: If path resolution fails
    """
    try:
        # Resolve BASE_DIR to handle symlinks (macOS /var -> /private/var)
        base_dir_resolved = BASE_DIR.resolve()

        # Only accept absolute paths
        dir_path = Path(dir_name)
        if not dir_path.is_absolute():
            raise FileOperationError(f"Path must be absolute: {dir_name}")

        # Check for symlinks BEFORE resolving
        if dir_path.is_symlink():
            raise FileSecurityError("Symlinks not allowed")

        # Resolve the path
        dir_path = dir_path.resolve()

        # Check for path traversal attacks - path must be within BASE_DIR
        if enforce_base_dir and not str(dir_path).startswith(str(base_dir_resolved)):
            raise FileSecurityError("Path traversal attempt detected")

        # Check it's actually a directory if required
        if check_exists and not dir_path.is_dir():
            raise FileOperationError(f"Path is not a directory: {dir_name}")

        return dir_path
    except (FileSecurityError, FileOperationError):
        raise
    except Exception as exc:
        raise FileSecurityError(f"Path resolution failed: {exc}") from exc


def _create_backup(file_path: Path) -> Path | None:
    """Create backup of file before destructive operation.

    Args:
        file_path: Path to the file to backup

    Returns:
        Path to backup file, or None if backup failed
    """
    if not file_path.exists():
        return None

    backup_path = file_path.with_suffix(file_path.suffix + ".backup")
    try:
        shutil.copy2(file_path, backup_path)
        logger.info(f"Created backup: {backup_path}")
        return backup_path
    except Exception as exc:
        logger.warning(f"Failed to create backup for {file_path}: {exc}")
        return None


def validate_and_resolve_file(file_name: str, check_exists: bool = True) -> Path:
    """Validate inputs and resolve file path in one step.

    Args:
        file_name: File name to validate and resolve
        check_exists: Whether to verify file exists

    Returns:
        Resolved Path object

    Raises:
        FileSecurityError: If validation fails
        FileOperationError: If file doesn't exist (when check_exists=True)
    """
    _validate_inputs(file_name)
    return _secure_resolve_path(file_name, check_exists=check_exists)


def validate_and_resolve_two_files(
    source: str, dest: str, dest_must_exist: bool = False
) -> tuple[Path, Path]:
    """Validate and resolve two file paths (for copy, rename operations).

    Args:
        source: Source file name
        dest: Destination file name
        dest_must_exist: Whether destination must exist

    Returns:
        Tuple of (source_path, dest_path)

    Raises:
        FileSecurityError: If validation fails
        FileOperationError: If files don't exist as required
    """
    _validate_inputs(source)
    _validate_inputs(dest)
    source_path = _secure_resolve_path(source)
    dest_path = _secure_resolve_path(dest, check_exists=dest_must_exist)
    return source_path, dest_path
