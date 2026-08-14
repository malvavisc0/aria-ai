"""File write and modification operations."""

from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from aria.tools import Reason
from aria.tools.decorators import tool_function
from aria.tools.files._internals import _create_backup, _secure_resolve_path
from aria.tools.files._responses import file_success_response
from aria.tools.files.decorators import (
    with_file_operation_error_handling,
    with_input_validation,
)
from aria.tools.files.exceptions import FileOperationError
from aria.tools.files.unified_read import _count_lines_efficiently

# ---------------------------------------------------------------------------
# Explicit schemas exposed to the LLM (mirrors ShellToolSchema pattern).
# llama-index's auto-schema does NOT extract descriptions from docstrings,
# so every field must carry a Field(description=...) for the LLM to
# understand what it should pass.
# ---------------------------------------------------------------------------


class WriteFileSchema(BaseModel):
    """Schema exposed to the LLM for write_file."""

    reason: str = Field(
        description="Required. Brief explanation of why you are writing this file."
    )
    file_name: str = Field(
        description=(
            "Absolute path to the file to create or overwrite "
            "(e.g. /home/user/project/file.txt)."
        )
    )
    contents: str = Field(description="The full content to write into the file.")
    mode: str = Field(
        default="overwrite",
        description=(
            "'overwrite' to replace the entire file (creates parent dirs), "
            "'append' to add content to the end of an existing file."
        ),
    )


class EditFileSchema(BaseModel):
    """Schema exposed to the LLM for edit_file.

    Uses line-based editing: specify an offset (0-indexed line number),
    how many existing lines to replace/delete, and the new lines to insert.
    """

    reason: str = Field(
        description="Required. Brief explanation of why you are editing this file."
    )
    file_name: str = Field(
        description=(
            "Absolute path to an existing file to edit "
            "(e.g. /home/user/project/file.txt)."
        )
    )
    offset: int = Field(
        description=(
            "0-indexed line number where the edit starts. "
            "For example, 0 means the very first line."
        )
    )
    length: int = Field(
        default=0,
        description=(
            "Number of existing lines to remove or replace starting at offset. "
            "0 = pure insert (no lines removed)."
        ),
    )
    new_lines: list[str] | None = Field(
        default=None,
        description=(
            "Lines to insert or use as replacements. "
            "Omit or null for a pure delete (length > 0, no new lines)."
        ),
    )


def _atomic_write(file_path: Path, content: str) -> None:
    """Write file atomically using temp file and rename.

    Args:
        file_path: Path to write to
        content: Content to write

    Raises:
        FileOperationError: If write fails
    """
    import tempfile

    tmp_path = None
    try:
        # Write to temp file in same directory (for atomic rename)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=file_path.parent,
            delete=False,
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        # Atomic rename
        tmp_path.rename(file_path)
    except OSError as exc:
        # Clean up temp file if it exists
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
        raise FileOperationError(f"Failed to write file: {exc}") from exc


def _should_skip_index(i: int, offset: int, length: int) -> bool:
    return offset < i < offset + length


def _is_insert_position(i: int, offset: int) -> bool:
    return i == offset


def _is_before_offset(i: int, offset: int) -> bool:
    return i < offset


def _process_position(
    i: int,
    line: str,
    offset: int,
    length: int,
    new_lines: list[str] | None,
    outfile,
    counter: list[int],
) -> None:
    if _is_before_offset(i, offset):
        _emit_line(line, outfile, counter)
    elif _is_insert_position(i, offset):
        _emit_insert_lines(new_lines, outfile, counter)
        if length == 0:
            _emit_line(line, outfile, counter)
    elif not _should_skip_index(i, offset, length):
        _emit_line(line, outfile, counter)


def _emit_line(line: str, outfile, counter: list[int]) -> None:
    outfile.write(line)
    counter[0] += 1


def _emit_insert_lines(
    new_lines: list[str] | None, outfile, counter: list[int]
) -> None:
    if not new_lines:
        return
    for new_line in new_lines:
        outfile.write(new_line + "\n")
        counter[0] += 1


def _copy_streaming(
    infile,
    outfile,
    offset: int,
    length: int,
    new_lines: list[str] | None,
) -> tuple[int, int]:
    """Stream-copy ``infile`` to ``outfile`` applying the modification."""
    old_total_lines = 0
    counter: list[int] = [0]

    for i, line in enumerate(infile):
        old_total_lines += 1
        _process_position(i, line, offset, length, new_lines, outfile, counter)

    if offset >= old_total_lines:
        _emit_insert_lines(new_lines, outfile, counter)

    return old_total_lines, counter[0]


def _modify_lines_streaming(
    file_path: Path, offset: int, length: int, new_lines: list[str] | None
) -> tuple[int, int]:
    """Modify lines in file using streaming.

    Args:
        file_path: Path to the file
        offset: Starting line number (0-indexed)
        length: Number of lines to delete (0 = just insert)
        new_lines: Lines to insert (None = just delete)

    Returns:
        Tuple of (old_total_lines, new_total_lines)

    Raises:
        FileOperationError: If operation fails
    """
    import shutil

    temp_path = file_path.with_suffix(file_path.suffix + ".tmp")

    try:
        with (
            open(file_path, encoding="utf-8") as infile,
            open(temp_path, "w", encoding="utf-8") as outfile,
        ):
            totals = _copy_streaming(infile, outfile, offset, length, new_lines)

        shutil.move(str(temp_path), str(file_path))
        return totals

    except Exception as exc:
        if temp_path.exists():
            temp_path.unlink()
        raise FileOperationError(f"Failed to modify file: {exc}") from exc


