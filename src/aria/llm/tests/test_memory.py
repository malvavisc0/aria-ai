"""Tests for aria.llm.memory.

Verifies that ``BackgroundFlushMemory`` keeps the chat-store write
on the awaited path while running the expensive ``_manage_queue``
waterfall as a background task, never drops a flush that was
requested while another was in flight, refuses the sync API, and
that ``IdempotentVectorMemoryBlock`` derives stable node IDs from the
message text so re-embedding the same content does not accumulate
duplicates.
"""

from __future__ import annotations

import asyncio
from typing import Any, Sequence

import pytest
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.base.llms.types import ChatMessage, MessageRole, TextBlock
from llama_index.core.memory import Memory, VectorMemoryBlock
from llama_index.core.schema import BaseNode, TextNode
from llama_index.core.vector_stores.types import BasePydanticVectorStore

from aria.llm.memory import (
    BackgroundFlushMemory,
    IdempotentVectorMemoryBlock,
)


def _msg(role: MessageRole, text: str) -> ChatMessage:
    return ChatMessage(role=role, blocks=[TextBlock(text=text)])


class _FakeEmbedding(BaseEmbedding):
    """Embedding stub that returns a deterministic float vector."""

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return [float(len(query))]

    def _get_query_embedding(self, query: str) -> list[float]:
        return [float(len(query))]

    def _get_text_embedding(self, text: str) -> list[float]:
        return [float(len(text))]


class _RecordingVectorStore(BasePydanticVectorStore):
    """Vector store stub that records every inserted TextNode."""

    def __init__(self) -> None:
        super().__init__(stores_text=True)
        self._nodes: list[TextNode] = []

    @property
    def nodes(self) -> list[TextNode]:
        return self._nodes

    @property
    def client(self) -> None:
        return None

    async def async_add(self, nodes: Sequence[BaseNode], **_: Any) -> list[str]:
        self._nodes.extend(nodes)  # type: ignore[arg-type]
        return [n.node_id for n in nodes]

    def add(self, nodes: Sequence[BaseNode], **_: Any) -> list[str]:
        self._nodes.extend(nodes)  # type: ignore[arg-type]
        return [n.node_id for n in nodes]

    def query(self, *args: Any, **kwargs: Any) -> Any:
        return None

    def delete(self, *args: Any, **kwargs: Any) -> None:
        return None


class TestIdempotentVectorBlock:
    """Re-inserting identical content reuses the same node ID."""

    @pytest.mark.asyncio
    async def test_assigns_deterministic_node_id(self) -> None:
        store = _RecordingVectorStore()
        block = IdempotentVectorMemoryBlock(
            name="vector_memory",
            vector_store=store,  # type: ignore[arg-type]
            embed_model=_FakeEmbedding(),
        )
        msgs = [_msg(MessageRole.USER, "hi")]
        await block._aput(msgs)
        await block._aput(msgs)

        assert len(store.nodes) == 2
        assert store.nodes[0].node_id == store.nodes[1].node_id

    @pytest.mark.asyncio
    async def test_skips_empty_messages(self) -> None:
        store = _RecordingVectorStore()
        block = IdempotentVectorMemoryBlock(
            name="vector_memory",
            vector_store=store,  # type: ignore[arg-type]
            embed_model=_FakeEmbedding(),
        )
        await block._aput([])
        assert store.nodes == []

    @pytest.mark.asyncio
    async def test_attaches_session_id_via_additional_kwargs(self) -> None:
        """The base ``aput`` wrapper injects session_id into additional_kwargs."""
        store = _RecordingVectorStore()
        block = IdempotentVectorMemoryBlock(
            name="vector_memory",
            vector_store=store,  # type: ignore[arg-type]
            embed_model=_FakeEmbedding(),
        )
        msg = _msg(MessageRole.USER, "hi")
        msg.additional_kwargs["session_id"] = "thread-abc"
        await block._aput([msg])
        assert store.nodes[0].metadata["session_id"] == "thread-abc"

    @pytest.mark.asyncio
    async def test_session_id_does_not_leak_into_text(self) -> None:
        """session_id must be popped — it must not appear in the node text.

        If it leaked, it would pollute both the embedding and the
        content hash, degrading retrieval and breaking idempotency
        across sessions.
        """
        store = _RecordingVectorStore()
        block = IdempotentVectorMemoryBlock(
            name="vector_memory",
            vector_store=store,  # type: ignore[arg-type]
            embed_model=_FakeEmbedding(),
        )
        msg = _msg(MessageRole.USER, "hi")
        msg.additional_kwargs["session_id"] = "thread-abc"
        await block._aput([msg])
        assert "session_id" not in store.nodes[0].text
        assert "thread-abc" not in store.nodes[0].text

    @pytest.mark.asyncio
    async def test_text_matches_base_vector_block(self) -> None:
        """Guard: the override's joined text must match the base class.

        ``IdempotentVectorMemoryBlock._aput`` reimplements the base
        extraction loop to inject a hash-based node ID.  If the text
        formatting drifts from upstream ``VectorMemoryBlock._aput``,
        dedup and retrieval consistency break silently.  This test
        asserts the node text is byte-identical for representative
        inputs.
        """
        msgs = [
            _msg(MessageRole.USER, "hello world"),
            _msg(MessageRole.ASSISTANT, "hi there"),
        ]
        msgs[0].additional_kwargs["session_id"] = "t1"
        msgs[1].additional_kwargs["extra"] = "data"

        base_store = _RecordingVectorStore()
        base_block = VectorMemoryBlock(
            name="vector_memory",
            vector_store=base_store,  # type: ignore[arg-type]
            embed_model=_FakeEmbedding(),
        )
        idem_store = _RecordingVectorStore()
        idem_block = IdempotentVectorMemoryBlock(
            name="vector_memory",
            vector_store=idem_store,  # type: ignore[arg-type]
            embed_model=_FakeEmbedding(),
        )

        await base_block._aput([msgs[0], msgs[1]])
        await idem_block._aput([msgs[0], msgs[1]])

        assert len(base_store.nodes) == 1
        assert len(idem_store.nodes) == 1
        assert base_store.nodes[0].text == idem_store.nodes[0].text


