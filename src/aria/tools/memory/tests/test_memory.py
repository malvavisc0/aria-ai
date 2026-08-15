"""Tests for memory store tool."""

import json

import pytest

from aria.tools.execution_context import (
    ExecutionContext,
    reset_execution_context,
    set_execution_context,
)
from aria.tools.memory import memory
from aria.tools.memory.database import MemoryDatabase


@pytest.fixture(autouse=True)
def test_db(test_tools_db):
    """Create a temporary memory database for testing.

    Depends on the shared ``test_tools_db`` fixture (defined in root
    ``conftest.py``) which handles temp-file creation and singleton
    resets.
    """
    test_mdb = MemoryDatabase()

    yield test_mdb


class TestMemoryStore:
    """Test suite for memory store tool."""

    def test_store_and_recall(self, test_db):
        """Test storing and recalling a memory entry."""
        result = memory(
            "Store user preference",
            action="store",
            key="user_language",
            value="Python",
        )
        data = json.loads(result)
        assert data["data"]["action"] == "store"
        assert data["data"]["key"] == "user_language"

        # Recall it
        result = memory(
            "Recall user preference",
            action="recall",
            key="user_language",
        )
        data = json.loads(result)
        assert data["data"]["found"] is True
        assert data["data"]["value"] == "Python"

    def test_worker_uses_worker_memory_namespace(self, test_db):
        token = set_execution_context(
            ExecutionContext(role="worker", worker_id="worker_test")
        )
        try:
            result = memory(
                "Store worker fact", action="store", key="fact", value="isolated"
            )
        finally:
            reset_execution_context(token)
        assert json.loads(result)["data"]["error"]["code"] == "WORKER_MEMORY_FORBIDDEN"

    def test_recall_missing_key(self, test_db):
        """Test recalling a non-existent key."""
        result = memory(
            "Recall missing key",
            action="recall",
            key="nonexistent_key",
        )
        data = json.loads(result)
        assert data["data"]["found"] is False

    def test_store_with_tags(self, test_db):
        """Test storing with tags."""
        result = memory(
            "Store with tags",
            action="store",
            key="project_name",
            value="Aria",
            tags=["project", "config"],
        )
        data = json.loads(result)
        assert data["data"]["action"] == "store"

        # Recall to verify tags
        result = memory(
            "Recall with tags",
            action="recall",
            key="project_name",
        )
        data = json.loads(result)
        assert data["data"]["tags"] == ["project", "config"]

    def test_search_entries(self, test_db):
        """Test searching memory entries."""
        memory("Store entry 1", action="store", key="api_key", value="abc123")
        memory(
            "Store entry 2",
            action="store",
            key="api_url",
            value="https://example.com",
        )

        result = memory(
            "Search for api",
            action="search",
            query="api",
        )
        data = json.loads(result)
        assert data["data"]["results_count"] == 2

    def test_list_entries(self, test_db):
        """Test listing all entries."""
        memory("Store 1", action="store", key="key1", value="val1")
        memory("Store 2", action="store", key="key2", value="val2")

        result = memory("List all", action="list")
        data = json.loads(result)
        assert data["data"]["count"] == 2

    def test_list_by_tag(self, test_db):
        """Test listing entries filtered by tag."""
        memory(
            "Store tagged",
            action="store",
            key="k1",
            value="v1",
            tags=["important"],
        )
        memory("Store untagged", action="store", key="k2", value="v2")

        result = memory("List by tag", action="list", tags=["important"])
        data = json.loads(result)
        assert data["data"]["count"] == 1

    def test_update_entry(self, test_db):
        """Test updating an existing entry."""
        store_result = memory(
            "Store for update", action="store", key="updatable", value="old"
        )
        entry_id = json.loads(store_result)["data"]["entry_id"]

        result = memory(
            "Update entry",
            action="update",
            entry_id=entry_id,
            value="new",
        )
        data = json.loads(result)
        assert data["data"]["action"] == "update"

        # Verify updated value
        result = memory("Recall updated", action="recall", key="updatable")
        data = json.loads(result)
        assert data["data"]["value"] == "new"

    def test_delete_entry(self, test_db):
        """Test deleting an entry."""
        store_result = memory(
            "Store for delete", action="store", key="deletable", value="gone"
        )
        entry_id = json.loads(store_result)["data"]["entry_id"]

        result = memory(
            "Delete entry",
            action="delete",
            entry_id=entry_id,
        )
        data = json.loads(result)
        assert data["data"]["action"] == "delete"

        # Verify it's gone
        result = memory("Recall deleted", action="recall", key="deletable")
        data = json.loads(result)
        assert data["data"]["found"] is False

    def test_store_missing_key(self, test_db):
        """Test store without key returns error."""
        result = memory("Bad store", action="store", value="no key")
        data = json.loads(result)
        assert "error" in data["data"]

    def test_store_missing_value(self, test_db):
        """Test store without value returns error."""
        result = memory("Bad store", action="store", key="no_value")
        data = json.loads(result)
        assert "error" in data["data"]

    def test_invalid_action(self, test_db):
        """Test invalid action returns error."""
        result = memory("Bad action", action="explode")
        data = json.loads(result)
        assert "error" in data["data"]

    def test_multi_agent_isolation(self, test_db):
        """Test that different agents have isolated memory."""
        memory(
            "Agent 1 store",
            action="store",
            key="secret",
            value="agent1_data",
            agent_id="agent_1",
        )
        memory(
            "Agent 2 store",
            action="store",
            key="secret",
            value="agent2_data",
            agent_id="agent_2",
        )

        r1 = memory("Agent 1 recall", action="recall", key="secret", agent_id="agent_1")
        r2 = memory("Agent 2 recall", action="recall", key="secret", agent_id="agent_2")

        assert json.loads(r1)["data"]["value"] == "agent1_data"
        assert json.loads(r2)["data"]["value"] == "agent2_data"
