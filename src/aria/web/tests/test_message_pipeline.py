from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import chainlit as cl
import pytest

from aria.web import message_pipeline as pipeline


def _mock_message(**kwargs: Any) -> Any:
    """Create a mock cl.Message from keyword attributes."""
    return SimpleNamespace(**kwargs)


class TestRoutePipelineError:
    """Tests for _route_pipeline_error — error-to-user-message routing."""

    def test_context_overflow_message(self) -> None:
        """Substring 'maximum context length' maps to overflow message."""
        msg = pipeline._route_pipeline_error(
            "This model's maximum context length is 32768 tokens."
        )
        assert "context window" in msg
        assert "new conversation" in msg

    def test_generic_message_for_unknown_error(self) -> None:
        """Anything else maps to the generic retry message."""
        msg = pipeline._route_pipeline_error("Connection refused")
        assert msg == "An error occurred. Please try again."

    def test_case_insensitive_match(self) -> None:
        """Matching is case-insensitive."""
        msg = pipeline._route_pipeline_error("MAXIMUM CONTEXT LENGTH exceeded")
        assert "context window" in msg

    def test_empty_string_returns_generic(self) -> None:
        """Empty error string falls through to generic."""
        assert (
            pipeline._route_pipeline_error("") == "An error occurred. Please try again."
        )


