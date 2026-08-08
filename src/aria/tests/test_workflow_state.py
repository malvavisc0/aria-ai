"""Tests for WorkflowState, initial_workflow_state, and state_reducer.

These tests exercise the shared-state machinery in :mod:`aria.llm` in
isolation — no LLM, no network, no agents required.
"""

from types import SimpleNamespace

import pytest
from llama_index.core.agent.workflow import ToolCallResult
from llama_index.core.tools.types import ToolOutput

from aria.llm import (
    StatefulAgentWorkflow,
    WorkflowState,
    get_agent_workflow,
    get_chat_llm,
    initial_workflow_state,
    state_reducer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_call_result(
    tool_name: str,
    tool_kwargs: dict,
    content: str,
    is_error: bool = False,
) -> ToolCallResult:
    """Build a minimal :class:`ToolCallResult` for testing."""
    output = ToolOutput(
        content=content,
        tool_name=tool_name,
        raw_input=tool_kwargs,
        raw_output=content,
        is_error=is_error,
    )
    return ToolCallResult(
        tool_name=tool_name,
        tool_kwargs=tool_kwargs,
        tool_id="test-id",
        tool_output=output,
        return_direct=False,
    )


# ---------------------------------------------------------------------------
# initial_workflow_state
# ---------------------------------------------------------------------------


class TestInitialWorkflowState:
    """Tests for :func:`initial_workflow_state`."""

    def test_last_error_is_none(self):
        state = initial_workflow_state()
        assert state["last_error"] is None


# ---------------------------------------------------------------------------
# state_reducer — ToolCallResult events
# ---------------------------------------------------------------------------


class TestStateReducerToolCallResult:
    """Tests for :func:`state_reducer` handling :class:`ToolCallResult`."""

    def test_last_error_none_on_success(self):
        state = initial_workflow_state()
        ev = _make_tool_call_result("web_search", {}, "ok")
        state_reducer(state, ev)
        assert state["last_error"] is None

    def test_last_error_set_on_failure(self):
        state = initial_workflow_state()
        ev = _make_tool_call_result("bad_tool", {}, "boom", is_error=True)
        state_reducer(state, ev)
        assert state["last_error"] == "boom"

    def test_last_error_cleared_after_success(self):
        """A successful tool call after a failure must clear ``last_error``."""
        state = initial_workflow_state()
        state_reducer(
            state,
            _make_tool_call_result("bad_tool", {}, "boom", is_error=True),
        )
        state_reducer(state, _make_tool_call_result("good_tool", {}, "ok"))
        assert state["last_error"] is None

    def test_returns_same_state_object(self):
        state = initial_workflow_state()
        ev = _make_tool_call_result("tool", {}, "out")
        result = state_reducer(state, ev)
        assert result is state


# ---------------------------------------------------------------------------
# state_reducer — unknown / unhandled event types
# ---------------------------------------------------------------------------


class TestStateReducerUnknownEvents:
    """Tests for :func:`state_reducer` with unrecognised event types."""

    @pytest.mark.parametrize(
        "event",
        [
            None,
            42,
            "a string event",
            object(),
            {"type": "unknown"},
        ],
    )
    def test_unknown_event_leaves_state_unchanged(self, event):
        state = initial_workflow_state()
        state_reducer(state, event)
        assert state["last_error"] is None


class _FakeStore:
    def __init__(self, initial: dict[str, object] | None = None):
        self._data = dict(initial or {})

    async def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)

    async def set(self, key: str, value: object) -> None:
        self._data[key] = value


class TestStatefulAgentWorkflowReduceState:
    """Tests for live state synchronization in StatefulAgentWorkflow."""

    @staticmethod
    def _make_workflow() -> StatefulAgentWorkflow:
        workflow = StatefulAgentWorkflow.__new__(StatefulAgentWorkflow)
        workflow.root_agent = "Aria"
        return workflow

    @pytest.mark.asyncio
    async def test_reduce_state_initializes_missing_state(self):
        workflow = self._make_workflow()
        ctx = SimpleNamespace(store=_FakeStore())

        result = await workflow.reduce_state(
            ctx, _make_tool_call_result("web_search", {}, "results")
        )

        assert result["last_error"] is None

        stored_state = await ctx.store.get("state")
        assert stored_state == result

    @pytest.mark.asyncio
    async def test_reduce_state_records_error(self):
        workflow = self._make_workflow()
        existing_state: WorkflowState = initial_workflow_state()
        ctx = SimpleNamespace(store=_FakeStore({"state": existing_state}))

        result = await workflow.reduce_state(
            ctx, _make_tool_call_result("bad_tool", {}, "boom", is_error=True)
        )

        assert result["last_error"] == "boom"

        stored_state = await ctx.store.get("state")
        assert stored_state is result


class TestStatefulAgentWorkflowRegistration:
    """Regression tests for step discovery on workflow overrides."""

    def test_override_steps_keep_step_metadata(self):
        assert hasattr(StatefulAgentWorkflow.run_agent_step, "_step_config")
        assert hasattr(StatefulAgentWorkflow.call_tool, "_step_config")

    def test_get_agent_workflow_validation_succeeds(self):
        workflow = get_agent_workflow(get_chat_llm("http://127.0.0.1:1"))

        workflow._validate()
