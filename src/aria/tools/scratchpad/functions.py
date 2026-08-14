"""Standalone scratchpad tool — decoupled from reasoning sessions.

Provides a persistent key-value working memory that survives across
reasoning sessions and conversations.
"""

from typing import Any

from aria.tools import Reason, safe_json, utc_timestamp
from aria.tools.decorators import log_tool_call

from .database import get_database

_DEFAULT_AGENT_ID = "aria"


@log_tool_call
def scratchpad(
    reason: Reason,
    key: str,
    value: str | None = None,
    operation: str = "get",
    agent_id: str = _DEFAULT_AGENT_ID,
) -> str:
    """Small persistent key-value working memory.

    Use this to store or retrieve short intermediate data across steps.

    Returns:
        JSON string with operation result and stored or retrieved value.
    """
    operation = operation.lower().strip()
    now = utc_timestamp()

    if operation == "set":
        result = _op_set(reason, agent_id, key, value, now)
    elif operation == "get":
        result = _op_get(reason, agent_id, key, now)
    elif operation == "delete":
        result = _op_delete(reason, agent_id, key, now)
    elif operation == "list":
        result = _op_list(reason, agent_id, now)
    else:
        result = _err(
            reason=reason,
            agent_id=agent_id,
            code="UNSUPPORTED_OPERATION",
            message=(
                f"Unknown operation '{operation}'. Supported: get, set, delete, list"
            ),
            how_to_fix="Use one of: get, set, delete, list",
        )

    return safe_json(result)


# ── helpers ──────────────────────────────────────────────────────────


def _ok(
    *,
    reason: str,
    agent_id: str,
    data: dict[str, Any],
    timestamp: str,
) -> dict[str, Any]:
    return {
        "status": "success",
        "tool": "scratchpad",
        "reason": reason,
        "agent_id": agent_id,
        "timestamp": timestamp,
        "data": data,
    }


def _err(
    *,
    reason: str,
    agent_id: str,
    code: str,
    message: str,
    how_to_fix: str | None = None,
) -> dict[str, Any]:
    err: dict[str, Any] = {
        "code": code,
        "message": message,
        "recoverable": True,
    }
    if how_to_fix:
        err["how_to_fix"] = how_to_fix
    return {
        "status": "error",
        "tool": "scratchpad",
        "reason": reason,
        "agent_id": agent_id,
        "timestamp": utc_timestamp(),
        "error": err,
    }


# ── operations ───────────────────────────────────────────────────────


def _op_set(
    reason: str,
    agent_id: str,
    key: str,
    value: str | None,
    now: str,
) -> dict[str, Any]:
    if value is None:
        return _err(
            reason=reason,
            agent_id=agent_id,
            code="VALUE_REQUIRED",
            message="Value required for set operation",
            how_to_fix="Provide the 'value' parameter.",
        )

    db = get_database()
    db.set_item(agent_id, key, value, reason)

    return _ok(
        reason=reason,
        agent_id=agent_id,
        timestamp=now,
        data={
            "tool": "set",
            "key": key,
            "value": value,
            "reason": reason,
        },
    )


def _op_get(
    reason: str,
    agent_id: str,
    key: str,
    now: str,
) -> dict[str, Any]:
    db = get_database()
    item = db.get_item(agent_id, key)

    if item is None:
        return _err(
            reason=reason,
            agent_id=agent_id,
            code="KEY_NOT_FOUND",
            message=f"Key '{key}' not found",
            how_to_fix=f"Use operation='set' to store a value for '{key}'.",
        )

    return _ok(
        reason=reason,
        agent_id=agent_id,
        timestamp=now,
        data={
            "tool": "get",
            "key": key,
            "value": item["value"],
        },
    )


def _op_delete(
    reason: str,
    agent_id: str,
    key: str,
    now: str,
) -> dict[str, Any]:
    db = get_database()

    if key == "all":
        count = db.clear_all(agent_id)
        return _ok(
            reason=reason,
            agent_id=agent_id,
            timestamp=now,
            data={
                "tool": "delete",
                "key": "all",
                "deleted_count": count,
            },
        )

    success = db.delete_item(agent_id, key)
    if not success:
        return _err(
            reason=reason,
            agent_id=agent_id,
            code="KEY_NOT_FOUND",
            message=f"Key '{key}' not found for delete operation",
        )

    return _ok(
        reason=reason,
        agent_id=agent_id,
        timestamp=now,
        data={
            "tool": "delete",
            "key": key,
        },
    )


def _op_list(
    reason: str,
    agent_id: str,
    now: str,
) -> dict[str, Any]:
    db = get_database()
    items = db.list_items(agent_id)

    return _ok(
        reason=reason,
        agent_id=agent_id,
        timestamp=now,
        data={
            "tool": "list",
            "items": items,
        },
    )
