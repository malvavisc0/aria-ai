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
    async def test_removes_last_tool_step_when_answer_delta_starts(
        self, monkeypatch
    ) -> None:
        """The last ToolCall step must be cleared as soon as the final
        answer's first delta streams — not left visible until AgentOutput.

        Regression guard for the "lingering last tool step" bug.
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
        monkeypatch.setattr(
            pipeline, "send_tool_step", AsyncMock(return_value=sent_step)
        )

        await pipeline.stream_agent_response(handler, output)

        # The tool step is created on ToolCall and removed once the answer
        # delta begins streaming — before any AgentOutput event.
        sent_step.remove.assert_awaited()

    @pytest.mark.asyncio
    async def test_interleaved_stream_tool_stream_removes_each_tool_step(
        self, monkeypatch
    ) -> None:
        """Models may interleave: answer → tool → answer → tool → answer.

        Every tool step must appear while its tool runs and be cleared when
        the answer resumes; the last tool (no delta after it) is cleared by
        the AgentOutput cleanup.  None should linger at the end.
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
            steps.append(s)
            return s

        monkeypatch.setattr(pipeline, "send_tool_step", _send_tool_step)

        await pipeline.stream_agent_response(handler, output)

        # Two tool steps were created; both must have been removed (the
        # first by the intervening answer delta, the second by the
        # AgentOutput cleanup — no delta follows it).
        assert len(steps) == 2
        for s in steps:
            s.remove.assert_awaited()

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
    async def test_streams_thinking_delta_as_blockquote(self) -> None:
        from llama_index.core.agent.workflow import AgentStream

        event = AgentStream(
            delta="",
            response="",
            current_agent_name="test",
            thinking_delta="pondering",
        )
        handler = self._make_handler(event)
        output = self._make_output()

        emitted, meta, answer = await pipeline.stream_agent_response(handler, output)

        assert emitted is True
        assert meta["has_thinking"] is True
        assert meta["tools_called"] == []
        assert answer == ""

        output.stream_token.assert_any_await(pipeline._BLOCKQUOTE_PREFIX)
        output.stream_token.assert_any_await("pondering")

    @pytest.mark.asyncio
    async def test_closes_thinking_block_on_regular_delta(self) -> None:
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

        emitted, meta, answer = await pipeline.stream_agent_response(handler, output)

        assert emitted is True
        assert meta["has_thinking"] is True
        assert answer == "answer"
        calls = [c.args[0] for c in output.stream_token.call_args_list]
        assert calls == [
            pipeline._BLOCKQUOTE_PREFIX,
            "thought",
            pipeline._BLOCKQUOTE_END,
            "answer",
        ]

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
    async def test_thinking_then_distinct_final_answer_is_streamed(self) -> None:
        """Thinking streamed as blockquote; a distinct final answer is also
        streamed (the original bug dropped it because thinking set emitted).
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

        emitted, meta, answer = await pipeline.stream_agent_response(handler, output)

        assert emitted is True
        assert meta["has_thinking"] is True
        assert answer == "the actual answer"
        calls = [c.args[0] for c in output.stream_token.call_args_list]
        # blockquoted thinking + the distinct final answer must both appear
        assert "reasoning here" in calls
        assert "the actual answer" in calls

    @pytest.mark.asyncio
    async def test_thinking_duplicated_as_final_not_restreamed(self) -> None:
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

        emitted, meta, answer = await pipeline.stream_agent_response(handler, output)

        assert emitted is True
        assert meta["has_thinking"] is True
        assert answer == ""
        calls = [c.args[0] for c in output.stream_token.call_args_list]
        # "same text" appears once (as the blockquoted thinking), not twice
        assert calls.count("same text") == 1
