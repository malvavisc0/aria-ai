"""File operations tools."""

# File management operations
from aria.tools.files.file_management import (
    copy_file,
)

# Unified read operations
from aria.tools.files.unified_read import (
    FileInfoSchema,
    ListFilesSchema,
    ReadFileSchema,
    SearchFilesSchema,
    file_info,
    list_files,
    read_file,
    search_files,
)

# Unified write operations
from aria.tools.files.write_operations import (
    EditFileSchema,
    WriteFileSchema,
    edit_file,
    write_file,
)

__all__ = [
    # Unified read operations
    "read_file",
    "file_info",
    "list_files",
    "search_files",
    # Unified write operations
    "write_file",
    "edit_file",
    # Schemas for LLM tool calling
    "ReadFileSchema",
    "FileInfoSchema",
    "ListFilesSchema",
    "SearchFilesSchema",
    "WriteFileSchema",
    "EditFileSchema",
    # File management
    "copy_file",
]