@tool_function(
    "write_file",
    validate={"contents": True},
    error_handler=with_file_operation_error_handling,
    validation_decorator=with_input_validation,
)
def write_file(
    reason: Reason,
    file_name: str,
    contents: str,
    mode: str = "overwrite",
) -> str:
    """Write or append to a file (atomic, dirs auto-created, backup on overwrite).

    Returns:
        JSON with bytes_written/appended, lines, created, backup_created.
    """
    if mode not in ("overwrite", "append"):
        raise FileOperationError(
            f"Invalid mode: {mode!r}. Must be 'overwrite' or 'append'."
        )

    if mode == "overwrite":
        return _write_file_overwrite(reason, file_name, contents)
    else:
        return _write_file_append(reason, file_name, contents)


def _write_file_overwrite(reason: str, file_name: str, contents: str) -> str:
    """Overwrite or create a file atomically."""
    logger.info(f"Writing file (overwrite): {file_name}")

    # Resolve path
    resolved_path = _secure_resolve_path(file_name, check_exists=False)

    # Check if file exists
    file_existed = resolved_path.exists()

    # Create backup if file exists
    backup_path = None
    if file_existed:
        backup_path = _create_backup(resolved_path)

    # Create parent directories
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    # Write content atomically
    _atomic_write(resolved_path, contents)

    # Calculate metrics
    bytes_written = len(contents.encode("utf-8"))
    lines_written = contents.count("\n")
    if not contents.endswith("\n") and contents:
        lines_written += 1

    # Build and return response
    data = {
        "file_name": file_name,
        "mode": "overwrite",
        "bytes_written": bytes_written,
        "lines_written": lines_written,
        "created": not file_existed,
        "backup_created": backup_path is not None,
    }
    logger.info(f"Successfully wrote {bytes_written} bytes to {file_name}")
    return file_success_response(reason, data, tool="write_file")


def _write_file_append(reason: str, file_name: str, contents: str) -> str:
    """Append content to an existing file."""
    logger.info(f"Appending to file: {file_name}")

    # Resolve path
    resolved_path = _secure_resolve_path(file_name)

    # Append content
    with open(resolved_path, "a", encoding="utf-8") as f:
        f.write(contents)

    # Calculate metrics
    bytes_appended = len(contents.encode("utf-8"))
    new_total_lines = _count_lines_efficiently(resolved_path)
    new_file_size = resolved_path.stat().st_size

    # Build and return response
    data = {
        "file_name": file_name,
        "mode": "append",
        "bytes_appended": bytes_appended,
        "new_total_lines": new_total_lines,
        "new_file_size": new_file_size,
    }
    logger.info(f"Successfully appended {bytes_appended} bytes to {file_name}")
    return file_success_response(reason, data, tool="write_file")


@tool_function(
    "edit_file",
    validate={"offset": True},
    error_handler=with_file_operation_error_handling,
    validation_decorator=with_input_validation,
)
def edit_file(
    reason: Reason,
    file_name: str,
    offset: int,
    length: int = 0,
    new_lines: list[str] | None = None,
) -> str:
    """Edit specific lines in a file (backup always created).

    Operation: length=0+new_lines→insert; length>0+new_lines→replace;
    length>0+new_lines=None→delete.

    Returns:
        JSON with operation, offset, lines_affected, old/new total_lines.
    """
    # Determine operation type
    if length == 0 and new_lines is not None:
        operation = "insert"
    elif length > 0 and new_lines is not None:
        operation = "replace"
    elif length > 0 and new_lines is None:
        operation = "delete"
    else:
        raise FileOperationError(
            "Invalid edit_file parameters: provide new_lines for insert, "
            "or length>0 for replace/delete."
        )

    logger.info(
        f"Editing file {file_name}: {operation} (offset={offset}, length={length})"
    )

    # Resolve path
    resolved_path = _secure_resolve_path(file_name)

    # Always create backup before modification
    backup_path = _create_backup(resolved_path)

    # Modify lines using streaming
    old_total_lines, new_total_lines = _modify_lines_streaming(
        resolved_path, offset, length, new_lines
    )

    # Calculate lines affected
    if operation == "delete":
        lines_affected = length
    else:
        # insert or replace — new_lines is guaranteed non-None
        lines_affected = len(new_lines)  # type: ignore[arg-type]

    # Build and return response
    data = {
        "file_name": file_name,
        "operation": operation,
        "offset": offset,
        "length": length,
        "lines_affected": lines_affected,
        "old_total_lines": old_total_lines,
        "new_total_lines": new_total_lines,
        "backup_created": backup_path is not None,
    }
    logger.info(
        f"Successfully {operation}ed in {file_name}: "
        f"{old_total_lines} → {new_total_lines} lines"
    )
    return file_success_response(reason, data)
