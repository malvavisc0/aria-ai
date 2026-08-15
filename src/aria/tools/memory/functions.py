"""Memory store tool for persistent key-value storage."""

import uuid

from aria.tools import Reason, err, ok
from aria.tools.decorators import log_tool_call
from aria.tools.execution_context import get_execution_context

from .database import MemoryDatabase, get_database

_TOOL = "memory"
_DEFAULT_AGENT_ID = "aria"


@log_tool_call
def memory(
    reason: Reason,
    action: str,
    key: str | None = None,
    value: str | None = None,
    tags: list[str] | None = None,
    entry_id: str | None = None,
    query: str | None = None,
    max_results: int = 10,
    agent_id: str = _DEFAULT_AGENT_ID,
) -> str:
    """Persistent key-value memory store across conversations.

    When to use:
        - Use this to remember facts, preferences, or context that must
          persist across conversations (e.g., user's preferred language,
          project naming conventions).
        - Use this to store learned information for future recall.
        - Do NOT use this for ephemeral working memory within a task —
          use `scratchpad` instead.
        - Do NOT use this for structured execution plans — use `plan`.

    Why:
        Unlike scratchpad (ephemeral working memory), memory entries
        survive server restarts and conversation boundaries. This is the
        tool for long-term memory.

    Actions:
        - "store": Save a new entry (requires key and value).
        - "recall": Retrieve an entry by key (requires key).
        - "search": Search entries by query string (requires query).
        - "list": List all entries (optional tag filter).
        - "update": Update an existing entry (requires entry_id and value).
        - "delete": Remove an entry (requires entry_id).

    Args:
        reason: Required. Brief explanation of why you are calling this tool (e.g. "Store user's preferred language").
        action: One of: store, recall, search, list, update, delete.
        key: Unique key for the entry (required for store/recall).
        value: Value to store (required for store/update).
        tags: Optional list of tags for categorization.
        entry_id: UUID of entry to update/delete.
        query: Search query for text search.
        max_results: Maximum results for search/list (default: 10).
        agent_id: Agent identifier (auto-set, do not provide).

    Returns:
        JSON response with action-specific data.

    Important:
        - Data is persisted to SQLite and survives restarts.
        - Use tags to organize entries by category for easier search.
    """
    context = get_execution_context()
    if context.role == "worker":
        return err(
            tool=_TOOL,
            reason=reason,
            code="WORKER_MEMORY_FORBIDDEN",
            message="Worker agents do not have persistent conversation memory.",
        )
    action = action.lower().strip()
    db = get_database()

    if action == "store":
        return _action_store(db, reason, agent_id, key, value, tags)
    elif action == "recall":
        return _action_recall(db, reason, agent_id, key)
    elif action == "search":
        return _action_search(db, reason, agent_id, query, max_results)
    elif action == "list":
        return _action_list(db, reason, agent_id, tags, max_results)
    elif action == "update":
        return _action_update(db, reason, agent_id, entry_id, value)
    elif action == "delete":
        return _action_delete(db, reason, agent_id, entry_id)
    else:
        return err(
            tool=_TOOL,
            reason=reason,
            code="INVALID_ACTION",
            message=(
                f"Unknown action '{action}'. "
                "Valid: store, recall, search, list, update, delete"
            ),
            how_to_fix="Use one of: store, recall, search, list, update, delete",
        )


def _action_store(
    db: MemoryDatabase,
    reason: str,
    agent_id: str,
    key: str | None,
    value: str | None,
    tags: list[str] | None,
) -> str:
    """Store a new memory entry."""
    if not key:
        return err(
            tool=_TOOL,
            reason=reason,
            code="MISSING_KEY",
            message="Missing required 'key' parameter.",
            how_to_fix="Provide the 'key' parameter.",
        )
    if value is None:
        return err(
            tool=_TOOL,
            reason=reason,
            code="MISSING_VALUE",
            message="Missing required 'value' parameter.",
            how_to_fix="Provide the 'value' parameter.",
        )

    entry_id = uuid.uuid4().hex
    db.store(entry_id, agent_id, key, value, tags)

    return ok(
        tool=_TOOL,
        reason=reason,
        data={
            "action": "store",
            "entry_id": entry_id,
            "key": key,
            "message": "Memory entry stored successfully",
        },
    )


