"""Tests for standalone scratchpad tool."""

import json

import pytest

from aria.tools.scratchpad import scratchpad


@pytest.fixture(autouse=True)
def test_db(test_tools_db):
    """Create a temporary database for testing.

    Depends on the shared ``test_tools_db`` fixture (defined in root
    ``conftest.py``) which handles temp-file creation and singleton
    resets.
    """
    yield


def _result(call_result: str) -> dict:
    """Parse tool JSON-string response into a dict for assertions."""
    return json.loads(call_result)


class TestScratchpadStandalone:
    """Test that scratchpad works without any reasoning session."""

    def test_set_and_get(self):
        """Test basic set and get operations."""
        result = _result(
            scratchpad(
                "Store a value",
                key="test_key",
                value="test_value",
                operation="set",
                agent_id="test_agent",
            )
        )
        assert result["status"] == "success"
        assert result["data"]["tool"] == "set"
        assert result["data"]["key"] == "test_key"
        assert result["data"]["value"] == "test_value"

        result = _result(
            scratchpad(
                "Retrieve a value",
                key="test_key",
                operation="get",
                agent_id="test_agent",
            )
        )
        assert result["status"] == "success"
        assert result["data"]["tool"] == "get"
        assert result["data"]["value"] == "test_value"

    def test_get_nonexistent_key(self):
        """Test getting a key that doesn't exist."""
        result = _result(
            scratchpad(
                "Get missing",
                key="nonexistent",
                operation="get",
                agent_id="test_agent",
            )
        )
        assert result["status"] == "error"
        assert result["error"]["code"] == "KEY_NOT_FOUND"

    def test_set_requires_value(self):
        """Test that set operation requires a value."""
        result = _result(
            scratchpad(
                "Set without value",
                key="test_key",
                operation="set",
                agent_id="test_agent",
            )
        )
        assert result["status"] == "error"
        assert result["error"]["code"] == "VALUE_REQUIRED"

    def test_set_overwrites_existing(self):
        """Test that setting an existing key overwrites it."""
        scratchpad(
            "Store first",
            key="overwrite_key",
            value="first",
            operation="set",
            agent_id="test_agent",
        )
        scratchpad(
            "Store second",
            key="overwrite_key",
            value="second",
            operation="set",
            agent_id="test_agent",
        )
        result = _result(
            scratchpad(
                "Get overwritten",
                key="overwrite_key",
                operation="get",
                agent_id="test_agent",
            )
        )
        assert result["data"]["value"] == "second"

    def test_delete_key(self):
        """Test deleting a key."""
        scratchpad(
            "Store",
            key="delete_me",
            value="bye",
            operation="set",
            agent_id="test_agent",
        )
        result = _result(
            scratchpad(
                "Delete",
                key="delete_me",
                operation="delete",
                agent_id="test_agent",
            )
        )
        assert result["status"] == "success"
        assert result["data"]["tool"] == "delete"

        # Verify it's gone
        result = _result(
            scratchpad(
                "Get deleted",
                key="delete_me",
                operation="get",
                agent_id="test_agent",
            )
        )
        assert result["status"] == "error"
        assert result["error"]["code"] == "KEY_NOT_FOUND"

    def test_delete_nonexistent_key(self):
        """Test deleting a key that doesn't exist."""
        result = _result(
            scratchpad(
                "Delete missing",
                key="ghost",
                operation="delete",
                agent_id="test_agent",
            )
        )
        assert result["status"] == "error"
        assert result["error"]["code"] == "KEY_NOT_FOUND"

    def test_delete_all(self):
        """Test clearing all scratchpad items."""
        scratchpad(
            "Store 1",
            key="k1",
            value="v1",
            operation="set",
            agent_id="test_agent",
        )
        scratchpad(
            "Store 2",
            key="k2",
            value="v2",
            operation="set",
            agent_id="test_agent",
        )
        result = _result(
            scratchpad(
                "Clear all",
                key="all",
                operation="delete",
                agent_id="test_agent",
            )
        )
        assert result["status"] == "success"
        assert result["data"]["deleted_count"] == 2

        # Verify all gone
        result = _result(
            scratchpad(
                "List after clear",
                key="",
                operation="list",
                agent_id="test_agent",
            )
        )
        assert result["data"]["items"] == []

    def test_list_items(self):
        """Test listing all scratchpad items."""
        scratchpad(
            "Store 1",
            key="list_k1",
            value="v1",
            operation="set",
            agent_id="test_agent",
        )
        scratchpad(
            "Store 2",
            key="list_k2",
            value="v2",
            operation="set",
            agent_id="test_agent",
        )
        result = _result(
            scratchpad(
                "List all",
                key="",
                operation="list",
                agent_id="test_agent",
            )
        )
        assert result["status"] == "success"
        assert result["data"]["tool"] == "list"
        items = result["data"]["items"]
        assert len(items) == 2
        keys = {item["key"] for item in items}
        assert keys == {"list_k1", "list_k2"}

    def test_list_empty(self):
        """Test listing when no items exist."""
        result = _result(
            scratchpad(
                "List empty",
                key="",
                operation="list",
                agent_id="test_agent",
            )
        )
        assert result["status"] == "success"
        assert result["data"]["items"] == []

    def test_unsupported_operation(self):
        """Test unsupported operation returns error."""
        result = _result(
            scratchpad(
                "Bad op",
                key="k",
                operation="explode",
                agent_id="test_agent",
            )
        )
        assert result["status"] == "error"
        assert result["error"]["code"] == "UNSUPPORTED_OPERATION"

    def test_multi_agent_isolation(self):
        """Test that different agents have isolated scratchpads."""
        scratchpad(
            "Agent 1 store",
            key="shared_key",
            value="agent1_value",
            operation="set",
            agent_id="agent_1",
        )
        scratchpad(
            "Agent 2 store",
            key="shared_key",
            value="agent2_value",
            operation="set",
            agent_id="agent_2",
        )

        result1 = _result(
            scratchpad(
                "Agent 1 get",
                key="shared_key",
                operation="get",
                agent_id="agent_1",
            )
        )
        result2 = _result(
            scratchpad(
                "Agent 2 get",
                key="shared_key",
                operation="get",
                agent_id="agent_2",
            )
        )

        assert result1["data"]["value"] == "agent1_value"
        assert result2["data"]["value"] == "agent2_value"

    def test_no_reasoning_session_needed(self):
        """Verify scratchpad does NOT create reasoning sessions.

        This is the key decoupling test: the old implementation created
        a ReasoningSession under the hood. The new one should not.
        """
        from aria.tools.reasoning import registry

        # Ensure no active reasoning session
        assert registry.get_active_session_id("decoupled_agent") is None

        # Use scratchpad
        scratchpad(
            "Store without reasoning",
            key="decoupled_key",
            value="decoupled_value",
            operation="set",
            agent_id="decoupled_agent",
        )

        # Verify no reasoning session was created
        assert registry.get_active_session_id("decoupled_agent") is None

        # But the value is still retrievable
        result = _result(
            scratchpad(
                "Get without reasoning",
                key="decoupled_key",
                operation="get",
                agent_id="decoupled_agent",
            )
        )
        assert result["data"]["value"] == "decoupled_value"