class TestEditDetection:
    """Tests for metadata-based edit detection."""

    @pytest.mark.asyncio
    async def test_mark_message_processed(self, monkeypatch) -> None:
        """_mark_message_processed persists _aria_processed in metadata."""
        created_steps = []
        mock_data_layer = MagicMock()
        mock_data_layer.create_step = AsyncMock(
            side_effect=lambda d: created_steps.append(d)
        )
        monkeypatch.setattr(
            pipeline,
            "get_data_layer_handler",
            lambda: mock_data_layer,
        )

        message = MagicMock()
        message.id = "msg-1"
        message.metadata = {"location": "http://localhost"}
        message.to_dict.return_value = {
            "id": "msg-1",
            "type": "user_message",
            "output": "Hello",
            "metadata": {"location": "http://localhost"},
        }

        await pipeline._mark_message_processed(message)

        assert len(created_steps) == 1
        meta = created_steps[0]["metadata"]
        assert meta["processed"] is True
        assert meta["location"] == "http://localhost"
        # All default keys are always present
        assert meta["tools_called"] == []
        assert meta["has_thinking"] is False
        assert meta["prompt_enhanced"] is False
        assert meta["attachments"] == []
        assert meta["error"] == ""

    @pytest.mark.asyncio
    async def test_mark_message_processed_writes_flag_in_memory(
        self, monkeypatch
    ) -> None:
        """The processed flag is written onto the in-memory message too.

        Chainlit's ``edit_message`` mutates the same object and re-invokes
        ``on_message``, so the flag must live on ``message.metadata`` for a
        same-session edit to be detected.
        """
        mock_data_layer = MagicMock()
        mock_data_layer.create_step = AsyncMock()
        monkeypatch.setattr(pipeline, "get_data_layer_handler", lambda: mock_data_layer)

        message = MagicMock()
        message.id = "msg-1"
        message.metadata = {"location": "http://localhost"}
        message.to_dict.return_value = {"id": "msg-1", "metadata": {}}

        await pipeline._mark_message_processed(message)

        assert message.metadata["processed"] is True
        assert message.metadata["location"] == "http://localhost"

    @pytest.mark.asyncio
    async def test_workflow_init_takes_edit_branch_when_flag_in_memory(
        self, monkeypatch
    ) -> None:
        """``_workflow_init`` reads the flag off ``message.metadata``, so a
        same-session redelivery (flag already written in-memory) triggers
        the edit reset."""
        reset_called: list[str] = []

        async def mock_reset(thread_id: str) -> Any:
            reset_called.append(thread_id)
            return MagicMock()

        monkeypatch.setattr(pipeline, "_reset_memory_for_edit", mock_reset)
        monkeypatch.setattr(pipeline, "_sanitize_memory", AsyncMock())
        monkeypatch.setattr(
            pipeline, "handle_message", AsyncMock(return_value=("prompt", {}))
        )

        mock_memory = MagicMock()
        mock_memory.session_id = "thread-1"
        mock_session = {"memory": mock_memory}
        monkeypatch.setattr(
            pipeline.cl,
            "user_session",
            SimpleNamespace(
                get=lambda k: mock_session.get(k),
                set=lambda k, v: mock_session.__setitem__(k, v),
            ),
        )

        message = _mock_message(
            id="msg-1",
            content="Edited",
            thread_id="thread-1",
            metadata={"processed": True},
        )

        await pipeline._workflow_init(message)

        assert reset_called == ["thread-1"]

    @pytest.mark.asyncio
    async def test_edit_detected_when_processed_flag_set(self, monkeypatch) -> None:
        """on_message_handler detects edit via _aria_processed metadata."""
        # Track whether _reset_memory_for_edit was called
        reset_called = []
        mock_memory = MagicMock()
        mock_memory.session_id = "thread-1"
        mock_memory.aget = AsyncMock(return_value=[])
        mock_memory.set = MagicMock()

        async def mock_reset(thread_id):
            reset_called.append(thread_id)
            return mock_memory

        monkeypatch.setattr(pipeline, "_reset_memory_for_edit", mock_reset)
        monkeypatch.setattr(pipeline, "_mark_message_processed", AsyncMock())

        # Mock all the dependencies — use object.__setattr__ to bypass
        # Pydantic's frozen/strict __setattr__ on AppState.
        mock_workflow = MagicMock()
        object.__setattr__(pipeline._state, "agents_workflow", mock_workflow)
        object.__setattr__(
            pipeline._state,
            "validate_initialized",
            lambda: None,
        )

        # Mock handle_message
        monkeypatch.setattr(
            pipeline,
            "handle_message",
            AsyncMock(return_value=("prompt", {})),
        )

        # Mock user_session
        mock_session = {"memory": mock_memory}
        monkeypatch.setattr(
            pipeline.cl,
            "user_session",
            SimpleNamespace(
                get=lambda k: mock_session.get(k),
                set=lambda k, v: mock_session.__setitem__(k, v),
            ),
        )

        # Mock the workflow run + streaming
        monkeypatch.setattr(
            pipeline,
            "stream_agent_response",
            AsyncMock(return_value=(True, {}, "")),
        )

        mock_handler = MagicMock()
        workflow = pipeline._state.agents_workflow
        assert workflow is not None
        workflow.run = MagicMock(return_value=mock_handler)

        # Mock cl.Message for output
        mock_output = MagicMock()
        mock_output.send = AsyncMock()
        mock_output.update = AsyncMock()
        mock_output.remove = AsyncMock()
        monkeypatch.setattr(
            pipeline.cl,
            "Message",
            lambda **kw: mock_output,
        )
        monkeypatch.setattr(
            pipeline.cl,
            "ErrorMessage",
            lambda **kw: SimpleNamespace(send=AsyncMock()),
        )

        # Create message WITH processed (simulating edit)
        message = _mock_message(
            id="msg-1",
            content="Edited hello",
            command=None,
            thread_id="thread-1",
            elements=[],
            metadata={"processed": True},
        )

        await pipeline.on_message_handler(message)

        assert reset_called == ["thread-1"]

    @pytest.mark.asyncio
    async def test_no_reset_on_first_message(self, monkeypatch) -> None:
        """on_message_handler does NOT reset memory on first message."""
        reset_called = []

        async def mock_reset(thread_id):
            reset_called.append(thread_id)
            return MagicMock()

        monkeypatch.setattr(pipeline, "_reset_memory_for_edit", mock_reset)
        monkeypatch.setattr(pipeline, "_mark_message_processed", AsyncMock())

        mock_workflow = MagicMock()
        object.__setattr__(pipeline._state, "agents_workflow", mock_workflow)
        object.__setattr__(pipeline._state, "validate_initialized", lambda: None)
        monkeypatch.setattr(
            pipeline,
            "handle_message",
            AsyncMock(return_value=("prompt", {})),
        )

        mock_memory = MagicMock()
        mock_memory.session_id = "thread-1"
        mock_memory.aget = AsyncMock(return_value=[])
        mock_memory.set = MagicMock()
        mock_session = {"memory": mock_memory}
        monkeypatch.setattr(
            pipeline.cl,
            "user_session",
            SimpleNamespace(
                get=lambda k: mock_session.get(k),
                set=lambda k, v: mock_session.__setitem__(k, v),
            ),
        )

        monkeypatch.setattr(
            pipeline,
            "stream_agent_response",
            AsyncMock(return_value=(True, {}, "")),
        )

        mock_handler = MagicMock()
        workflow = pipeline._state.agents_workflow
        assert workflow is not None
        workflow.run = MagicMock(return_value=mock_handler)

        mock_output = MagicMock()
        mock_output.send = AsyncMock()
        mock_output.update = AsyncMock()
        mock_output.remove = AsyncMock()
        monkeypatch.setattr(
            pipeline.cl,
            "Message",
            lambda **kw: mock_output,
        )
        monkeypatch.setattr(
            pipeline.cl,
            "ErrorMessage",
            lambda **kw: SimpleNamespace(send=AsyncMock()),
        )

        # First message — no processed in metadata
        message = _mock_message(
            id="msg-1",
            content="Hello",
            command=None,
            thread_id="thread-1",
            elements=[],
            metadata={},
        )

        await pipeline.on_message_handler(message)

        assert reset_called == []

    @pytest.mark.asyncio
    async def test_sources_footer_goes_to_content_not_answer_text(
        self, monkeypatch
    ) -> None:
        """The Sources footer must land in output.content (what send() ships),
        while answer_text stays clean for the TTS side-channel."""
        from aria.config.models import Chat as ChatConfigCls

        monkeypatch.setattr(ChatConfigCls.__dict__["max_iteration"], "_value", 10)
        monkeypatch.setattr(pipeline, "_mark_message_processed", AsyncMock())
        object.__setattr__(pipeline._state, "agents_workflow", MagicMock())
        object.__setattr__(pipeline._state, "validate_initialized", lambda: None)
        monkeypatch.setattr(
            pipeline,
            "handle_message",
            AsyncMock(return_value=("prompt", {})),
        )
        monkeypatch.setattr(
            pipeline,
            "stream_agent_response",
            AsyncMock(return_value=(True, {}, "The company is Inferact.")),
        )
        monkeypatch.setattr(
            pipeline,
            "create_render_elements",
            AsyncMock(return_value=([SimpleNamespace(name="Inferact")], ["Inferact"])),
        )
        monkeypatch.setattr(
            pipeline.cl,
            "user_session",
            SimpleNamespace(
                get=lambda k: MagicMock(
                    session_id="thread-1",
                    aget=AsyncMock(return_value=[]),
                    aget_all=AsyncMock(return_value=[]),
                ),
                set=lambda k, v: None,
            ),
        )

        output = MagicMock()
        output.send = AsyncMock()
        output.update = AsyncMock()
        output.remove = AsyncMock()
        monkeypatch.setattr(pipeline.cl, "Message", lambda **kw: output)

        message = _mock_message(
            id="msg-1",
            content="who built vllm",
            command=None,
            thread_id="thread-1",
            elements=[],
            metadata={},
        )

        await pipeline.on_message_handler(message)

        assert output.content.endswith("**Sources:** Inferact")
        assert output.content.startswith("The company is Inferact.")
        assert "Sources" not in output.answer_text

    @pytest.mark.asyncio
    async def test_successful_stream_calls_send(self, monkeypatch) -> None:
        """A successful turn must call send() to persist the final message.

        The placeholder is no longer sent early — the message is created
        unsent and only appears in the timeline when the first content
        token streams (via stream_start), after thinking/tool steps.
        send() at the end persists it.
        """
        from aria.config.models import Chat as ChatConfigCls

        monkeypatch.setattr(ChatConfigCls.__dict__["max_iteration"], "_value", 10)
        monkeypatch.setattr(pipeline, "_mark_message_processed", AsyncMock())
        object.__setattr__(pipeline._state, "agents_workflow", MagicMock())
        object.__setattr__(pipeline._state, "validate_initialized", lambda: None)
        monkeypatch.setattr(
            pipeline,
            "handle_message",
            AsyncMock(return_value=("prompt", {})),
        )
        monkeypatch.setattr(
            pipeline,
            "stream_agent_response",
            AsyncMock(return_value=(True, {}, "")),
        )
        monkeypatch.setattr(
            pipeline.cl,
            "user_session",
            SimpleNamespace(
                get=lambda k: MagicMock(
                    session_id="thread-1",
                    aget=AsyncMock(return_value=[]),
                    aget_all=AsyncMock(return_value=[]),
                ),
                set=lambda k, v: None,
            ),
        )

        output = MagicMock()
        output.send = AsyncMock()
        output.update = AsyncMock()
        output.remove = AsyncMock()
        monkeypatch.setattr(pipeline.cl, "Message", lambda **kw: output)

        message = _mock_message(
            id="msg-1",
            content="Hello",
            command=None,
            thread_id="thread-1",
            elements=[],
            metadata={},
        )

        await pipeline.on_message_handler(message)

        output.send.assert_awaited_once()
        output.update.assert_not_awaited()
        output.remove.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_stream_before_tokens_skips_remove(self, monkeypatch) -> None:
        """A failed turn where no tokens were streamed must not call remove()
        (nothing to remove — the message was never sent to the frontend).

        A separate error cl.Message is sent by _fail_turn; that uses its own
        mock, so we only assert on the streaming output mock.
        """
        from aria.config.models import Chat as ChatConfigCls

        monkeypatch.setattr(ChatConfigCls.__dict__["max_iteration"], "_value", 10)
        mark_mock = AsyncMock()
        monkeypatch.setattr(pipeline, "_mark_message_processed", mark_mock)
        monkeypatch.setattr(pipeline, "_rollback_memory", AsyncMock())
        object.__setattr__(pipeline._state, "agents_workflow", MagicMock())
        object.__setattr__(pipeline._state, "validate_initialized", lambda: None)
        monkeypatch.setattr(
            pipeline,
            "handle_message",
            AsyncMock(return_value=("prompt", {})),
        )
        monkeypatch.setattr(
            pipeline,
            "stream_agent_response",
            AsyncMock(side_effect=RuntimeError("boom")),
        )
        monkeypatch.setattr(
            pipeline.cl,
            "user_session",
            SimpleNamespace(
                get=lambda k: MagicMock(
                    session_id="thread-1",
                    aget=AsyncMock(return_value=[]),
                    aget_all=AsyncMock(return_value=[]),
                ),
                set=lambda k, v: None,
            ),
        )

        outputs = []

        def _make_message(**kw):
            m = MagicMock()
            m.send = AsyncMock()
            m.update = AsyncMock()
            m.remove = AsyncMock()
            m.streaming = False
            outputs.append(m)
            return m

        monkeypatch.setattr(pipeline.cl, "Message", _make_message)
        monkeypatch.setattr(pipeline.cl, "ErrorMessage", _make_message)

        message = _mock_message(
            id="msg-1",
            content="Hello",
            command=None,
            thread_id="thread-1",
            elements=[],
            metadata={},
        )

        await pipeline.on_message_handler(message)

        # First Message is the unsent streaming output; the second is the
        # error notice sent by _fail_turn.
        streaming_output = outputs[0]
        streaming_output.send.assert_not_awaited()
        streaming_output.remove.assert_not_awaited()
        streaming_output.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_truncated_stream_persists_partial_output(self, monkeypatch) -> None:
        """When the stream is interrupted after tokens were emitted, the
        partial output must be persisted via send() so it survives reload.
        The user message marking is left to _fail_turn.
        """
        from aria.config.models import Chat as ChatConfigCls

        monkeypatch.setattr(ChatConfigCls.__dict__["max_iteration"], "_value", 10)
        monkeypatch.setattr(pipeline, "_mark_message_processed", AsyncMock())
        monkeypatch.setattr(pipeline, "_rollback_memory", AsyncMock())
        object.__setattr__(pipeline._state, "agents_workflow", MagicMock())
        object.__setattr__(pipeline._state, "validate_initialized", lambda: None)
        monkeypatch.setattr(
            pipeline,
            "handle_message",
            AsyncMock(return_value=("prompt", {})),
        )

        async def _raise_with_partial(handler, output):
            output.answer_text = "partial answer"  # type: ignore[attr-defined]
            raise RuntimeError("max tokens reached")

        monkeypatch.setattr(pipeline, "stream_agent_response", _raise_with_partial)
        monkeypatch.setattr(
            pipeline.cl,
            "user_session",
            SimpleNamespace(
                get=lambda k: MagicMock(
                    session_id="thread-1",
                    aget=AsyncMock(return_value=[]),
                    aget_all=AsyncMock(return_value=[]),
                ),
                set=lambda k, v: None,
            ),
        )

        output = MagicMock()
        output.send = AsyncMock()
        output.update = AsyncMock()
        output.remove = AsyncMock()
        output.streaming = True
        output.content = "partial answer"
        error_msg = MagicMock()
        error_msg.send = AsyncMock()

        def _make_message(**kw):
            if kw.get("content") == "":
                return output
            return error_msg

        monkeypatch.setattr(pipeline.cl, "Message", _make_message)
        monkeypatch.setattr(pipeline.cl, "ErrorMessage", _make_message)

        message = _mock_message(
            id="msg-1",
            content="Hello",
            command=None,
            thread_id="thread-1",
            elements=[],
            metadata={},
        )

        await pipeline.on_message_handler(message)

        output.send.assert_awaited_once()
        output.remove.assert_not_awaited()


