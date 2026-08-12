"""Tests for LocalStorageClient."""

from pathlib import Path

import pytest

from aria.db.local_storage_client import LocalStorageClient


class TestLocalStorageClientInit:
    """Test suite for LocalStorageClient initialization."""

    @pytest.mark.asyncio
    async def test_initialization(self, tmp_path: Path):
        """Test LocalStorageClient initialization."""
        storage_path = tmp_path / "storage"
        client = LocalStorageClient(storage_path=str(storage_path))

        assert client.storage_path == storage_path
        assert storage_path.exists()
        assert storage_path.is_dir()

    @pytest.mark.asyncio
    async def test_default_base_url(self, tmp_path: Path):
        """Test default base_url is /storage."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        assert client.base_url == "/storage"

    @pytest.mark.asyncio
    async def test_custom_base_url(self, tmp_path: Path):
        """Test custom base_url is stored correctly."""
        client = LocalStorageClient(
            storage_path=str(tmp_path / "storage"),
            base_url="http://localhost:9876/storage",
        )
        assert client.base_url == "http://localhost:9876/storage"

    @pytest.mark.asyncio
    async def test_base_url_trailing_slash_stripped(self, tmp_path: Path):
        """Test trailing slash is stripped from base_url."""
        client = LocalStorageClient(
            storage_path=str(tmp_path / "storage"),
            base_url="/storage/",
        )
        assert client.base_url == "/storage"


class TestPathValidation:
    """Test suite for path validation and traversal protection."""

    @pytest.mark.asyncio
    async def test_rejects_absolute_path(self, tmp_path: Path):
        """Test that absolute paths are rejected."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        with pytest.raises(ValueError, match="absolute paths not allowed"):
            client._validate_object_key("/etc/passwd")

    @pytest.mark.asyncio
    async def test_rejects_traversal_with_dotdot(self, tmp_path: Path):
        """Test that path traversal via .. is rejected."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        with pytest.raises(ValueError, match="escapes storage directory"):
            client._validate_object_key("../../etc/passwd")

    @pytest.mark.asyncio
    async def test_rejects_traversal_in_subdirectory(self, tmp_path: Path):
        """Test that traversal from a subdirectory is rejected."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        with pytest.raises(ValueError, match="escapes storage directory"):
            client._validate_object_key("subdir/../../etc/passwd")

    @pytest.mark.asyncio
    async def test_allows_dotdot_in_filename(self, tmp_path: Path):
        """Test that filenames containing .. are allowed if safe."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        # A filename like "data..backup.txt" contains ".." but
        # resolves safely within the storage directory.
        path = client._validate_object_key("data..backup.txt")
        assert path.is_relative_to(client.storage_path)
        assert path.name == "data..backup.txt"

    @pytest.mark.asyncio
    async def test_allows_nested_object_key(self, tmp_path: Path):
        """Test that nested subdirectory keys are allowed."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        path = client._validate_object_key("threads/abc-123/elements/image.png")
        assert path.is_relative_to(client.storage_path)

    @pytest.mark.asyncio
    async def test_resolved_path_is_absolute(self, tmp_path: Path):
        """Test that validated path is resolved and absolute."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        path = client._validate_object_key("test.txt")
        assert path.is_absolute()

    @pytest.mark.asyncio
    async def test_rejects_null_byte_in_key(self, tmp_path: Path):
        """Null bytes (a path injection vector) must be rejected."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        with pytest.raises((ValueError, TypeError)):
            client._validate_object_key("evil\0/etc/passwd")

    @pytest.mark.asyncio
    async def test_rejects_symlink_escape(self, tmp_path: Path):
        """A symlink inside storage pointing outside must not escape on upload."""
        storage = tmp_path / "storage"
        secret = tmp_path / "secret.txt"
        secret.write_bytes(b"private")
        client = LocalStorageClient(storage_path=str(storage))
        # Pre-place a symlink inside storage that points outside.
        link = storage / "escape.png"
        link.symlink_to(secret)
        # Uploading *through* the symlink must not write outside storage; the
        # resolved target is outside, so validation should reject it.
        with pytest.raises(ValueError):
            await client.upload_file(object_key="escape.png", data=b"x")

    @pytest.mark.asyncio
    async def test_rejects_empty_object_key(self, tmp_path: Path):
        """An empty key resolves to the storage dir itself; upload must fail."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        with pytest.raises((ValueError, IsADirectoryError, OSError)):
            await client.upload_file(object_key="", data=b"x")


class TestUploadFile:
    """Test suite for file upload operations."""

    @pytest.mark.asyncio
    async def test_upload_bytes(self, tmp_path: Path):
        """Test uploading a file with bytes data."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        data = b"Hello, World!"
        result = await client.upload_file(
            object_key="test.txt", data=data, mime="text/plain"
        )

        assert result["object_key"] == "test.txt"
        assert result["url"] == "/storage/test.txt"

        file_path = client.storage_path / "test.txt"
        assert file_path.exists()
        assert file_path.read_bytes() == data

    @pytest.mark.asyncio
    async def test_upload_string(self, tmp_path: Path):
        """Test uploading a file with string data."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        data = "Hello, World!"
        result = await client.upload_file(
            object_key="test.txt", data=data, mime="text/plain"
        )

        assert result["object_key"] == "test.txt"
        file_path = client.storage_path / "test.txt"
        assert file_path.exists()
        assert file_path.read_text(encoding="utf-8") == data

    @pytest.mark.asyncio
    async def test_upload_unicode_string_utf8(self, tmp_path: Path):
        """Test that string writes use UTF-8 encoding."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        unicode_data = "Hello 世界 🌍 Привет"
        await client.upload_file(
            object_key="unicode.txt",
            data=unicode_data,
            mime="text/plain",
        )

        file_path = client.storage_path / "unicode.txt"
        # Verify the file is valid UTF-8
        assert file_path.read_text(encoding="utf-8") == unicode_data
        # Verify the raw bytes are UTF-8 encoded
        assert file_path.read_bytes() == unicode_data.encode("utf-8")

    @pytest.mark.asyncio
    async def test_upload_with_subdirectory(self, tmp_path: Path):
        """Test uploading a file with subdirectory in object_key."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        data = b"Test data"
        result = await client.upload_file(
            object_key="subdir/nested/file.bin", data=data
        )

        assert result["object_key"] == "subdir/nested/file.bin"
        assert result["url"] == "/storage/subdir/nested/file.bin"

        file_path = client.storage_path / "subdir" / "nested" / "file.bin"
        assert file_path.exists()
        assert file_path.read_bytes() == data

    @pytest.mark.asyncio
    async def test_upload_overwrite_true(self, tmp_path: Path):
        """Test uploading a file with overwrite=True."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        await client.upload_file(
            object_key="test.txt", data=b"Original", overwrite=True
        )
        result = await client.upload_file(
            object_key="test.txt", data=b"Updated", overwrite=True
        )

        assert result["object_key"] == "test.txt"
        file_path = client.storage_path / "test.txt"
        assert file_path.read_bytes() == b"Updated"

    @pytest.mark.asyncio
    async def test_upload_overwrite_false(self, tmp_path: Path):
        """Test uploading a file with overwrite=False raises error."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        await client.upload_file(
            object_key="test.txt", data=b"Original", overwrite=True
        )

        with pytest.raises(FileExistsError, match="File already exists"):
            await client.upload_file(
                object_key="test.txt",
                data=b"Updated",
                overwrite=False,
            )

        # Verify original file was not overwritten
        file_path = client.storage_path / "test.txt"
        assert file_path.read_bytes() == b"Original"

    @pytest.mark.asyncio
    async def test_upload_binary_data(self, tmp_path: Path):
        """Test uploading binary data (e.g., image)."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        binary_data = bytes(range(256))
        result = await client.upload_file(
            object_key="image.png",
            data=binary_data,
            mime="image/png",
        )

        assert result["object_key"] == "image.png"
        file_path = client.storage_path / "image.png"
        assert file_path.read_bytes() == binary_data

    @pytest.mark.asyncio
    async def test_upload_multiple_files(self, tmp_path: Path):
        """Test uploading multiple files."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        files = {
            "file1.txt": b"Content 1",
            "file2.txt": b"Content 2",
            "subdir/file3.txt": b"Content 3",
        }

        for object_key, data in files.items():
            result = await client.upload_file(object_key=object_key, data=data)
            assert result["object_key"] == object_key

        for object_key, data in files.items():
            file_path = client.storage_path / object_key
            assert file_path.exists()
            assert file_path.read_bytes() == data

    @pytest.mark.asyncio
    async def test_upload_rejects_non_bytes_or_str(self, tmp_path: Path):
        """L5: non-bytes/str input must raise, not silently stringify garbage."""
        from typing import Any

        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        bad_none: Any = None
        bad_int: Any = 123
        with pytest.raises(TypeError):
            await client.upload_file(object_key="bad.txt", data=bad_none)
        with pytest.raises(TypeError):
            await client.upload_file(object_key="bad.txt", data=bad_int)
        assert not (client.storage_path / "bad.txt").exists()


class TestURLGeneration:
    """Test suite for URL generation correctness."""

    @pytest.mark.asyncio
    async def test_url_uses_object_key_not_absolute_path(self, tmp_path: Path):
        """Test that URLs use relative object_key, not absolute path."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        result = await client.upload_file(object_key="test.txt", data=b"Test")

        url = result["url"]
        # URL must NOT contain the absolute filesystem path
        assert str(tmp_path) not in url
        # URL must be base_url/object_key
        assert url == "/storage/test.txt"

    @pytest.mark.asyncio
    async def test_url_with_custom_base_url(self, tmp_path: Path):
        """Test URL generation with custom base URL."""
        client = LocalStorageClient(
            storage_path=str(tmp_path / "storage"),
            base_url="http://localhost:9876/storage",
        )
        await client.upload_file(object_key="test.txt", data=b"Test")

        url = await client.get_read_url("test.txt")
        assert url == "http://localhost:9876/storage/test.txt"

    @pytest.mark.asyncio
    async def test_url_with_nested_object_key(self, tmp_path: Path):
        """Test URL generation with nested subdirectory key."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        result = await client.upload_file(
            object_key="threads/abc/image.png", data=b"img"
        )

        assert result["url"] == "/storage/threads/abc/image.png"

    @pytest.mark.asyncio
    async def test_get_read_url_matches_upload_url(self, tmp_path: Path):
        """Test that get_read_url returns same URL as upload_file."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        result = await client.upload_file(object_key="test.txt", data=b"Test")

        read_url = await client.get_read_url("test.txt")
        assert read_url == result["url"]


