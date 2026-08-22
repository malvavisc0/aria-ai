from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aria.web import session as pipeline


class _FakeMemory:
    """In-memory fake Memory for sanitize/rollback tests.

    Backed by a list; supports the ``aget``/``aget_all``/``aset``
    contract that ``_sanitize_memory`` and ``_rollback_memory`` use.
    """

    def __init__(self, msgs: Any = ()) -> None:
        self._msgs = list(msgs)

    async def aget(self, input: Any = None) -> list:
        return list(self._msgs)

    async def aget_all(self, status: Any = None) -> list:
        return list(self._msgs)

    async def aset(self, messages: Any) -> None:
        self._msgs = list(messages)


class TestSanitizeMemory:
    """Tests for the _sanitize_memory helper."""

    @staticmethod
    def _make_memory(*messages) -> Any:
        """Build a fake Memory backed by an in-memory list."""
        return _FakeMemory(messages)

    @pytest.mark.asyncio
    async def test_empty_memory_is_noop(self) -> None:

        memory = self._make_memory()
        await pipeline._sanitize_memory(memory)
        assert await memory.aget() == []

    @pytest.mark.asyncio
    async def test_already_alternating_is_unchanged(self) -> None:
        from llama_index.core.base.llms.types import ChatMessage, MessageRole

        msgs = [
            ChatMessage(role=MessageRole.USER, content="hi"),
            ChatMessage(role=MessageRole.ASSISTANT, content="hello"),
        ]
        memory = self._make_memory(*msgs)
        await pipeline._sanitize_memory(memory)
        result = await memory.aget()
        assert len(result) == 2
        assert result[0].content == "hi"
        assert result[1].content == "hello"

    @pytest.mark.asyncio
    async def test_consecutive_user_messages_collapsed(self) -> None:
        from llama_index.core.base.llms.types import ChatMessage, MessageRole

        msgs = [
            ChatMessage(role=MessageRole.USER, content="first"),
            ChatMessage(role=MessageRole.USER, content="second"),
            ChatMessage(role=MessageRole.ASSISTANT, content="reply"),
        ]
        memory = self._make_memory(*msgs)
        await pipeline._sanitize_memory(memory)
        result = await memory.aget()
        assert [m.content for m in result] == ["second", "reply"]

    @pytest.mark.asyncio
    async def test_trailing_user_message_removed(self) -> None:
        """A dangling user message from a failed run is dropped."""
        from llama_index.core.base.llms.types import ChatMessage, MessageRole

        msgs = [
            ChatMessage(role=MessageRole.USER, content="q"),
            ChatMessage(role=MessageRole.ASSISTANT, content="a"),
            ChatMessage(role=MessageRole.USER, content="unanswered"),
        ]
        memory = self._make_memory(*msgs)
        await pipeline._sanitize_memory(memory)
        result = await memory.aget()
        assert [m.content for m in result] == ["q", "a"]

    @pytest.mark.asyncio
    async def test_round_trip_preserves_aget_all_when_already_valid(self) -> None:
        """Regression: sanitize must read the raw chat store, not the rendered one.

        If ``aget()`` (which splices the retrieved vector context into the
        last user message) were read and ``set()`` were written, the
        injected blob would be persisted permanently and grow unbounded
        across repairs.  Reading ``aget_all()`` + writing ``aset()``
        leaves valid history byte-identical.
        """
        from llama_index.core.base.llms.types import ChatMessage, MessageRole

        msgs = [
            ChatMessage(role=MessageRole.USER, content="q1"),
            ChatMessage(role=MessageRole.ASSISTANT, content="a1"),
            ChatMessage(role=MessageRole.USER, content="q2"),
            ChatMessage(role=MessageRole.ASSISTANT, content="a2"),
        ]
        memory = self._make_memory(*msgs)
        before = await memory.aget_all()
        await pipeline._sanitize_memory(memory)
        after = await memory.aget_all()
        assert [m.content for m in after] == [m.content for m in before]
        assert [m.role for m in after] == [m.role for m in before]

    @pytest.mark.asyncio
    async def test_repair_never_grows_message_length(self) -> None:
        """Regression: no message should grow across a sanitize round-trip."""
        from llama_index.core.base.llms.types import ChatMessage, MessageRole

        msgs = [
            ChatMessage(role=MessageRole.USER, content="q"),
            ChatMessage(role=MessageRole.ASSISTANT, content="a"),
        ]
        memory = self._make_memory(*msgs)
        before_lens = [len(m.content or "") for m in await memory.aget_all()]
        await pipeline._sanitize_memory(memory)
        after_lens = [len(m.content or "") for m in await memory.aget_all()]
        assert after_lens == before_lens


