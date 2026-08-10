"""Tests for aria.llm._state — thread_id injection into worker tool calls.

Verifies that ``_inject_thread_id`` populates ``thread_id`` on ``worker``
spawns dispatched through the ``ax`` unified tool from the Chainlit session,
does not clobber an explicitly provided value, and is a no-op outside a
Chainlit context.

The agent's only registered tool is ``ax``; worker spawns are dispatched
as ``ax(family="worker", command="spawn", args={...})``.  The ``thread_id``
must be injected into the nested ``args`` dict, not the top-level
``tool_kwargs``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from aria.llm._state import _inject_thread_id


def _ax_worker_call(
    args: dict | None = None,
) -> MagicMock:
    """Build a fake ToolCall for ``ax(family="worker", ...)``."""
    ev = MagicMock()
    ev.tool_name = "ax"
    ev.tool_kwargs = {
        "reason": "spawning worker",
        "family": "worker",
        "command": "spawn",
        "args": dict(args or {}),
    }
    return ev


def _ax_call(family: str, kwargs: dict | None = None) -> MagicMock:
    """Build a fake ToolCall for ``ax`` with an arbitrary family."""
    ev = MagicMock()
    ev.tool_name = "ax"
    ev.tool_kwargs = {"reason": "test", "family": family, "command": "test"}
    ev.tool_kwargs.update(kwargs or {})
    return ev


def _mock_chainlit_session(tid: str | None, monkeypatch) -> None:
    """Patch chainlit.user_session to return *tid* for 'thread_id'."""
    monkeypatch.setattr(
        "chainlit.user_session",
        SimpleNamespace(get=lambda k: tid if k == "thread_id" else None),
    )


class TestInjectThreadId:
    """Tests for _inject_thread_id."""

    def test_injects_thread_id_into_args(self, monkeypatch) -> None:
        """Populates args.thread_id when the worker spawn omits it."""
        _mock_chainlit_session("thread-abc", monkeypatch)

        ev = _ax_worker_call({"prompt": "do work", "expected": "result"})
        _inject_thread_id(ev)

        assert ev.tool_kwargs["args"]["thread_id"] == "thread-abc"

    def test_preserves_explicit_thread_id(self, monkeypatch) -> None:
        """Does not overwrite an explicitly provided thread_id."""
        _mock_chainlit_session("session-thread", monkeypatch)

        ev = _ax_worker_call({"thread_id": "explicit-id"})
        _inject_thread_id(ev)

        assert ev.tool_kwargs["args"]["thread_id"] == "explicit-id"

    def test_ignores_non_worker_families(self, monkeypatch) -> None:
        """Does not inject thread_id for non-worker ax families."""
        _mock_chainlit_session("thread-abc", monkeypatch)

        ev = _ax_call("shell", {"command": "ls"})
        _inject_thread_id(ev)

        assert "args" not in ev.tool_kwargs or "thread_id" not in ev.tool_kwargs.get(
            "args", {}
        )

    def test_ignores_non_ax_tools(self, monkeypatch) -> None:
        """Does not inject thread_id for tools other than ax."""
        _mock_chainlit_session("thread-abc", monkeypatch)

        ev = MagicMock()
        ev.tool_name = "shell"
        ev.tool_kwargs = {"command": "ls"}
        _inject_thread_id(ev)

        assert "thread_id" not in ev.tool_kwargs

    def test_noop_without_chainlit_context(self) -> None:
        """Does not raise when chainlit session is unavailable (CLI/tests)."""
        ev = _ax_worker_call({"prompt": "do work", "expected": "result"})
        _inject_thread_id(ev)

        assert "thread_id" not in ev.tool_kwargs["args"]

    def test_noop_when_session_has_no_thread_id(self, monkeypatch) -> None:
        """Does not inject when the session has no thread_id set."""
        _mock_chainlit_session(None, monkeypatch)

        ev = _ax_worker_call({"prompt": "do work", "expected": "result"})
        _inject_thread_id(ev)

        assert "thread_id" not in ev.tool_kwargs["args"]

    def test_creates_args_dict_if_missing(self, monkeypatch) -> None:
        """Creates the args dict if the LLM omitted it entirely."""
        _mock_chainlit_session("thread-abc", monkeypatch)

        ev = MagicMock()
        ev.tool_name = "ax"
        ev.tool_kwargs = {
            "reason": "test",
            "family": "worker",
            "command": "spawn",
        }
        _inject_thread_id(ev)

        assert ev.tool_kwargs["args"]["thread_id"] == "thread-abc"