class TestDeleteFile:
    """Test suite for file deletion operations."""

    @pytest.mark.asyncio
    async def test_delete_existing_file(self, tmp_path: Path):
        """Test deleting an existing file."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        await client.upload_file(object_key="test.txt", data=b"Test")

        result = await client.delete_file("test.txt")
        assert result is True

        file_path = client.storage_path / "test.txt"
        assert not file_path.exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file(self, tmp_path: Path):
        """Test deleting a non-existent file."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        result = await client.delete_file("nonexistent.txt")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_multiple_files(self, tmp_path: Path):
        """Test deleting multiple files."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        files = ["file1.txt", "file2.txt", "file3.txt"]
        for key in files:
            await client.upload_file(object_key=key, data=b"Test")

        for key in files:
            result = await client.delete_file(key)
            assert result is True

        for key in files:
            file_path = client.storage_path / key
            assert not file_path.exists()


class TestGetReadURL:
    """Test suite for get_read_url behavior."""

    @pytest.mark.asyncio
    async def test_get_read_url_existing_file(self, tmp_path: Path):
        """Test getting read URL for existing file."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        await client.upload_file(object_key="test.txt", data=b"Test")

        url = await client.get_read_url("test.txt")
        assert url == "/storage/test.txt"

    @pytest.mark.asyncio
    async def test_get_read_url_missing_file_raises(self, tmp_path: Path):
        """Test that get_read_url raises FileNotFoundError for missing files."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))

        with pytest.raises(FileNotFoundError, match="Storage file not found"):
            await client.get_read_url("nonexistent.txt")

    @pytest.mark.asyncio
    async def test_get_read_url_after_delete_raises(self, tmp_path: Path):
        """Test that get_read_url raises after file is deleted."""
        client = LocalStorageClient(storage_path=str(tmp_path / "storage"))
        await client.upload_file(object_key="test.txt", data=b"Test")
        await client.delete_file("test.txt")

        with pytest.raises(FileNotFoundError):
            await client.get_read_url("test.txt")


class TestContextManager:
    """Test suite for async context manager support."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self, tmp_path: Path):
        """Test using as async context manager."""
        async with LocalStorageClient(storage_path=str(tmp_path / "storage")) as client:
            result = await client.upload_file(object_key="test.txt", data=b"Test")
            assert result["object_key"] == "test.txt"
