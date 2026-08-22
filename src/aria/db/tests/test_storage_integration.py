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
