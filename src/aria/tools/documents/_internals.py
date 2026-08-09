"""Internal helpers for the documents tool.

NOTE: we deliberately do NOT reuse ``_secure_resolve_path`` from
``aria.tools.files._internals`` — that helper blocks office/PDF
extensions (BLOCKED_EXTENSIONS) which are exactly what this tool
converts.
"""

from pathlib import Path

from aria.tools.files.exceptions import FileOperationError, FileSecurityError


def resolve_doc_path(file_name: str) -> Path:
    """Resolve an absolute path for a document to convert.

    Checks: absolute, not a symlink, not a directory, exists. No
    blocked-extension filter (this tool's purpose is binary docs).
    """
    p = Path(file_name)
    if not p.is_absolute():
        raise FileOperationError(f"Path must be absolute: {file_name}")
    if p.is_symlink():
        raise FileSecurityError("Symlinks not allowed")
    p = p.resolve()
    if p.is_dir():
        raise FileOperationError(f"Path is a directory, not a file: {file_name}")
    if not p.exists():
        raise FileOperationError(f"File not found: {file_name}")
    return p