class TestRollbackMemory:
    """Tests for the _rollback_memory helper."""

    @staticmethod
    def _make_memory(*messages) -> Any:
        return _FakeMemory(messages)

    @pytest.mark.asyncio
    async def test_none_memory_is_noop(self) -> None:
        # Should not raise
        await pipeline._rollback_memory(None)

    @pytest.mark.asyncio
    async def test_empty_memory_is_noop(self) -> None:
        memory = self._make_memory()
        await pipeline._rollback_memory(memory)
        assert await memory.aget() == []

    @pytest.mark.asyncio
    async def test_removes_trailing_user_message(self) -> None:
        from llama_index.core.base.llms.types import ChatMessage, MessageRole

        msgs = [
            ChatMessage(role=MessageRole.USER, content="q"),
            ChatMessage(role=MessageRole.ASSISTANT, content="a"),
            ChatMessage(role=MessageRole.USER, content="dangling"),
        ]
        memory = self._make_memory(*msgs)
        await pipeline._rollback_memory(memory)
        result = await memory.aget()
        assert [m.content for m in result] == ["q", "a"]

    @pytest.mark.asyncio
    async def test_leaves_valid_alternation_unchanged(self) -> None:
        from llama_index.core.base.llms.types import ChatMessage, MessageRole

        msgs = [
            ChatMessage(role=MessageRole.USER, content="q"),
            ChatMessage(role=MessageRole.ASSISTANT, content="a"),
        ]
        memory = self._make_memory(*msgs)
        await pipeline._rollback_memory(memory)
        result = await memory.aget()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_round_trip_preserves_aget_all_when_already_valid(self) -> None:
        """Regression: rollback reads raw chat store, never grows messages."""
        from llama_index.core.base.llms.types import ChatMessage, MessageRole

        msgs = [
            ChatMessage(role=MessageRole.USER, content="q1"),
            ChatMessage(role=MessageRole.ASSISTANT, content="a1"),
        ]
        memory = self._make_memory(*msgs)
        before = await memory.aget_all()
        await pipeline._rollback_memory(memory)
        after = await memory.aget_all()
        assert [m.content for m in after] == [m.content for m in before]


class TestResetMemoryForEdit:
    """Tests for _reset_memory_for_edit — memory rebuild on message edit."""

    @pytest.mark.asyncio
    async def test_rebuilds_memory_from_db(self, monkeypatch) -> None:
        """_reset_memory_for_edit rebuilds memory from DB."""
        mock_vector_db = MagicMock()
        monkeypatch.setattr(pipeline._state, "vector_db", mock_vector_db)

        mock_memory = MagicMock()
        monkeypatch.setattr(pipeline, "create_memory", lambda tid: mock_memory)

        mock_thread = {
            "id": "thread-1",
            "name": "Test",
            "steps": [],
        }
        mock_data_layer = MagicMock()
        mock_data_layer.get_thread = AsyncMock(return_value=mock_thread)
        from aria.web import hooks

        monkeypatch.setattr(
            hooks,
            "get_data_layer_handler",
            lambda: mock_data_layer,
        )

        restored_memory = MagicMock()
        monkeypatch.setattr(
            pipeline,
            "restore_chat_history",
            AsyncMock(return_value=restored_memory),
        )

        result = await pipeline._reset_memory_for_edit("thread-1")

        mock_vector_db.delete_collection.assert_called_once_with("thread-1")
        mock_data_layer.get_thread.assert_awaited_once_with("thread-1")
        assert result is restored_memory

    @pytest.mark.asyncio
    async def test_raises_when_thread_missing(self, monkeypatch) -> None:
        """A missing thread aborts the edit instead of returning empty memory."""
        mock_vector_db = MagicMock()
        monkeypatch.setattr(pipeline._state, "vector_db", mock_vector_db)

        mock_memory = MagicMock()
        monkeypatch.setattr(pipeline, "create_memory", lambda tid: mock_memory)

        mock_data_layer = MagicMock()
        mock_data_layer.get_thread = AsyncMock(return_value=None)
        from aria.web import hooks

        monkeypatch.setattr(
            hooks,
            "get_data_layer_handler",
            lambda: mock_data_layer,
        )

        with pytest.raises(pipeline._EditThreadMissingError):
            await pipeline._reset_memory_for_edit("ghost-thread")

        mock_vector_db.delete_collection.assert_called_once_with("ghost-thread")


class TestStepToChatMessage:
    """Tests for _step_to_chat_message error handling."""

    def test_returns_none_for_error_step(self) -> None:
        """A persisted error notice must not enter restored memory."""
        assert (
            pipeline._step_to_chat_message({"isError": True, "output": "err"}) is None
        )

    def test_returns_message_for_normal_step(self) -> None:
        from llama_index.core.base.llms.types import MessageRole

        msg = pipeline._step_to_chat_message(
            {"type": "assistant_message", "output": "hi"}
        )
        assert msg is not None
        assert msg.role == MessageRole.ASSISTANT