class TestOnMessageHandlerReturn:
    """Tests for the `on_message_handler` return value (voice TTS capture)."""

    @pytest.mark.asyncio
    async def test_success_path_returns_output_message(self, monkeypatch) -> None:
        """The success path returns the assistant cl.Message with content."""
        from aria.config.models import Chat as ChatConfigCls

        monkeypatch.setattr(ChatConfigCls.__dict__["max_iteration"], "_value", 10)
        monkeypatch.setattr(pipeline, "_mark_message_processed", AsyncMock())
        monkeypatch.setattr(pipeline, "_maybe_rename_thread", MagicMock())
        object.__setattr__(pipeline._state, "agents_workflow", MagicMock())
        object.__setattr__(pipeline._state, "validate_initialized", lambda: None)
        monkeypatch.setattr(
            pipeline,
            "handle_message",
            AsyncMock(return_value=("prompt", {})),
        )
        monkeypatch.setattr(
            pipeline,
            "stream_agent_response",
            AsyncMock(return_value=(True, {}, "")),
        )

        mock_memory = MagicMock()
        mock_memory.session_id = "thread-1"
        mock_memory.aget = AsyncMock(return_value=[])
        mock_memory.aget_all = AsyncMock(return_value=[])
        mock_session = {"memory": mock_memory}
        monkeypatch.setattr(
            cl,
            "user_session",
            SimpleNamespace(
                get=lambda k: mock_session.get(k),
                set=lambda k, v: mock_session.__setitem__(k, v),
            ),
        )

        mock_output = MagicMock()
        mock_output.send = AsyncMock()
        mock_output.update = AsyncMock()
        mock_output.remove = AsyncMock()
        mock_output.content = "Final answer"
        monkeypatch.setattr(cl, "Message", lambda **kw: mock_output)

        message = _mock_message(
            id="msg-1",
            content="Hello",
            command=None,
            thread_id="thread-1",
            elements=[],
            metadata={},
        )

        result = await pipeline.on_message_handler(message)
        assert result is mock_output
        assert result is not None
        assert result.content == "Final answer"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_initialized(self, monkeypatch) -> None:
        """When the workflow is missing, the handler returns None."""
        object.__setattr__(pipeline._state, "agents_workflow", None)
        monkeypatch.setattr(pipeline, "_warn_not_initialized", AsyncMock())
        result = await pipeline.on_message_handler(MagicMock())
        assert result is None


