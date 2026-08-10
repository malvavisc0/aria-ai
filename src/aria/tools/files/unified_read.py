"""Unified file read operations.

This module provides 4 unified read tools:
- read_file: Merges read_full_file + read_file_chunk
- file_info: Merges file_exists + get_file_info
- list_files: Merges list_files + get_directory_tree
- search_files: Merges search_files_by_name + search_in_files
"""

import mimetypes
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from aria.tools import Reason, tool_response
from aria.tools.decorators import tool_function
from aria.tools.files._internals import (
    _secure_resolve_dir,
    _secure_resolve_path,
)
from aria.tools.files.decorators import with_file_operation_error_handling
from aria.tools.files.exceptions import FileOperationError

MAX_CONTENT_FILE_SIZE = 1024 * 1024  # 1MB
MAX_FILES_SEARCH = 100
MAX_LINES_PER_FILE = 10000


class ReadFileSchema(BaseModel):
    """Schema exposed to the LLM for read_file."""

    reason: str = Field(
        description="Required. Brief explanation of why you are reading this file."
    )
    file_name: str = Field(
        description=(
            "Absolute path to the file to read (e.g. /home/user/project/file.txt)."
        )
    )
    offset: int | None = Field(
        default=0,
        description="0-indexed line number to start reading from (default: 0).",
    )
    length: int | None = Field(
        default=0,
        description=(
            "Number of lines to read. 0 = read up to max_lines from offset "
            "(default: 0)."
        ),
    )
    max_lines: int | None = Field(
        default=200,
        description="Maximum lines to return per call (default: 200, max: 200).",
    )


class FileInfoSchema(BaseModel):
    """Schema exposed to the LLM for file_info."""

    reason: str = Field(
        description=(
            "Required. Brief explanation of why you need this file's metadata."
        )
    )
    file_name: str = Field(
        description=(
            "Absolute path to the file or directory (e.g. /home/user/project/file.txt)."
        )
    )


class ListFilesSchema(BaseModel):
    """Schema exposed to the LLM for list_files."""

    reason: str = Field(
        description="Required. Brief explanation of why you are listing files."
    )
    pattern: str | None = Field(
        default="*",
        description="Glob filter pattern (default: '*'). E.g. '*.py', '*.txt'.",
    )
    recursive: bool | None = Field(
        default=False,
        description=(
            "If true, returns a directory tree structure "
            "instead of a flat list (default: false)."
        ),
    )
    max_depth: int | None = Field(
        default=3,
        description="Maximum recursion depth for tree view (default: 3).",
    )
    max_results: int | None = Field(
        default=100,
        description="Maximum files to return in flat list mode (default: 100).",
    )
    path: str | None = Field(
        default=".",
        description=(
            "Absolute directory path to list "
            "(e.g. /home/user/project). Default: current workspace."
        ),
    )


class SearchFilesSchema(BaseModel):
    """Schema exposed to the LLM for search_files."""

    reason: str = Field(
        description="Required. Brief explanation of why you are searching files."
    )
    pattern: str = Field(
        description=(
            "Regex pattern to match against filenames or file content "
            "depending on mode."
        )
    )
    mode: str | None = Field(
        default="name",
        description=(
            "'name' to match against filenames, 'content' to search inside "
            "file contents (default: 'name')."
        ),
    )
    file_pattern: str | None = Field(
        default="**/*",
        description="Glob filter for which files to search (default: '**/*').",
    )
    recursive: bool | None = Field(
        default=True,
        description="Search subdirectories recursively (default: true).",
    )
    max_results: int | None = Field(
        default=500,
        description="Maximum matches to return (default: 500).",
    )
    context_lines: int | None = Field(
        default=2,
        description="Lines of context around each match for content mode (default: 2).",
    )
    path: str | None = Field(
        default=".",
        description=(
            "Absolute directory path to search in "
            "(e.g. /home/user/project). Default: current workspace."
        ),
    )