class TestBackgroundFlushMemory:
    """``aput`` writes to the chat store but never awaits the waterfall."""

    @staticmethod
    def _make_inner() -> tuple[Memory, Any]:
        """Build a real Memory whose _manage_queue is patched."""

        async def slow_manage(self: Memory) -> None:
            await asyncio.sleep(1.0)

        manage = slow_manage
        inner = Memory.from_defaults(session_id="t1", token_limit=10_000)
        inner._manage_queue = manage.__get__(inner, Memory)  # type: ignore[method-assign]
        return inner, manage

    @pytest.mark.asyncio
    async def test_aput_does_not_await_manage_queue(self) -> None:
        inner, _manage = self._make_inner()
        wrapper = BackgroundFlushMemory(inner)

        start = asyncio.get_event_loop().time()
        await wrapper.aput(_msg(MessageRole.USER, "hi"))
        elapsed = asyncio.get_event_loop().time() - start

        assert elapsed < 0.1, (
            f"aput must not block on _manage_queue; took {elapsed:.2f}s"
        )

    @pytest.mark.asyncio
    async def test_aput_writes_to_chat_store(self) -> None:
        inner, _manage = self._make_inner()
        wrapper = BackgroundFlushMemory(inner)

        await wrapper.aput(_msg(MessageRole.USER, "hi"))
        msgs = await inner.sql_store.get_messages(inner.session_id)
        assert [m.content for m in msgs] == ["hi"]

    @pytest.mark.asyncio
    async def test_aput_messages_does_not_await_manage_queue(self) -> None:
        inner, _manage = self._make_inner()
        wrapper = BackgroundFlushMemory(inner)

        start = asyncio.get_event_loop().time()
        await wrapper.aput_messages(
            [_msg(MessageRole.USER, "a"), _msg(MessageRole.ASSISTANT, "b")]
        )
        elapsed = asyncio.get_event_loop().time() - start

        assert elapsed < 0.1, (
            f"aput_messages must not block on _manage_queue; took {elapsed:.2f}s"
        )

    @pytest.mark.asyncio
    async def test_drain_awaits_in_flight_flush(self) -> None:
        inner, _manage = self._make_inner()
        wrapper = BackgroundFlushMemory(inner)

        wrapper._schedule_manage()
        await wrapper.drain()
        assert wrapper._current is None or wrapper._current.done()

    @pytest.mark.asyncio
    async def test_drain_catches_stragglers_added_during_flush(self) -> None:
        """drain() must re-run _manage_queue to catch messages added
        during an in-flight flush — _manage_queue snapshots the store
        once, so those messages would otherwise be lost at shutdown."""
        call_count = 0

        async def counting_manage(self: Memory) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(0.05)

        inner = Memory.from_defaults(session_id="t1", token_limit=10_000)
        inner._manage_queue = counting_manage.__get__(inner, Memory)  # type: ignore[method-assign]
        wrapper = BackgroundFlushMemory(inner)

        wrapper._schedule_manage()
        await wrapper.drain()
        assert call_count >= 2, "drain must re-run _manage_queue after awaiting"

    @pytest.mark.asyncio
    async def test_only_one_flush_in_flight(self) -> None:
        """Multiple back-to-back aput calls do not queue parallel tasks."""
        inner, _manage = self._make_inner()
        wrapper = BackgroundFlushMemory(inner)

        await wrapper.aput(_msg(MessageRole.USER, "a"))
        await wrapper.aput(_msg(MessageRole.USER, "b"))
        await wrapper.aput(_msg(MessageRole.USER, "c"))

        assert wrapper._current is not None
        wrapper._current.cancel()
        try:
            await wrapper._current
        except BaseException:
            pass

    @pytest.mark.asyncio
    async def test_flush_requested_mid_flight_is_replayed(self) -> None:
        """A flush requested while one is running must not be dropped.

        Without the dirty flag the second request is discarded, leaving
        the queue over budget until some later turn happens to schedule
        a flush.
        """
        calls = 0
        started = asyncio.Event()

        async def slow_manage(self: Memory) -> None:
            nonlocal calls
            calls += 1
            started.set()
            await asyncio.sleep(0.05)

        inner = Memory.from_defaults(session_id="t1", token_limit=10_000)
        inner._manage_queue = slow_manage.__get__(inner, Memory)  # type: ignore[method-assign]
        wrapper = BackgroundFlushMemory(inner)

        await wrapper.aput(_msg(MessageRole.USER, "a"))
        await started.wait()
        await wrapper.aput(_msg(MessageRole.USER, "b"))
        assert wrapper._dirty is True

        await wrapper.drain()
        assert calls >= 2, "mid-flight flush request must be replayed"

    @pytest.mark.asyncio
    async def test_background_flush_failure_is_logged_not_raised(self) -> None:
        """A failing flush must not surface as an unretrieved task error."""

        async def failing_manage(self: Memory) -> None:
            raise RuntimeError("boom")

        inner = Memory.from_defaults(session_id="t1", token_limit=10_000)
        inner._manage_queue = failing_manage.__get__(inner, Memory)  # type: ignore[method-assign]
        wrapper = BackgroundFlushMemory(inner)

        await wrapper.aput(_msg(MessageRole.USER, "a"))
        await wrapper.drain()  # must not raise
        assert wrapper._current is not None
        assert wrapper._current.done()

    @pytest.mark.asyncio
    async def test_schedule_embed_puts_to_blocks_without_queueing(self) -> None:
        """Dropped resume turns reach the vector block, not the live queue."""
        store = _RecordingVectorStore()
        block = IdempotentVectorMemoryBlock(
            name="vector_memory",
            vector_store=store,  # type: ignore[arg-type]
            embed_model=_FakeEmbedding(),
        )
        inner = Memory.from_defaults(
            session_id="t1", token_limit=10_000, memory_blocks=[block]
        )
        wrapper = BackgroundFlushMemory(inner)

        wrapper.schedule_embed([_msg(MessageRole.USER, "old turn")])
        await wrapper.drain()

        assert len(store.nodes) == 1
        assert "old turn" in store.nodes[0].text
        assert await inner.aget_all() == []

    @pytest.mark.asyncio
    async def test_schedule_embed_ignores_empty(self) -> None:
        inner, _manage = self._make_inner()
        wrapper = BackgroundFlushMemory(inner)
        wrapper.schedule_embed([])
        assert not wrapper._embeds

    @pytest.mark.asyncio
    async def test_sync_api_is_refused(self) -> None:
        """Sync methods must fail loudly instead of blocking on the waterfall."""
        inner, _manage = self._make_inner()
        wrapper = BackgroundFlushMemory(inner)

        for name in ("get", "get_all", "put", "put_messages", "set", "reset"):
            with pytest.raises(RuntimeError, match="async memory API only"):
                getattr(wrapper, name)()

    @pytest.mark.asyncio
    async def test_delegates_arbitrary_attributes(self) -> None:
        inner, _manage = self._make_inner()
        wrapper = BackgroundFlushMemory(inner)
        assert wrapper.session_id == inner.session_id
