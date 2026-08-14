"""Tests for tool-step labeling."""

from llama_index.core.agent.workflow import ToolCall

from aria.helpers.ui import _step_label_from_tool_call


class TestStepLabelFromToolCall:
    def test_strips_wrapping_quotes(self) -> None:
        """Models sometimes wrap the whole reason in quotes."""
        ev = ToolCall(
            tool_name="ax",
            tool_kwargs={"reason": '"Find the official website of vllm"'},
            tool_id="1",
        )
        assert _step_label_from_tool_call(ev) == "Find the official website of vllm"

    def test_keeps_inner_quotes(self) -> None:
        ev = ToolCall(
            tool_name="ax",
            tool_kwargs={"reason": 'say "hi" loudly'},
            tool_id="1",
        )
        assert _step_label_from_tool_call(ev) == 'say "hi" loudly'

    def test_falls_back_to_tool_name(self) -> None:
        ev = ToolCall(tool_name="web", tool_kwargs={}, tool_id="1")
        assert _step_label_from_tool_call(ev) == "web"