def _read_lines_streaming(file_path: Path, offset: int, length: int) -> list[str]:
    """Read lines from file using streaming.

    Lines exceeding ``MAX_LINE_LENGTH`` are truncated with a notice so the
    agent knows to read the file with a smaller ``length`` or use other
    tools for the full content.

    Args:
        file_path: Path to the file
        offset: Starting line number (0-indexed)
        length: Number of lines to read (0 = read all remaining)

    Returns:
        List[str]: Lines read from file (without newline characters)
    """
    from aria.tools.files.constants import MAX_LINE_LENGTH

    lines = []
    try:
        with open(file_path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < offset:
                    continue
                if length > 0 and i >= offset + length:
                    break
                text = line.rstrip("\n\r")
                if len(text) > MAX_LINE_LENGTH:
                    text = (
                        text[:MAX_LINE_LENGTH] + f"\n[...line {i} truncated — "
                        f"{len(text) - MAX_LINE_LENGTH:,} chars omitted. "
                        f"Use a smaller length to read this file.]"
                    )
                lines.append(text)
        return lines
    except OSError as exc:
        raise FileOperationError(f"Failed to read file: {exc}") from exc


def _count_lines_efficiently(file_path: Path) -> int:
    """Memory-efficient line counting for large files.

    Reads file in chunks to avoid loading entire file into memory.
    Counts the number of lines the same way iteration over a text file
    does: every ``\\n`` starts a new line, and a final chunk that does
    not end with ``\\n`` still counts as its own line.

    Args:
        file_path: Path to the file to count lines for

    Returns:
        int: Number of lines in the file (0 for empty files)

    Raises:
        FileOperationError: If path is a directory or file cannot be read
    """
    if file_path.is_dir():
        raise FileOperationError(f"Path is a directory, not a file: {file_path}")

    count = 0
    last_byte = b""
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                count += chunk.count(b"\n")
                last_byte = chunk[-1:]
        # If the file is non-empty and doesn't end with a newline,
        # there is one more line that was not counted.
        if last_byte and last_byte != b"\n":
            count += 1
        return count
    except OSError as exc:
        raise FileOperationError(
            f"Failed to read file for line counting: {exc}"
        ) from exc


def _build_directory_tree(
    path: Path, current_depth: int, max_depth: int
) -> dict[str, Any]:
    """Build directory tree structure recursively.

    Args:
        path: Path to build tree from
        current_depth: Current recursion depth
        max_depth: Maximum depth to recurse

    Returns:
        Dict representing directory tree
    """
    try:
        result = {"name": path.name, "type": "directory", "children": []}

        if current_depth >= max_depth:
            result["truncated"] = True
            return result

        for child in sorted(path.iterdir()):
            if child.is_dir():
                result["children"].append(
                    _build_directory_tree(child, current_depth + 1, max_depth)
                )
            else:
                result["children"].append({"name": child.name, "type": "file"})

        return result
    except PermissionError:
        return {
            "name": path.name,
            "type": "directory",
            "error": "Permission denied",
        }


def _count_tree_items(tree: dict[str, Any]) -> tuple[int, int]:
    """Count files and directories in a tree.

    Args:
        tree: Tree structure from _build_directory_tree

    Returns:
        Tuple of (total_files, total_directories)
    """
    files = 0
    directories = 0

    if tree.get("type") == "file":
        return 1, 0

    directories = 1  # Count the directory itself
    for child in tree.get("children", []):
        if child.get("type") == "file":
            files += 1
        else:
            child_files, child_dirs = _count_tree_items(child)
            files += child_files
            directories += child_dirs

    return files, directories


def _format_permissions_symbolic(mode: int) -> str:
    """Convert mode bits to symbolic permissions string.

    Args:
        mode: File mode bits from stat

    Returns:
        String like 'rwxr-xr-x'
    """
    perms = []
    for who in ["USR", "GRP", "OTH"]:
        for what in ["R", "W", "X"]:
            bit = getattr(stat, f"S_I{what}{who}")
            perms.append(what.lower() if mode & bit else "-")
    return "".join(perms)


def _ok(tool: str, reason: str, result: dict[str, Any], **metadata) -> str:
    """Build a standard success response."""
    return tool_response(tool=tool, reason=reason, data=result, **metadata)


def _err(tool: str, reason: str, message: str, **metadata) -> str:
    """Build a standard error response from a message string."""
    from aria.tools import tool_error_response

    return tool_error_response(
        tool=tool,
        reason=reason,
        exc=RuntimeError(message),
        **metadata,
    )


@tool_function(
    "read_file",
    error_handler=with_file_operation_error_handling,
)
def read_file(
    reason: Reason,
    file_name: str,
    offset: int | None = 0,
    length: int | None = 0,
    max_lines: int | None = 200,
) -> str:
    """Read file contents in chunks. Never reads an entire file at once.

    Output is chunked via offset/length parameters.

    Args:
        reason: Required. Brief explanation of why you are reading this file.
        file_name: Path relative to BASE_DIR.
        offset: Start line 0-indexed (default: 0).
        length: Lines to read; 0=all up to max_lines (default: 0).
        max_lines: Max lines per call (default: 200).

    Returns:
        JSON with lines/content, total_lines, has_more, next_offset.
    """
    offset_value = 0 if offset is None else offset
    length_value = 0 if length is None else length
    max_lines_value = 200 if max_lines is None else max_lines

    logger.info(
        f"Reading file: {file_name} (offset={offset_value}, length={length_value})"
    )

    try:
        resolved_path = _secure_resolve_path(file_name)

        total_lines = _count_lines_efficiently(resolved_path)

        # Always enforce chunked reading — cap lines to max_lines_value
        if offset_value == 0 and length_value == 0:
            lines_to_read = min(total_lines, max_lines_value)
        else:
            lines_to_read = length_value if length_value > 0 else max_lines_value
            lines_to_read = min(lines_to_read, max_lines_value)

        lines = _read_lines_streaming(resolved_path, offset_value, lines_to_read)
        lines_returned = len(lines)
        next_offset = offset_value + lines_returned
        has_more = next_offset < total_lines

        return _ok(
            tool="read_file",
            reason=reason,
            result={
                "file_name": file_name,
                "lines": lines,
                "offset": offset_value,
                "lines_returned": lines_returned,
                "total_lines": total_lines,
                "has_more": has_more,
                "next_offset": next_offset if has_more else None,
                "mode": "chunked",
            },
            file_name=file_name,
        )

    except Exception as exc:
        return _err(
            tool="read_file",
            reason=reason,
            message=str(exc),
            file_name=file_name,
        )


@tool_function(
    "file_info",
    error_handler=with_file_operation_error_handling,
)
def file_info(reason: Reason, file_name: str) -> str:
    """Get metadata for a file or directory (size, type, permissions, timestamps).

    Args:
        reason: Required. Brief explanation of why you need this file's metadata.
        file_name: Path to the file or directory.

    Returns:
        JSON with exists, is_file, is_directory, size_bytes,
        modified, permissions, mime_type.
    """
    logger.info(f"Getting file info for: {file_name}")

    try:
        try:
            resolved_path = _secure_resolve_path(file_name, check_exists=False)
        except FileOperationError:
            # If it fails (e.g., is a directory), try as a directory
            resolved_path = _secure_resolve_dir(file_name, check_exists=False)

        exists = resolved_path.exists()
        is_file = resolved_path.is_file() if exists else False
        is_directory = resolved_path.is_dir() if exists else False
        is_symlink = resolved_path.is_symlink() if exists else False

        result = {
            "file_name": file_name,
            "exists": exists,
            "is_file": is_file,
            "is_directory": is_directory,
            "is_symlink": is_symlink,
        }

        if exists and (is_file or is_directory):
            file_stats = resolved_path.stat()

            result.update(
                {
                    "size_bytes": file_stats.st_size,
                    "size_mb": round(file_stats.st_size / (1024 * 1024), 4),
                    "modified": datetime.fromtimestamp(
                        file_stats.st_mtime, tz=UTC
                    ).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "created": datetime.fromtimestamp(
                        file_stats.st_ctime, tz=UTC
                    ).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "permissions": _format_permissions_symbolic(file_stats.st_mode),
                    "mode_octal": oct(file_stats.st_mode)[-3:],
                }
            )

            if is_file:
                result.update(
                    {
                        "total_lines": _count_lines_efficiently(resolved_path),
                        "mime_type": mimetypes.guess_type(file_name)[0],
                    }
                )

        return _ok(
            tool="file_info",
            reason=reason,
            result=result,
            file_name=file_name,
        )

    except Exception as exc:
        return _err(
            tool="file_info",
            reason=reason,
            message=str(exc),
            file_name=file_name,
        )


def _resolve_listing_path(path_value: str) -> tuple[Path | None, str | None]:
    """Return (path, None) on success or (None, error_response) on failure."""
    try:
        resolved = _secure_resolve_dir(path_value)
        if not resolved.exists():
            resolved = _secure_resolve_path(path_value, check_exists=False)
        if not resolved.exists():
            return None, "Path does not exist"
        return resolved, None
    except Exception as exc:
        return None, str(exc)


def _single_file_response(path_value: str) -> dict[str, Any]:
    return {
        "path": path_value,
        "is_file": True,
        "files": [path_value],
        "count": 1,
        "truncated": False,
    }


def _tree_response(
    path_value: str, resolved_path: Path, max_depth_value: int
) -> dict[str, Any]:
    tree = _build_directory_tree(resolved_path, 0, max_depth_value)
    total_files, total_directories = _count_tree_items(tree)
    return {
        "path": path_value,
        "tree": tree,
        "total_files": total_files,
        "total_directories": total_directories,
        "mode": "tree",
        "max_depth": max_depth_value,
    }


def _relative_or_absolute(match: Path, resolved_path: Path) -> str:
    try:
        return str(match.relative_to(resolved_path))
    except ValueError:
        return str(match)


def _flat_listing(
    resolved_path: Path,
    pattern_value: str,
    recursive_value: bool,
    max_results_value: int,
) -> tuple[list[str], bool]:
    matches = (
        list(resolved_path.rglob(pattern_value))
        if recursive_value
        else list(resolved_path.glob(pattern_value))
    )
    files = []
    for match in matches:
        if not match.is_file():
            continue
        files.append(_relative_or_absolute(match, resolved_path))
        if len(files) >= max_results_value:
            break
    return files, len(matches) > max_results_value


def _normalize_list_params(
    pattern: str | None,
    recursive: bool | None,
    max_depth: int | None,
    max_results: int | None,
    path: str | None,
) -> tuple[str, bool, int, int, str]:
    return (
        pattern or "*",
        False if recursive is None else recursive,
        3 if max_depth is None else max_depth,
        100 if max_results is None else max_results,
        path or ".",
    )


def _flat_response(
    path_value: str,
    pattern_value: str,
    files: list[str],
    truncated: bool,
) -> dict[str, Any]:
    return {
        "path": path_value,
        "pattern": pattern_value,
        "files": files,
        "count": len(files),
        "truncated": truncated,
        "mode": "flat",
    }


@tool_function(
    "list_files",
    error_handler=with_file_operation_error_handling,
)
def list_files(
    reason: Reason,
    pattern: str | None = "*",
    recursive: bool | None = False,
    max_depth: int | None = 3,
    max_results: int | None = 100,
    path: str | None = ".",
) -> str:
    """List files/dirs with optional recursive tree view.

    Args:
        reason: Required. Brief explanation of why you are listing files.
        pattern: Glob filter (default: "*").
        recursive: Tree view if True (default: False).
        max_depth: Max depth for tree (default: 3).
        max_results: Cap for flat list (default: 100).
        path: Start dir relative to BASE_DIR (default: ".").

    Returns:
        JSON with files (flat) or tree (recursive), plus count.
    """
    pattern_value, recursive_value, max_depth_value, max_results_value, path_value = (
        _normalize_list_params(pattern, recursive, max_depth, max_results, path)
    )
    logger.info(
        f"Listing files: path={path_value}, pattern={pattern_value}, "
        f"recursive={recursive_value}"
    )

    resolved_path, error = _resolve_listing_path(path_value)
    if error is not None:
        message = (
            f"Path does not exist: {path_value}"
            if error == "Path does not exist"
            else error
        )
        return _err(
            tool="list_files",
            reason=reason,
            message=message,
            path=path_value,
        )
    assert resolved_path is not None

    if resolved_path.is_file():
        return _ok(
            tool="list_files",
            reason=reason,
            result=_single_file_response(path_value),
            path=path_value,
        )
    if recursive_value and pattern_value == "*":
        return _ok(
            tool="list_files",
            reason=reason,
            result=_tree_response(path_value, resolved_path, max_depth_value),
            path=path_value,
        )

    files, truncated = _flat_listing(
        resolved_path, pattern_value, recursive_value, max_results_value
    )
    return _ok(
        tool="list_files",
        reason=reason,
        result=_flat_response(path_value, pattern_value, files, truncated),
        path=path_value,
    )


def _search_names(
    resolved_path: Path,
    regex: re.Pattern[str],
    recursive: bool,
    max_results: int,
) -> tuple[list[str], bool]:
    """Search file names matching ``regex`` under ``resolved_path``."""
    matches: list[str] = []
    paths = resolved_path.rglob("*") if recursive else resolved_path.glob("*")
    for file_path in paths:
        if not (file_path.is_file() and regex.search(file_path.name)):
            continue
        try:
            matches.append(str(file_path.relative_to(resolved_path)))
        except ValueError:
            continue
        if len(matches) >= max_results:
            break
    return matches, len(matches) >= max_results


def _match_line(
    lines: list[str],
    regex: re.Pattern[str],
    line_num: int,
    context_lines: int,
) -> dict[str, Any] | None:
    """Return a match dict for ``line_num`` if ``regex`` hits, else None."""
    if not regex.search(lines[line_num]):
        return None
    start = max(0, line_num - context_lines)
    end = min(len(lines), line_num + context_lines + 1)
    return {
        "line_number": line_num + 1,
        "line_content": lines[line_num].rstrip("\n\r"),
        "context_before": [lines[i].rstrip("\n\r") for i in range(start, line_num)],
        "context_after": [lines[i].rstrip("\n\r") for i in range(line_num + 1, end)],
    }


def _iter_candidate_files(resolved_path: Path, file_pattern: str, recursive: bool):
    """Yield candidate files under size limit matching ``file_pattern``."""
    paths = (
        resolved_path.rglob(file_pattern)
        if recursive
        else resolved_path.glob(file_pattern)
    )
    for file_path in paths:
        if not file_path.is_file():
            continue
        try:
            size = file_path.stat().st_size
        except OSError:
            continue
        if size > MAX_CONTENT_FILE_SIZE:
            logger.debug(
                f"Skipping {file_path}: size {size} exceeds "
                f"limit {MAX_CONTENT_FILE_SIZE}"
            )
            continue
        yield file_path


def _read_lines(file_path: Path) -> list[str] | None:
    """Read up to ``MAX_LINES_PER_FILE`` lines; None on read error."""
    try:
        lines: list[str] = []
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                lines.append(line)
                if len(lines) > MAX_LINES_PER_FILE:
                    break
        return lines
    except (OSError, UnicodeDecodeError):
        return None


def _search_content(
    resolved_path: Path,
    file_pattern: str,
    regex: re.Pattern[str],
    recursive: bool,
    max_results: int,
    context_lines: int,
) -> tuple[list[dict[str, Any]], int, bool]:
    """Search file contents matching ``regex`` under ``resolved_path``."""
    matches: list[dict[str, Any]] = []
    files_searched = 0
    for file_path in _iter_candidate_files(resolved_path, file_pattern, recursive):
        if files_searched >= MAX_FILES_SEARCH:
            break
        files_searched += 1
        lines = _read_lines(file_path)
        if lines is None:
            continue
        rel_path = str(file_path.relative_to(resolved_path))
        for line_num in range(len(lines)):
            if len(matches) >= max_results:
                break
            hit = _match_line(lines, regex, line_num, context_lines)
            if hit is not None:
                matches.append({"file": rel_path, **hit})
        if len(matches) >= max_results:
            break

    truncated = len(matches) >= max_results or files_searched >= MAX_FILES_SEARCH
    return matches, files_searched, truncated


def _prepare_search(
    reason: str, path_value: str, pattern: str
) -> tuple[Path, re.Pattern[str]] | str:
    """Resolve the search path and compile the regex, or return an error."""
    resolved_path = _secure_resolve_dir(path_value)
    if not resolved_path.exists():
        resolved_path = _secure_resolve_path(path_value, check_exists=False)
    if not resolved_path.exists():
        return _err(
            tool="search_files",
            reason=reason,
            message=f"Path does not exist: {path_value}",
            path=path_value,
        )
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return _err(
            tool="search_files",
            reason=reason,
            message=f"Invalid regex pattern: {exc}",
            pattern=pattern,
        )
    return resolved_path, regex


def _search_params(
    mode: str | None,
    file_pattern: str | None,
    recursive: bool | None,
    max_results: int | None,
    context_lines: int | None,
    path: str | None,
) -> tuple[str, str, bool, int, int, str]:
    """Apply defaults to the search_files parameters."""
    return (
        mode or "name",
        file_pattern or "**/*",
        True if recursive is None else recursive,
        500 if max_results is None else max_results,
        2 if context_lines is None else context_lines,
        path or ".",
    )


@tool_function(
    "search_files",
    error_handler=with_file_operation_error_handling,
)
def search_files(
    reason: Reason,
    pattern: str,
    mode: str | None = "name",
    file_pattern: str | None = "**/*",
    recursive: bool | None = True,
    max_results: int | None = 500,
    context_lines: int | None = 2,
    path: str | None = ".",
) -> str:
    """Search files by name pattern or content regex.

    Args:
        reason: Required. Brief explanation of why you are searching files.
        pattern: Regex to match filenames or content.
        mode: name|content (default: name).
        file_pattern: Glob filter for files (default: "**/*").
        recursive: Search recursively (default: True).
        max_results: Cap results (default: 500).
        context_lines: Context lines around matches (default: 2).
        path: Start dir relative to BASE_DIR (default: ".").

    Returns:
        JSON with matches[] (file, line, context), count.
    """
    (
        mode_value,
        file_pattern_value,
        recursive_value,
        max_results_value,
        context_lines_value,
        path_value,
    ) = _search_params(mode, file_pattern, recursive, max_results, context_lines, path)

    logger.info(
        f"Searching files: path={path_value}, pattern={pattern}, "
        f"mode={mode_value}, file_pattern={file_pattern_value}"
    )

    try:
        prepared = _prepare_search(reason, path_value, pattern)
        if isinstance(prepared, str):
            return prepared
        resolved_path, regex = prepared

        if mode_value == "name":
            matches, truncated = _search_names(
                resolved_path, regex, recursive_value, max_results_value
            )
            return _ok(
                tool="search_files",
                reason=reason,
                result={
                    "pattern": pattern,
                    "mode": "name",
                    "matches": matches,
                    "count": len(matches),
                    "truncated": truncated,
                },
                path=path_value,
                pattern=pattern,
            )

        if mode_value == "content":
            matches, files_searched, truncated = _search_content(
                resolved_path,
                file_pattern_value,
                regex,
                recursive_value,
                max_results_value,
                context_lines_value,
            )
            return _ok(
                tool="search_files",
                reason=reason,
                result={
                    "pattern": pattern,
                    "mode": "content",
                    "matches": matches,
                    "total_matches": len(matches),
                    "files_searched": files_searched,
                    "truncated": truncated,
                },
                path=path_value,
                pattern=pattern,
            )

        return _err(
            tool="search_files",
            reason=reason,
            message=(f"Invalid mode '{mode_value}'. Use 'name' or 'content'."),
            pattern=pattern,
        )

    except Exception as exc:
        return _err(
            tool="search_files",
            reason=reason,
            message=str(exc),
            pattern=pattern,
        )
