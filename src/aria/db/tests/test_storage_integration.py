"""Integration tests for SQLiteSQLAlchemyDataLayer with LocalStorageClient."""

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, event

from aria.db.layer import SQLiteSQLAlchemyDataLayer
from aria.db.local_storage_client import LocalStorageClient
from aria.db.models import Base


@pytest_asyncio.fixture
async def data_layer_with_storage(tmp_path: Path):
    """Create data layer with local storage client.

    Args:
        tmp_path: Temporary directory for test database and storage

    Yields:
        Tuple of (data_layer, storage_client, storage_path)
    """
    db_path = tmp_path / "test.db"
    storage_path = tmp_path / "storage"

    # Create sync engine to initialize schema
    sync_url = f"sqlite:///{db_path}"
    sync_engine = create_engine(sync_url)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    # Create storage client
    storage_client = LocalStorageClient(storage_path=str(storage_path))

    # Create data layer with storage
    async_url = f"sqlite+aiosqlite:///{db_path}"
    layer = SQLiteSQLAlchemyDataLayer(
        conninfo=async_url, storage_provider=storage_client, show_logger=False
    )

    # Enable foreign key constraints
    @event.listens_for(layer.engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    yield layer, storage_client, storage_path

    await layer.engine.dispose()


class TestStorageIntegration:
    """Test suite for data layer integration with storage client."""

    @pytest.mark.asyncio
    async def test_data_layer_has_storage_provider(self, data_layer_with_storage):
        """Test data layer is initialized with storage provider."""
        layer, storage_client, _ = data_layer_with_storage

        assert layer.storage_provider is not None
        assert isinstance(layer.storage_provider, LocalStorageClient)
        assert layer.storage_provider is storage_client

    @pytest.mark.asyncio
    async def test_storage_directory_created(self, data_layer_with_storage):
        """Test storage directory is created."""
        _, _, storage_path = data_layer_with_storage

        assert storage_path.exists()
        assert storage_path.is_dir()

    @pytest.mark.asyncio
    async def test_upload_element_file(self, data_layer_with_storage):
        """Test uploading a file through storage client."""
        _, storage_client, storage_path = data_layer_with_storage

        # Upload a file
        object_key = "test-element.png"
        data = b"fake image data"

        result = await storage_client.upload_file(
            object_key=object_key, data=data, mime="image/png"
        )

        assert result["object_key"] == object_key
        assert "url" in result

        # Verify file exists in storage
        file_path = storage_path / object_key
        assert file_path.exists()
        assert file_path.read_bytes() == data

    @pytest.mark.asyncio
    async def test_delete_element_file(self, data_layer_with_storage):
        """Test deleting a file through storage client."""
        _, storage_client, storage_path = data_layer_with_storage

        # Upload a file
        object_key = "test-element.png"
        await storage_client.upload_file(
            object_key=object_key, data=b"test", mime="image/png"
        )

        # Verify file exists
        file_path = storage_path / object_key
        assert file_path.exists()

        # Delete the file
        result = await storage_client.delete_file(object_key)

        assert result is True
        assert not file_path.exists()

    @pytest.mark.asyncio
    async def test_get_read_url_for_element(self, data_layer_with_storage):
        """Test getting read URL for an element file."""
        _, storage_client, _ = data_layer_with_storage

        # Upload a file
        object_key = "test-element.png"
        await storage_client.upload_file(
            object_key=object_key, data=b"test", mime="image/png"
        )

        # Get read URL
        url = await storage_client.get_read_url(object_key)

        assert object_key in url
        assert url.startswith("/storage/")

    @pytest.mark.asyncio
    async def test_multiple_elements_storage(self, data_layer_with_storage):
        """Test storing multiple element files."""
        _, storage_client, storage_path = data_layer_with_storage

        # Upload multiple files
        files = {
            "image1.png": b"image1 data",
            "image2.jpg": b"image2 data",
            "document.pdf": b"pdf data",
        }

        for object_key, data in files.items():
            result = await storage_client.upload_file(object_key=object_key, data=data)
            assert result["object_key"] == object_key

        # Verify all files exist
        for object_key in files.keys():
            file_path = storage_path / object_key
            assert file_path.exists()

    @pytest.mark.asyncio
    async def test_storage_with_subdirectories(self, data_layer_with_storage):
        """Test storing files in subdirectories."""
        _, storage_client, storage_path = data_layer_with_storage

        # Upload files with subdirectories
        object_key = "threads/thread-123/elements/image.png"
        data = b"image data"

        result = await storage_client.upload_file(
            object_key=object_key, data=data, mime="image/png"
        )

        assert result["object_key"] == object_key

        # Verify directory structure created
        file_path = storage_path / object_key
        assert file_path.exists()
        assert file_path.parent.name == "elements"
        assert file_path.parent.parent.name == "thread-123"

    @pytest.mark.asyncio
    async def test_storage_cleanup_on_delete(self, data_layer_with_storage):
        """Test storage cleanup when deleting elements."""
        layer, storage_client, storage_path = data_layer_with_storage

        # Create a thread
        thread_id = str(uuid.uuid4())
        await layer.update_thread(thread_id=thread_id, name="Test Thread")

        # Upload a file for an element
        object_key = f"threads/{thread_id}/element.png"
        await storage_client.upload_file(
            object_key=object_key, data=b"test", mime="image/png"
        )

        # Verify file exists
        file_path = storage_path / object_key
        assert file_path.exists()

        # Delete the file
        result = await storage_client.delete_file(object_key)
        assert result is True
        assert not file_path.exists()

    @pytest.mark.asyncio
    async def test_storage_overwrite_behavior(self, data_layer_with_storage):
        """Test storage overwrite behavior."""
        _, storage_client, storage_path = data_layer_with_storage

        object_key = "test.txt"

        # Upload original
        await storage_client.upload_file(
            object_key=object_key, data=b"original", overwrite=True
        )

        # Upload updated (overwrite=True)
        result = await storage_client.upload_file(
            object_key=object_key, data=b"updated", overwrite=True
        )

        assert result["object_key"] == object_key

        # Verify file was overwritten
        file_path = storage_path / object_key
        assert file_path.read_bytes() == b"updated"

    @pytest.mark.asyncio
    async def test_storage_binary_and_text_files(self, data_layer_with_storage):
        """Test storing both binary and text files."""
        _, storage_client, storage_path = data_layer_with_storage

        # Upload binary file
        binary_key = "image.png"
        binary_data = bytes(range(256))
        await storage_client.upload_file(
            object_key=binary_key, data=binary_data, mime="image/png"
        )

        # Upload text file
        text_key = "document.txt"
        text_data = "Hello, World! 🌍"
        await storage_client.upload_file(
            object_key=text_key, data=text_data, mime="text/plain"
        )

        # Verify both files exist and have correct content
        assert (storage_path / binary_key).read_bytes() == binary_data
        assert (storage_path / text_key).read_text() == text_data

    @pytest.mark.asyncio
    async def test_storage_client_close(self, data_layer_with_storage):
        """Test closing storage client."""
        _, storage_client, _ = data_layer_with_storage

        # Should not raise any errors
        await storage_client.close()

        # Should still be able to use after close (no-op for local storage)
        result = await storage_client.upload_file(object_key="test.txt", data=b"test")
        assert result["object_key"] == "test.txt"


class TestElementPersistence:
    """End-to-end element persistence + storage cleanup (regression for C1)."""

    @staticmethod
    async def _make_user(layer):
        from chainlit.user import User

        persisted = await layer.create_user(
            User(identifier=f"u-{uuid.uuid4()}", metadata={})
        )
        assert persisted is not None
        return persisted

    @pytest.mark.asyncio
    async def test_create_element_persists_objectkey_and_file(
        self, data_layer_with_storage, tmp_path
    ):
        """C1: objectKey must be persisted so the file is reclaimable on delete."""
        from chainlit.context import init_http_context
        from chainlit.element import Image

        layer, storage_client, storage_path = data_layer_with_storage
        user = await self._make_user(layer)
        thread_id = str(uuid.uuid4())
        init_http_context(thread_id=thread_id, user=user)
        await layer.update_thread(thread_id=thread_id, user_id=user.id)

        image_bytes = b"fake-png-bytes"
        src = tmp_path / "src.png"
        src.write_bytes(image_bytes)
        element = Image(
            name="plot.png",
            path=str(src),
            display="inline",
            thread_id=thread_id,
            for_id=str(uuid.uuid4()),
        )

        await layer.create_element(element)

        from sqlalchemy import create_engine, text

        engine = create_engine(
            layer.engine.url.render_as_string().replace("+aiosqlite", "")
        )
        with engine.connect() as conn:
            row = conn.execute(
                text('SELECT "objectKey", url FROM elements WHERE id = :id'),
                {"id": element.id},
            ).fetchone()
        assert row is not None
        object_key = row[0]
        assert object_key is not None, "objectKey must not be NULL (C1 regression)"
        assert object_key == f"{user.id}/{element.id}/plot.png"

        file_on_disk = storage_path / object_key
        assert file_on_disk.read_bytes() == image_bytes

    @pytest.mark.asyncio
    async def test_delete_thread_removes_element_files(
        self, data_layer_with_storage, tmp_path
    ):
        """delete_thread must remove stored element files (orphan-leak regression)."""
        from chainlit.context import init_http_context
        from chainlit.element import Image

        layer, storage_client, storage_path = data_layer_with_storage
        user = await self._make_user(layer)
        thread_id = str(uuid.uuid4())
        init_http_context(thread_id=thread_id, user=user)
        await layer.update_thread(thread_id=thread_id, user_id=user.id)

        src = tmp_path / "src.png"
        src.write_bytes(b"img")
        element = Image(
            name="plot.png",
            path=str(src),
            display="inline",
            thread_id=thread_id,
            for_id=str(uuid.uuid4()),
        )
        await layer.create_element(element)

        from sqlalchemy import create_engine, text

        engine = create_engine(
            layer.engine.url.render_as_string().replace("+aiosqlite", "")
        )
        with engine.connect() as conn:
            object_key = conn.execute(
                text('SELECT "objectKey" FROM elements WHERE id = :id'),
                {"id": element.id},
            ).scalar()
        file_on_disk = storage_path / object_key
        assert file_on_disk.exists()

        await layer.delete_thread(thread_id)

        assert not file_on_disk.exists(), "delete_thread leaked the stored file"

    @pytest.mark.asyncio
    async def test_url_element_keeps_remote_url_no_local_file(
        self, data_layer_with_storage
    ):
        """L1: URL-backed elements keep the remote URL; nothing is mirrored."""
        from chainlit.context import init_http_context
        from chainlit.element import Image

        layer, storage_client, storage_path = data_layer_with_storage
        user = await self._make_user(layer)
        thread_id = str(uuid.uuid4())
        init_http_context(thread_id=thread_id, user=user)
        await layer.update_thread(thread_id=thread_id, user_id=user.id)

        remote = "https://example.com/assets/cat.png"
        element = Image(
            name="cat.png",
            url=remote,
            display="inline",
            thread_id=thread_id,
            for_id=str(uuid.uuid4()),
        )

        await layer.create_element(element)

        from sqlalchemy import create_engine, text

        engine = create_engine(
            layer.engine.url.render_as_string().replace("+aiosqlite", "")
        )
        with engine.connect() as conn:
            row = conn.execute(
                text('SELECT url, "objectKey" FROM elements WHERE id = :id'),
                {"id": element.id},
            ).fetchone()
        assert row is not None
        assert row[0] == remote
        assert row[1] is None
        # No file written under the user dir for this element.
        user_dir = storage_path / user.id
        assert not user_dir.exists() or not any(user_dir.rglob("*"))
