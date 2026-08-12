"""Integration tests for SQLiteSQLAlchemyDataLayer."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from chainlit.types import Pagination, ThreadFilter

from aria.db.layer import SQLiteSQLAlchemyDataLayer, _to_local_timestamp_string


class TestThreadOperations:
    """Test suite for thread operations."""

    @pytest.mark.asyncio
    async def test_update_thread_with_tags(
        self, data_layer: SQLiteSQLAlchemyDataLayer, raw_db_query: Callable
    ):
        """Test updating thread with tags list."""
        thread_id = str(uuid.uuid4())
        tags = ["important", "bug", "feature"]

        # Create/update thread with tags
        await data_layer.update_thread(thread_id=thread_id, tags=tags)

        # Verify tags stored as JSON string in database
        result = await raw_db_query(
            "SELECT tags FROM threads WHERE id = :id", {"id": thread_id}
        )
        assert len(result) == 1
        stored_tags = result[0]["tags"]
        assert stored_tags == '["important", "bug", "feature"]'

        # Verify tags returned as list when retrieved
        thread = await data_layer.get_thread(thread_id)
        assert thread is not None
        assert thread["tags"] == tags

    @pytest.mark.asyncio
    async def test_update_thread_with_empty_tags(
        self, data_layer: SQLiteSQLAlchemyDataLayer
    ):
        """Test updating thread with empty tags list."""
        thread_id = str(uuid.uuid4())

        await data_layer.update_thread(thread_id=thread_id, tags=[])

        thread = await data_layer.get_thread(thread_id)
        assert thread is not None
        assert thread["tags"] == []

    @pytest.mark.asyncio
    async def test_update_thread_tags_with_special_characters(
        self, data_layer: SQLiteSQLAlchemyDataLayer
    ):
        """Test thread tags with special characters."""
        thread_id = str(uuid.uuid4())
        tags = ["tag with spaces", 'tag"with"quotes', "日本語", "emoji🚀"]

        await data_layer.update_thread(thread_id=thread_id, tags=tags)

        thread = await data_layer.get_thread(thread_id)
        assert thread is not None
        assert thread["tags"] == tags

    @pytest.mark.asyncio
    async def test_update_thread_with_metadata(
        self, data_layer: SQLiteSQLAlchemyDataLayer
    ):
        """Test updating thread with metadata."""
        thread_id = str(uuid.uuid4())
        metadata = {"priority": "high", "assignee": "john"}

        await data_layer.update_thread(thread_id=thread_id, metadata=metadata)

        thread = await data_layer.get_thread(thread_id)
        assert thread is not None
        assert thread["metadata"] == metadata

    @pytest.mark.asyncio
    async def test_update_thread_metadata_merge(
        self, data_layer: SQLiteSQLAlchemyDataLayer
    ):
        """Test thread metadata merging behavior."""
        thread_id = str(uuid.uuid4())

        # Create thread with initial metadata
        await data_layer.update_thread(
            thread_id, metadata={"key1": "value1", "shared": "original"}
        )

        # Update with new metadata
        await data_layer.update_thread(
            thread_id, metadata={"key2": "value2", "shared": "updated"}
        )

        # Verify metadata is merged
        thread = await data_layer.get_thread(thread_id)
        assert thread is not None
        assert thread["metadata"] is not None
        assert thread["metadata"]["key1"] == "value1"
        assert thread["metadata"]["key2"] == "value2"
        assert thread["metadata"]["shared"] == "updated"

    @pytest.mark.asyncio
    async def test_update_thread_with_tags_and_metadata(
        self, data_layer: SQLiteSQLAlchemyDataLayer
    ):
        """Test updating thread with both tags and metadata."""
        thread_id = str(uuid.uuid4())
        tags = ["tag1", "tag2"]
        metadata = {"key": "value"}

        await data_layer.update_thread(
            thread_id=thread_id, tags=tags, metadata=metadata
        )

        thread = await data_layer.get_thread(thread_id)
        assert thread is not None
        assert thread["tags"] == tags
        assert thread["metadata"] == metadata


class TestStepOperations:
    """Test suite for step operations."""


class TestThreadRetrieval:
    """Test suite for thread retrieval operations."""

    @pytest.mark.asyncio
    async def test_get_all_user_threads_deserialization(
        self, data_layer: SQLiteSQLAlchemyDataLayer, create_user: Callable
    ):
        """Test get_all_user_threads deserializes all JSON fields."""
        # Create user
        user = await create_user()
        user_id = user["id"]

        # Create thread with JSON fields
        thread_id = str(uuid.uuid4())
        await data_layer.update_thread(
            thread_id=thread_id,
            user_id=user_id,
            tags=["tag1", "tag2"],
            metadata={"key": "value"},
        )

        # Retrieve threads
        threads = await data_layer.get_all_user_threads(user_id=user_id)
        assert threads is not None
        assert len(threads) > 0

        thread = threads[0]
        # Verify JSON fields are Python objects, not strings
        assert isinstance(thread["tags"], list)
        assert thread["tags"] == ["tag1", "tag2"]
        assert isinstance(thread["metadata"], dict)
        assert thread["metadata"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_get_all_user_threads_with_malformed_json(
        self, data_layer: SQLiteSQLAlchemyDataLayer, raw_db_query: Callable
    ):
        """Test graceful handling of malformed JSON in database."""
        thread_id = str(uuid.uuid4())

        # Insert thread with malformed JSON directly
        await raw_db_query(
            """INSERT INTO threads (id, tags, metadata, "createdAt")
               VALUES (:id, :tags, :metadata, :created_at)""",
            {
                "id": thread_id,
                "tags": "not valid json",
                "metadata": "also not valid",
                "created_at": "2024-01-01T00:00:00Z",
            },
        )

        # Retrieve threads - should not crash
        threads = await data_layer.get_all_user_threads(thread_id=thread_id)
        assert threads is not None
        assert len(threads) > 0

        thread = threads[0]
        # Verify returns default values instead of crashing
        assert thread["tags"] == []
        assert thread["metadata"] == {}

    @pytest.mark.asyncio
    async def test_get_thread_deserialization(
        self, data_layer: SQLiteSQLAlchemyDataLayer
    ):
        """Test get_thread returns deserialized data."""
        thread_id = str(uuid.uuid4())
        tags = ["test-tag"]
        metadata = {"test-key": "test-value"}

        await data_layer.update_thread(
            thread_id=thread_id, tags=tags, metadata=metadata
        )

        thread = await data_layer.get_thread(thread_id)
        assert thread is not None
        assert isinstance(thread["tags"], list)
        assert thread["tags"] == tags
        assert isinstance(thread["metadata"], dict)
        assert thread["metadata"] == metadata

    @pytest.mark.asyncio
    async def test_get_all_user_threads_normalizes_created_at_for_sidebar_grouping(
        self,
        data_layer: SQLiteSQLAlchemyDataLayer,
        create_user: Callable,
        raw_db_query: Callable,
    ):
        """Returned thread timestamps should include a local offset for frontend day bucketing."""
        user = await create_user()
        user_id = user["id"]
        thread_id = str(uuid.uuid4())
        created_at = "2026-04-01T23:58:48.216144Z"

        await data_layer.update_thread(
            thread_id=thread_id,
            user_id=user_id,
            name="elon's companies",
        )
        await raw_db_query(
            'UPDATE threads SET "createdAt" = :created_at WHERE id = :id',
            {"created_at": created_at, "id": thread_id},
        )

        threads = await data_layer.get_all_user_threads(user_id=user_id)
        assert threads is not None
        thread = next(t for t in threads if t["id"] == thread_id)

        expected = _to_local_timestamp_string(created_at)
        assert thread["createdAt"] == expected
        assert thread["createdAt"] != created_at
        parsed = datetime.fromisoformat(thread["createdAt"])
        assert parsed.tzinfo is not None

    @pytest.mark.asyncio
    async def test_list_threads_normalizes_created_at_for_sidebar_grouping(
        self,
        data_layer: SQLiteSQLAlchemyDataLayer,
        create_user: Callable,
        raw_db_query: Callable,
    ):
        """Pagination path should return the same normalized thread timestamps."""
        user = await create_user()
        user_id = user["id"]
        thread_id = str(uuid.uuid4())
        created_at = "2026-04-01T23:58:48.216144Z"

        await data_layer.update_thread(
            thread_id=thread_id,
            user_id=user_id,
            name="late night thread",
        )
        await raw_db_query(
            'UPDATE threads SET "createdAt" = :created_at WHERE id = :id',
            {"created_at": created_at, "id": thread_id},
        )

        response = await data_layer.list_threads(
            Pagination(first=20), ThreadFilter(userId=user_id)
        )
        thread = next(t for t in response.data if t["id"] == thread_id)

        assert thread["createdAt"] == _to_local_timestamp_string(created_at)


class TestTimestampNormalizationHelpers:
    def test_to_local_timestamp_string_preserves_invalid_values(self):
        """Invalid values should pass through unchanged."""
        assert _to_local_timestamp_string(None) is None
        assert _to_local_timestamp_string("not-a-timestamp") == "not-a-timestamp"

    def test_to_local_timestamp_string_returns_timezone_aware_isoformat(self):
        """UTC values should be converted to explicit local-offset ISO strings."""
        original = "2026-04-01T23:58:48.216144Z"
        normalized = _to_local_timestamp_string(original)

        assert normalized != original
        parsed = datetime.fromisoformat(normalized)
        assert parsed.tzinfo is not None
        assert parsed.astimezone(UTC) == datetime.fromisoformat(
            original.replace("Z", "+00:00")
        )


class TestRoundTrip:
    """Test suite for round-trip data integrity."""

    @pytest.mark.asyncio
    async def test_metadata_round_trip_nested(
        self, data_layer: SQLiteSQLAlchemyDataLayer
    ):
        """Test nested metadata round-trip."""
        thread_id = str(uuid.uuid4())
        original_metadata = {
            "level1": {"level2": {"level3": "value"}, "list": [1, 2, 3]},
            "boolean": True,
            "number": 42.5,
        }

        await data_layer.update_thread(thread_id=thread_id, metadata=original_metadata)

        thread = await data_layer.get_thread(thread_id)
        assert thread is not None
        # Compare each key individually to handle potential ordering/merging issues
        assert thread["metadata"] is not None
        assert thread["metadata"]["level1"] == original_metadata["level1"]
        assert thread["metadata"]["boolean"] == original_metadata["boolean"]
        assert thread["metadata"]["number"] == original_metadata["number"]