class TestStreamAndFinalize:
    """Tests for the success/finalization semantics of the message pipeline."""

    @pytest.mark.asyncio
    async def test_render_failure_still_marks_processed(self, monkeypatch) -> None:
        """A streamed-complete answer is a successful turn even if element
        building fails: the message is still marked processed so a retry
        does not re-run against already-completed memory.

        Args:
            monkeypatch: pytest monkeypatch fixture.
        """
        monkeypatch.setattr(pipeline, "ChatConfig", SimpleNamespace(max_iteration=10))
        monkeypatch.setattr(pipeline, "_rollback_memory", AsyncMock())
        monkeypatch.setattr(pipeline._state, "agents_workflow", MagicMock())
        monkeypatch.setattr(
            pipeline._state.__class__, "validate_initialized", lambda self: None
        )
        monkeypatch.setattr(
            pipeline, "handle_message", AsyncMock(return_value=("prompt", {}))
        )
        monkeypatch.setattr(
            pipeline,
            "stream_agent_response",
            AsyncMock(return_value=(True, {}, "The answer")),
        )
        monkeypatch.setattr(
            pipeline,
            "create_render_elements",
            AsyncMock(side_effect=RuntimeError("network down")),
        )
        monkeypatch.setattr("aria.web.supervisor.ensure_watching", AsyncMock())
        monkeypatch.setattr(
            pipeline.cl,
            "user_session",
            SimpleNamespace(
                get=lambda k: MagicMock(
                    session_id="thread-1",
                    aget=AsyncMock(return_value=[]),
                    aget_all=AsyncMock(return_value=[]),
                ),
                set=lambda k, v: None,
            ),
        )

        output = MagicMock()
        output.send = AsyncMock()
        output.update = AsyncMock()
        output.remove = AsyncMock()
        monkeypatch.setattr(pipeline.cl, "Message", lambda **kw: output)

        message = _mock_message(
            id="msg-1",
            content="who built vllm",
            command=None,
            thread_id="thread-1",
            elements=[],
            metadata={},
        )

        # Must not raise despite the render failure.
        await pipeline.on_message_handler(message)

        assert output.answer_text == "The answer"
        output.send.assert_awaited_once()


class TestMaybeRenameThread:
    """Tests for the titler's answer source."""

    @pytest.mark.asyncio
    async def test_uses_clean_answer_text_not_content(self, monkeypatch) -> None:
        """The titler receives the clean ``answer_text`` (no ``**Sources:**``
        footer that lives only in ``output.content``)."""
        captured: list[dict] = []

        async def fake_title(**kwargs: Any) -> None:
            captured.append(kwargs)

        monkeypatch.setattr(pipeline, "maybe_title_thread", fake_title)

        user_session: dict[str, Any] = {}
        monkeypatch.setattr(
            pipeline.cl,
            "user_session",
            SimpleNamespace(
                get=lambda k: user_session.get(k),
                set=lambda k, v: user_session.__setitem__(k, v),
            ),
        )

        output = MagicMock()
        output.content = "The answer **Sources:** Inferact"
        output.answer_text = "The answer"
        message = _mock_message(id="msg-1", content="q", thread_id="t1", metadata={})

        pipeline._maybe_rename_thread(message, output)

        task = user_session["_pending_title_task"]
        await task

        assert captured[0]["assistant_reply"] == "The answer"
        assert "Sources" not in captured[0]["assistant_reply"]
