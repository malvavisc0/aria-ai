"""File management operations (copy)."""

from shutil import copy2

from loguru import logger

from aria.tools import Reason
from aria.tools.decorators import tool_function
from aria.tools.files._internals import (
    validate_and_resolve_two_files,
)
from aria.tools.files._responses import (
    file_error_response,
    file_success_response,
)
from aria.tools.files.decorators import with_file_operation_error_handling
from aria.tools.files.exceptions import FileOperationError


@tool_function(
    "copy_file",
    error_handler=with_file_operation_error_handling,
)
def copy_file(
    reason: Reason,
    source: str,
    destination: str,
    overwrite: bool | None = False,
) -> str:
    """Copy a file to a new location (dirs auto-created).

    Returns:
        JSON with source, destination, bytes_copied, success.
    """
    logger.info(f"Copying file from {source} to {destination}")

    source_path, dest_path = validate_and_resolve_two_files(
        source, destination, dest_must_exist=False
    )

    if dest_path.exists() and not overwrite:
        return file_error_response(
            reason,
            FileOperationError(
                f"Destination {destination} already exists and overwrite=False"
            ),
        )

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    copy2(source_path, dest_path)
    bytes_copied = dest_path.stat().st_size

    data = {
        "source": source,
        "destination": destination,
        "bytes_copied": bytes_copied,
        "success": True,
    }
    logger.info(f"Successfully copied {source} to {destination}")
    return file_success_response(reason, data, tool="copy_file")
