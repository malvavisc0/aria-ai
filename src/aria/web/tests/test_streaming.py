from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aria.web import streaming as pipeline


class TestStreamAgentResponse:
    """Tests for the simplified stream_agent_response."""

    @staticmethod
    def _make_handler(*events) -> Any:
        """Build a mock handler yielding the given events."""

        async def _stream():
            for ev in events:
                yield ev

        _result = SimpleNamespace(response=SimpleNamespace(content=None))

        async def _await_result():
            return _result

        class _MockHandler:
            """Minimal awaitable mock for WorkflowHandler."""

            stream_events = staticmethod(_stream)

            def __await__(self):
                return _await_result().__await__()

        return _MockHandler()

    @staticmethod
    def _make_output() -> Any:
        output = MagicMock()
        output.stream_token = AsyncMock()
        return output

    @pytest.mark.asyncio
    async def test_tool_step_persists_when_answer_delta_starts(
        self, monkeypatch
    ) -> None:
        """Tool steps are persisted and never removed — the full per-turn
        hierarchy (Thinking ▸ tool ▸ answer) must stay visible.

        Replaces the old "lingering last tool step" regression guard: tool
        steps now intentionally persist instead of being cleared when the
        answer begins.
        """
        from llama_index.core.agent.workflow import AgentStream, ToolCall

        tool_event = ToolCall(
            tool_name="read_file",
            tool_kwargs={},
            tool_id="t1",
        )
        answer = AgentStream(
            delta="Here is the answer",
            response="Here is the answer",
            current_agent_name="test",
        )

        handler = self._make_handler(tool_event, answer)
        output = self._make_output()

        sent_step = MagicMock()
        sent_step.remove = AsyncMock()
        sent_step.update = AsyncMock()
        monkeypatch.setattr(
            pipeline, "send_tool_step", AsyncMock(return_value=sent_step)
        )

        await pipeline.stream_agent_response(handler, output)

        sent_step.remove.assert_not_awaited()
        sent_step.update.assert_awaited()

    @pytest.mark.asyncio
    async def test_interleaved_tool_steps_persist(self, monkeypatch) -> None:
        """Models may interleave: answer → tool → answer → tool → answer.

        Every tool step stays visible (persisted, never removed), so the
        full hierarchy remains in the UI and the persisted history.
        """
        from llama_index.core.agent.workflow import (
            AgentOutput,
            AgentStream,
            ToolCall,
        )
        from llama_index.core.llms import ChatMessage

        events = [
            AgentStream(delta="Let me check ", response="", current_agent_name="t"),
            ToolCall(tool_name="search", tool_kwargs={}, tool_id="t1"),
            AgentStream(delta="found it, now ", response="", current_agent_name="t"),
            ToolCall(tool_name="read_file", tool_kwargs={}, tool_id="t2"),
            AgentStream(
                delta="here is the answer", response="", current_agent_name="t"
            ),
            AgentOutput(
                response=ChatMessage(content="here is the answer"),
                current_agent_name="t",
            ),
        ]

        handler = self._make_handler(*events)
        output = self._make_output()

        steps: list[MagicMock] = []

        async def _send_tool_step(_event):
            s = MagicMock()
            s.remove = AsyncMock()
            s.update = AsyncMock()
            steps.append(s)
            return s

        monkeypatch.setattr(pipeline, "send_tool_step", _send_tool_step)

        await pipeline.stream_agent_response(handler, output)

        assert len(steps) == 2
        for s in steps:
            s.remove.assert_not_awaited()
        steps[-1].update.assert_awaited()

    @pytest.mark.asyncio
    async def test_tool_call_result_populates_step_output(self, monkeypatch) -> None:
        """A ToolCallResult event sets step.output from the tool result and
        finalizes the step via update().
        """
        from llama_index.core.agent.workflow import ToolCall, ToolCallResult
        from llama_index.core.tools import ToolOutput

        tool_call = ToolCall(
            tool_name="read_file",
            tool_kwargs={"path": "/tmp/x.md"},
            tool_id="t1",
        )
        tool_output = ToolOutput(
            tool_name="read_file",
            content="file contents here",
            raw_input={"path": "/tmp/x.md"},
            raw_output="file contents here",
        )
        result = ToolCallResult(
            tool_name="read_file",
            tool_kwargs={"path": "/tmp/x.md"},
            tool_id="t1",
            tool_output=tool_output,
            return_direct=False,
        )

        handler = self._make_handler(tool_call, result)
        output = self._make_output()

        sent_step = MagicMock()
        sent_step.update = AsyncMock()
        sent_step.metadata = {"tool_id": "t1"}

        async def _send(_event):
            sent_step.input = _event.tool_kwargs
            return sent_step

        monkeypatch.setattr(pipeline, "send_tool_step", _send)

        await pipeline.stream_agent_response(handler, output)

        assert sent_step.output == "file contents here"
        sent_step.update.assert_awaited()

    @pytest.mark.asyncio
    async def test_tool_call_result_parses_json_output(self, monkeypatch) -> None:
        """JSON tool output is parsed to a dict so Chainlit renders it as
        formatted, syntax-highlighted JSON instead of a raw string.
        """
        import json

        from llama_index.core.agent.workflow import ToolCall, ToolCallResult
        from llama_index.core.tools import ToolOutput

        payload = {
            "status": "success",
            "tool": "search",
            "data": {"results": ["a", "b"]},
        }
        tool_call = ToolCall(
            tool_name="search",
            tool_kwargs={"query": "test"},
            tool_id="t1",
        )
        tool_output = ToolOutput(
            tool_name="search",
            content=json.dumps(payload),
            raw_input={"query": "test"},
            raw_output=json.dumps(payload),
        )
        result = ToolCallResult(
            tool_name="search",
            tool_kwargs={"query": "test"},
            tool_id="t1",
            tool_output=tool_output,
            return_direct=False,
        )

        handler = self._make_handler(tool_call, result)
        output = self._make_output()

        sent_step = MagicMock()
        sent_step.update = AsyncMock()
        sent_step.metadata = {"tool_id": "t1"}

        async def _send(_event):
            sent_step.input = _event.tool_kwargs
            return sent_step

        monkeypatch.setattr(pipeline, "send_tool_step", _send)

        await pipeline.stream_agent_response(handler, output)

        assert sent_step.output == payload
        sent_step.update.assert_awaited()

    @pytest.mark.asyncio
    async def test_late_result_fills_its_own_step(self, monkeypatch) -> None:
        """A result for call A arriving while call B is pending must fill A,
        never finalize B early (the real-world ax spin-forever case)."""
        import json

        from llama_index.core.agent.workflow import ToolCall, ToolCallResult
        from llama_index.core.tools import ToolOutput

        def _call(tid: str) -> ToolCall:
            return ToolCall(tool_name="ax", tool_kwargs={}, tool_id=tid)

        def _result(tid: str, marker: str) -> ToolCallResult:
            out = ToolOutput(
                tool_name="ax",
                content=json.dumps({"m": marker}),
                raw_input={},
                raw_output=json.dumps({"m": marker}),
            )
            return ToolCallResult(
                tool_name="ax",
                tool_kwargs={},
                tool_id=tid,
                tool_output=out,
                return_direct=False,
            )

        steps: dict[str, MagicMock] = {}

        async def _send(ev):
            step = MagicMock()
            step.update = AsyncMock()
            step.metadata = {"tool_id": ev.tool_id}
            steps[ev.tool_id] = step
            return step

        monkeypatch.setattr(pipeline, "send_tool_step", _send)

        handler = self._make_handler(
            _call("a"), _call("b"), _result("a", "A"), _result("b", "B")
        )
        await pipeline.stream_agent_response(handler, self._make_output())

        assert steps["a"].output == {"m": "A"}
        assert steps["b"].output == {"m": "B"}
        steps["a"].update.assert_awaited_once()
        steps["b"].update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_result_leaves_pending_step_alone(self, monkeypatch) -> None:
        """A result with an unknown id is dropped; the pending step is
        finalized without output at end of stream, not mid-stream."""
        from llama_index.core.agent.workflow import ToolCall, ToolCallResult
        from llama_index.core.tools import ToolOutput

        call = ToolCall(tool_name="ax", tool_kwargs={}, tool_id="t1")
        unknown = ToolCallResult(
            tool_name="ax",
            tool_kwargs={},
            tool_id="nope",
            tool_output=ToolOutput(
                tool_name="ax", content="x", raw_input={}, raw_output="x"
            ),
            return_direct=False,
        )

        step = SimpleNamespace(update=AsyncMock(), metadata={"tool_id": "t1"})
        monkeypatch.setattr(pipeline, "send_tool_step", AsyncMock(return_value=step))

        handler = self._make_handler(call, unknown)
        await pipeline.stream_agent_response(handler, self._make_output())

        # Not finalized mid-stream by the foreign result…
        assert step.update.await_count == 1  # …only at end of stream.
        assert not hasattr(step, "output")

    @pytest.mark.asyncio
    async def test_streams_text_delta(self) -> None:
        from llama_index.core.agent.workflow import AgentStream

        event = AgentStream(
            delta="hello",
            response="hello",
            current_agent_name="test",
        )
        handler = self._make_handler(event)
        output = self._make_output()

        emitted, meta, _answer = await pipeline.stream_agent_response(handler, output)

        assert emitted is True
        assert meta["tools_called"] == []
        assert meta["has_thinking"] is False
        output.stream_token.assert_any_await("hello")

    @pytest.mark.asyncio
    async def test_streams_thinking_delta_as_step(self, monkeypatch) -> None:
        from llama_index.core.agent.workflow import AgentStream

        event = AgentStream(
            delta="",
            response="",
            current_agent_name="test",
            thinking_delta="pondering",
        )
        handler = self._make_handler(event)
        output = self._make_output()

        thinking_step = MagicMock()
        thinking_step.stream_token = AsyncMock()
        thinking_step.update = AsyncMock()
        send_mock = AsyncMock(return_value=thinking_step)
        monkeypatch.setattr(pipeline, "send_thinking_step", send_mock)

        emitted, meta, answer = await pipeline.stream_agent_response(handler, output)

        assert emitted is True
        assert meta["has_thinking"] is True
        assert meta["tools_called"] == []
        assert answer == ""

        send_mock.assert_awaited()
        thinking_step.stream_token.assert_awaited_with("pondering")
        thinking_step.update.assert_awaited()
        output.stream_token.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_finalizes_thinking_step_on_regular_delta(self, monkeypatch) -> None:
        from llama_index.core.agent.workflow import AgentStream

        thinking = AgentStream(
            delta="",
            response="",
            current_agent_name="test",
            thinking_delta="thought",
        )
        regular = AgentStream(
            delta="answer",
            response="answer",
            current_agent_name="test",
        )
        handler = self._make_handler(thinking, regular)
        output = self._make_output()

        thinking_step = MagicMock()
        thinking_step.stream_token = AsyncMock()
        thinking_step.update = AsyncMock()
        monkeypatch.setattr(
            pipeline, "send_thinking_step", AsyncMock(return_value=thinking_step)
        )

        emitted, meta, answer = await pipeline.stream_agent_response(handler, output)

        assert emitted is True
        assert meta["has_thinking"] is True
        assert answer == "answer"
        thinking_step.stream_token.assert_awaited_with("thought")
        thinking_step.update.assert_awaited()
        output.stream_token.assert_awaited_with("answer")

    @pytest.mark.asyncio
    async def test_agent_output_fallback_when_no_streamed_content(
        self,
    ) -> None:
        from llama_index.core.agent.workflow import AgentOutput
        from llama_index.core.llms import ChatMessage

        event = AgentOutput(
            response=ChatMessage(content="fallback answer"),
            current_agent_name="test",
        )
        handler = self._make_handler(event)
        output = self._make_output()

        emitted, meta, answer = await pipeline.stream_agent_response(handler, output)

        assert emitted is True
        assert meta["tools_called"] == []
        assert meta["has_thinking"] is False
        assert answer == "fallback answer"
        output.stream_token.assert_any_await("fallback answer")

    @pytest.mark.asyncio
    async def test_thinking_then_distinct_final_answer_is_streamed(
        self, monkeypatch
    ) -> None:
        """Thinking is streamed to its own step; a distinct final answer is
        also streamed (the original bug dropped it because thinking set
        emitted).
        """
        from llama_index.core.agent.workflow import AgentOutput, AgentStream
        from llama_index.core.llms import ChatMessage

        thinking = AgentStream(
            delta="",
            response="",
            current_agent_name="test",
            thinking_delta="reasoning here",
        )
        final = AgentOutput(
            response=ChatMessage(content="the actual answer"),
            current_agent_name="test",
        )
        handler = self._make_handler(thinking, final)
        output = self._make_output()

        thinking_step = MagicMock()
        thinking_step.stream_token = AsyncMock()
        thinking_step.update = AsyncMock()
        monkeypatch.setattr(
            pipeline, "send_thinking_step", AsyncMock(return_value=thinking_step)
        )

        emitted, meta, answer = await pipeline.stream_agent_response(handler, output)

        assert emitted is True
        assert meta["has_thinking"] is True
        assert answer == "the actual answer"
        thinking_step.stream_token.assert_awaited_with("reasoning here")
        output.stream_token.assert_awaited_with("the actual answer")

    @pytest.mark.asyncio
    async def test_thinking_duplicated_as_final_not_restreamed(
        self, monkeypatch
    ) -> None:
        """When the final answer equals the thinking text, it is not
        streamed twice (some models echo thinking as the response).
        """
        from llama_index.core.agent.workflow import AgentOutput, AgentStream
        from llama_index.core.llms import ChatMessage

        thinking = AgentStream(
            delta="",
            response="",
            current_agent_name="test",
            thinking_delta="same text",
        )
        final = AgentOutput(
            response=ChatMessage(content="same text"),
            current_agent_name="test",
        )
        handler = self._make_handler(thinking, final)
        output = self._make_output()

        thinking_step = MagicMock()
        thinking_step.stream_token = AsyncMock()
        thinking_step.update = AsyncMock()
        monkeypatch.setattr(
            pipeline, "send_thinking_step", AsyncMock(return_value=thinking_step)
        )

        emitted, meta, answer = await pipeline.stream_agent_response(handler, output)

        assert emitted is True
        assert meta["has_thinking"] is True
        assert answer == ""
        thinking_step.stream_token.assert_awaited_once_with("same text")
        output.stream_token.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_creates_multiple_thinking_steps_for_interleaved_segments(
        self, monkeypatch
    ) -> None:
        """Each contiguous thinking run becomes its own, independently
        finalized Thinking step.
        """
        from llama_index.core.agent.workflow import AgentStream

        events = [
            AgentStream(
                delta="",
                response="",
                current_agent_name="t",
                thinking_delta="reason one",
            ),
            AgentStream(delta="part one ", response="", current_agent_name="t"),
            AgentStream(
                delta="",
                response="",
                current_agent_name="t",
                thinking_delta="reason two",
            ),
            AgentStream(delta="part two", response="", current_agent_name="t"),
        ]
        handler = self._make_handler(*events)
        output = self._make_output()

        thinking_steps: list[MagicMock] = []

        async def _send_thinking_step():
            step = MagicMock()
            step.stream_token = AsyncMock()
            step.update = AsyncMock()
            thinking_steps.append(step)
            return step

        monkeypatch.setattr(pipeline, "send_thinking_step", _send_thinking_step)

        emitted, meta, answer = await pipeline.stream_agent_response(handler, output)

        assert emitted is True
        assert meta["has_thinking"] is True
        assert answer == "part one part two"
        assert len(thinking_steps) == 2
        thinking_steps[0].stream_token.assert_awaited_with("reason one")
        thinking_steps[0].update.assert_awaited()
        thinking_steps[1].stream_token.assert_awaited_with("reason two")
        thinking_steps[1].update.assert_awaited()
