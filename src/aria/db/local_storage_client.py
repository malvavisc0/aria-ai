"""Local filesystem storage client for Chainlit elements.

This provides a local alternative to cloud storage providers (S3, Azure, GCS)
for development and self-hosted deployments.

URLs are generated as HTTP paths (e.g. ``/storage/image.png``) that the browser
can fetch from the same origin.  A corresponding ``StaticFiles`` mount must be
registered on the Chainlit/FastAPI app so that these paths resolve to the
actual files on disk.
"""

import logging
from pathlib import Path
from typing import Any

import aiofiles
from chainlit.data.storage_clients.base import BaseStorageClient

logger = logging.getLogger(__name__)


class LocalStorageClient(BaseStorageClient):
    """Local filesystem storage for Chainlit elements.

    Stores files in a local directory instead of cloud storage.
    Useful for development, testing, and self-hosted deployments.

    Args:
        storage_path: Path to directory for storing files
            (e.g. ``data/storage``)
        base_url: Base URL prefix for serving files.  Defaults to
            ``/storage`` which produces browser-relative HTTP URLs like
            ``/storage/image.png``.

    Example:
        >>> client = LocalStorageClient(storage_path="data/storage")
        >>> await client.upload_file("image.png", b"...", mime="image/png")
        {'object_key': 'image.png', 'url': '/storage/image.png'}

    Can be used as an async context manager:

        async with LocalStorageClient("data/storage") as client:
            await client.upload_file("test.txt", b"data")
    """

    def __init__(self, storage_path: str | Path, base_url: str = "/storage"):
        """Initialize local storage client.

        Args:
            storage_path: Directory path for storing files (str or Path)
            base_url: URL prefix for file access.  Use ``/storage`` (default)
                for browser-relative HTTP URLs, or a full URL like
                ``http://localhost:9876/storage`` if absolute URLs are needed.
        """
        self.storage_path = Path(storage_path).resolve()
        self.base_url = base_url.rstrip("/")

        # Create storage directory if it doesn't exist
        self.storage_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"LocalStorageClient initialized: storage_path={self.storage_path}")

    def _validate_object_key(self, object_key: str) -> Path:
        """Validate object_key and return safe absolute path.

        Args:
            object_key: Unique identifier for the file (can include subdirectories)

        Returns:
            Resolved absolute path within storage_path

        Raises:
            ValueError: If object_key is an absolute path or resolves outside
                the storage directory
        """
        # Reject absolute paths
        if object_key.startswith("/"):
            raise ValueError(
                f"Invalid object_key: absolute paths not allowed: {object_key}"
            )

        # Resolve the path and verify it's within storage_path
        file_path = (self.storage_path / object_key).resolve()

        if not file_path.is_relative_to(self.storage_path):
            raise ValueError(
                f"Invalid object_key: escapes storage directory: {object_key}"
            )

        return file_path

    async def __aenter__(self) -> "LocalStorageClient":
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager."""
        await self.close()

    async def upload_file(
        self,
        object_key: str,
        data: bytes | str,
        mime: str = "application/octet-stream",
        overwrite: bool = True,
        content_disposition: str | None = None,
    ) -> dict[str, Any]:
        """Upload a file to local storage.

        Args:
            object_key: Unique identifier for the file (can include subdirectories)
            data: File content as bytes or string
            mime: MIME type of the file
            overwrite: Whether to overwrite existing file
            content_disposition: Ignored (for API compatibility with BaseStorageClient)

        Returns:
            Dict with object_key and url

        Raises:
            ValueError: If object_key is invalid (path traversal)
            FileExistsError: If file exists and overwrite=False
            IOError: If file write fails
        """
        file_path = self._validate_object_key(object_key)

        # Check if file exists and overwrite is False
        if file_path.exists() and not overwrite:
            raise FileExistsError(
                f"File already exists: {object_key} (overwrite=False)"
            )

        # Create parent directories if needed
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        if isinstance(data, bytes):
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(data)
        elif isinstance(data, str):
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(data)
        else:
            raise TypeError(f"data must be bytes or str, got {type(data).__name__}")

        # Generate URL using the relative object_key
        url = f"{self.base_url}/{object_key}"

        logger.debug(f"Uploaded file: {object_key} ({mime})")

        return {"object_key": object_key, "url": url}

    async def delete_file(self, object_key: str) -> bool:
        """Delete a file from local storage.

        Args:
            object_key: Unique identifier for the file

        Returns:
            True if file was deleted, False if file didn't exist

        Raises:
            ValueError: If object_key is invalid (path traversal)
        """
        file_path = self._validate_object_key(object_key)

        if file_path.exists() and file_path.is_file():
            file_path.unlink()
            logger.debug(f"Deleted file: {object_key}")
            return True

        logger.warning(f"File not found for deletion: {object_key}")
        return False

    async def get_read_url(self, object_key: str) -> str:
        """Get a URL for reading a file.

        Args:
            object_key: Unique identifier for the file

        Returns:
            HTTP-relative URL to access the file (e.g. ``/storage/image.png``)

        Raises:
            ValueError: If object_key is invalid (path traversal)
            FileNotFoundError: If the file does not exist on disk
        """
        file_path = self._validate_object_key(object_key)

        if not file_path.exists():
            raise FileNotFoundError(f"Storage file not found: {object_key}")

        url = f"{self.base_url}/{object_key}"
        return url

    async def close(self) -> None:
        """Close the storage client.

        For local storage, there are no connections to close.
        """
        logger.debug("LocalStorageClient closed")