def _action_recall(
    db: MemoryDatabase,
    reason: str,
    agent_id: str,
    key: str | None,
) -> str:
    """Recall a memory entry by key."""
    if not key:
        return err(
            tool=_TOOL,
            reason=reason,
            code="MISSING_KEY",
            message="Missing required 'key' parameter.",
            how_to_fix="Provide the 'key' parameter.",
        )

    entry = db.recall(agent_id, key)
    if entry is None:
        return ok(
            tool=_TOOL,
            reason=reason,
            data={"action": "recall", "found": False, "key": key},
        )

    return ok(
        tool=_TOOL,
        reason=reason,
        data={"action": "recall", "found": True, **entry},
    )


def _action_search(
    db: MemoryDatabase,
    reason: str,
    agent_id: str,
    query: str | None,
    max_results: int,
) -> str:
    """Search memory entries."""
    if not query:
        return err(
            tool=_TOOL,
            reason=reason,
            code="MISSING_QUERY",
            message="Missing required 'query' parameter.",
            how_to_fix="Provide the 'query' parameter.",
        )

    results = db.search(agent_id, query, max_results)
    return ok(
        tool=_TOOL,
        reason=reason,
        data={
            "action": "search",
            "query": query,
            "results_count": len(results),
            "results": results,
        },
    )


def _action_list(
    db: MemoryDatabase,
    reason: str,
    agent_id: str,
    tags: list[str] | None,
    max_results: int,
) -> str:
    """List all memory entries, optionally filtered by tags.

    When multiple tags are provided, returns entries matching ALL tags.
    """
    if tags and len(tags) > 1:
        # Multi-tag: intersect results for each tag
        result_sets = []
        for t in tags:
            entries = db.list_entries(agent_id, tag=t, max_results=max_results)
            result_sets.append({e["id"] for e in entries})
        # Keep entries that appear in all tag result sets
        common_ids = result_sets[0]
        for s in result_sets[1:]:
            common_ids &= s
        # Re-fetch with the first tag and filter
        entries = db.list_entries(agent_id, tag=tags[0], max_results=max_results)
        entries = [e for e in entries if e["id"] in common_ids]
    else:
        tag = tags[0] if tags else None
        entries = db.list_entries(agent_id, tag=tag, max_results=max_results)

    return ok(
        tool=_TOOL,
        reason=reason,
        data={
            "action": "list",
            "count": len(entries),
            "entries": entries,
        },
    )


def _action_update(
    db: MemoryDatabase,
    reason: str,
    agent_id: str,
    entry_id: str | None,
    value: str | None,
) -> str:
    """Update an existing memory entry."""
    if not entry_id:
        return err(
            tool=_TOOL,
            reason=reason,
            code="MISSING_ENTRY_ID",
            message="Missing required 'entry_id' parameter.",
            how_to_fix="Provide the 'entry_id' from a previous store/search.",
        )
    if value is None:
        return err(
            tool=_TOOL,
            reason=reason,
            code="MISSING_VALUE",
            message="Missing required 'value' parameter.",
            how_to_fix="Provide the 'value' parameter.",
        )

    success = db.update(entry_id, agent_id, value)
    if not success:
        return err(
            tool=_TOOL,
            reason=reason,
            code="ENTRY_NOT_FOUND",
            message=f"Entry '{entry_id}' not found.",
        )

    return ok(
        tool=_TOOL,
        reason=reason,
        data={
            "action": "update",
            "entry_id": entry_id,
            "message": "Memory entry updated successfully",
        },
    )


def _action_delete(
    db: MemoryDatabase,
    reason: str,
    agent_id: str,
    entry_id: str | None,
) -> str:
    """Delete a memory entry."""
    if not entry_id:
        return err(
            tool=_TOOL,
            reason=reason,
            code="MISSING_ENTRY_ID",
            message="Missing required 'entry_id' parameter.",
            how_to_fix="Provide the 'entry_id' from a previous store/search.",
        )

    success = db.delete(entry_id, agent_id)
    if not success:
        return err(
            tool=_TOOL,
            reason=reason,
            code="ENTRY_NOT_FOUND",
            message=f"Entry '{entry_id}' not found.",
        )

    return ok(
        tool=_TOOL,
        reason=reason,
        data={
            "action": "delete",
            "entry_id": entry_id,
            "message": "Memory entry deleted successfully",
        },
    )
