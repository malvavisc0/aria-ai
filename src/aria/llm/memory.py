"""Background memory flushing and idempotent vector nodes.

The default ``llama_index.core.memory.Memory`` runs ``_manage_queue``
synchronously inside every ``aput``/``aput_messages`` call.  The
waterfall flushes the oldest turns to vector storage, which costs
~18s per batch on the UI critical path because it embeds 4k-token
chunks on CPU.

This module wraps the live ``Memory`` instance so:

- ``aput``/``aput_messages`` only await the cheap chat-store write
  (``sql_store.add_messages``) and schedule the expensive
  ``_manage_queue`` waterfall as a background ``asyncio`` task.
- The vector memory block is replaced by an idempotent subclass that
  derives its node ID from a SHA-256 of the message text, so
  re-embedding the same content does not accumulate duplicates.

At most one flush runs at a time.  Requests that arrive while a flush
is in flight set a dirty flag and are re-scheduled when it completes,
so a flush is never silently dropped.  Background failures are logged.
Use :meth:`BackgroundFlushMemory.drain` before discarding a memory
instance (session end, thread switch, edit reset) to await outstanding
work — otherwise the pending turns are never embedded.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any, NoReturn

from llama_index.core.base.llms.types import ChatMessage
from llama_index.core.memory import Memory, VectorMemoryBlock
from llama_index.core.schema import TextNode
from llama_index.core.storage.chat_store.base_db import MessageStatus
from loguru import logger

# Upper bound on drain re-scheduling rounds.  Each round awaits one
# in-flight flush; the dirty flag can only re-arm while messages are
# still arriving, so a small bound is enough and guarantees shutdown
# cannot hang.
_DRAIN_MAX_ROUNDS = 5

_SYNC_UNSUPPORTED = (
    "BackgroundFlushMemory exposes the async memory API only: the sync "
    "{name}() would delegate straight to Memory and run the ~18s embedding "
    "waterfall on the calling thread.  Use a{name}() instead."
)


def _hash_node_id(text: str) -> str:
    """Stable node ID derived from message text.

    Same content always hashes to the same ID.  Chroma's ``add``
    ignores an insert whose ID already exists (keeping the stored
    document), so re-embedding identical text is a no-op instead of
    appending yet another copy — which is what the upstream
    ``VectorMemoryBlock._aput`` does, since it builds a ``TextNode``
    with a freshly generated ID.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class IdempotentVectorMemoryBlock(VectorMemoryBlock):
    """Vector memory block whose nodes are keyed by content hash.

    Re-inserting identical content is idempotent — the deterministic
    ``node_id`` collides with the existing node instead of creating a
    new one, so the collection stops growing without bound across
    sessions.
    """

    async def _aput(self, messages: list[ChatMessage]) -> None:
        nodes: list[TextNode] = []
        session_id = None
        for message in messages:
            text = self._get_text_from_messages([message])
            if not text:
                continue

            # Pop session_id so it never enters the embedded/hashed text —
            # matches the base VectorMemoryBlock._aput behaviour.
            if "session_id" in message.additional_kwargs:
                session_id = message.additional_kwargs.pop("session_id")

            if message.additional_kwargs:
                text += f"\nAdditional Info: ({message.additional_kwargs!s})"

            text = f"<message role='{message.role.value}'>{text}</message>"
            nodes.append(
                TextNode(
                    text=text,
                    metadata={"session_id": session_id},
                    id_=_hash_node_id(text),
                )
            )

        if not nodes:
            return

        embeddings = await self.embed_model.aget_text_embedding_batch(
            [n.text for n in nodes]
        )
        for node, emb in zip(nodes, embeddings):
            node.embedding = emb
        await self.vector_store.async_add(nodes)


class BackgroundFlushMemory:
    """Wrap a ``Memory`` so waterfall flushing runs off the UI critical path.

    ``aput`` and ``aput_messages`` await only the chat-store write and
    dispatch ``_manage_queue`` as a background task the caller never
    waits on.  One flush runs at a time; concurrent requests set a
    dirty flag and are re-scheduled on completion.

    Call :meth:`drain` before dropping the instance so outstanding
    embedding work is not lost.
    """

    def __init__(self, memory: Memory) -> None:
        self._memory = memory
        self._current: asyncio.Task | None = None
        self._dirty = False
        self._embeds: set[asyncio.Task] = set()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._memory, name)

    # ---- async API (the only supported one) ----

    async def aput(self, message: ChatMessage) -> None:
        await self._memory.sql_store.add_message(
            self._memory.session_id, message, status=MessageStatus.ACTIVE
        )
        self._schedule_manage()

    async def aput_messages(self, messages: list[ChatMessage]) -> None:
        await self._memory.sql_store.add_messages(
            self._memory.session_id, messages, status=MessageStatus.ACTIVE
        )
        self._schedule_manage()

    async def aset(self, messages: list[ChatMessage]) -> None:
        await self._memory.aset(messages)

    async def aget(
        self, input: str | None = None, **block_kwargs: Any
    ) -> list[ChatMessage]:
        return await self._memory.aget(input, **block_kwargs)

    async def aget_all(self) -> list[ChatMessage]:
        return await self._memory.aget_all()

    async def areset(self) -> None:
        await self._memory.areset()

    # ---- sync API is refused rather than silently blocking ----

    def get(self, *_args: Any, **_kwargs: Any) -> NoReturn:
        raise RuntimeError(_SYNC_UNSUPPORTED.format(name="get"))

    def get_all(self, *_args: Any, **_kwargs: Any) -> NoReturn:
        raise RuntimeError(_SYNC_UNSUPPORTED.format(name="get_all"))

    def put(self, *_args: Any, **_kwargs: Any) -> NoReturn:
        raise RuntimeError(_SYNC_UNSUPPORTED.format(name="put"))

    def put_messages(self, *_args: Any, **_kwargs: Any) -> NoReturn:
        raise RuntimeError(_SYNC_UNSUPPORTED.format(name="put_messages"))

    def set(self, *_args: Any, **_kwargs: Any) -> NoReturn:
        raise RuntimeError(_SYNC_UNSUPPORTED.format(name="set"))

    def reset(self, *_args: Any, **_kwargs: Any) -> NoReturn:
        raise RuntimeError(_SYNC_UNSUPPORTED.format(name="reset"))

    # ---- background flushing ----

    def _schedule_manage(self) -> None:
        """Schedule ``_manage_queue``, or mark it pending if one is running.

        The dirty flag is what stops a flush from being dropped: a
        request that arrives mid-flush is replayed by
        :meth:`_on_flush_done` instead of being discarded.
        """
        self._dirty = True
        if self._current is not None and not self._current.done():
            return
        loop = _running_loop()
        if loop is None:
            return
        self._dirty = False
        self._current = loop.create_task(self._memory._manage_queue())
        self._current.add_done_callback(self._on_flush_done)

    def _on_flush_done(self, task: asyncio.Task) -> None:
        """Log failures and replay a flush that was requested mid-flight."""
        _log_task_failure(task, "Background memory flush failed")
        if self._dirty:
            self._schedule_manage()

    def schedule_embed(self, messages: list[ChatMessage]) -> None:
        """Embed *messages* into the memory blocks without queueing them.

        Used on resume for the turns trimmed off the recent-history
        tail: they must reach vector storage, but they must not re-enter
        the live queue (that is what caused the freeze).  Embedding is
        idempotent thanks to :func:`_hash_node_id`, so replaying content
        that is already stored is harmless.
        """
        if not messages:
            return
        loop = _running_loop()
        if loop is None:
            return
        task = loop.create_task(self._embed(messages))
        self._embeds.add(task)
        task.add_done_callback(self._on_embed_done)

    async def _embed(self, messages: list[ChatMessage]) -> None:
        await asyncio.gather(
            *[
                block.aput(
                    messages,
                    from_short_term_memory=True,
                    session_id=self._memory.session_id,
                )
                for block in self._memory.memory_blocks
            ]
        )

    def _on_embed_done(self, task: asyncio.Task) -> None:
        self._embeds.discard(task)
        _log_task_failure(task, "Background memory embed failed")

    async def drain(self) -> None:
        """Await all outstanding background work.

        Awaits the in-flight flush (repeatedly, while the dirty flag
        re-arms it), then runs ``_manage_queue`` once more because it
        snapshots the chat store at entry and therefore misses messages
        added while it was running.  Finally awaits pending
        :meth:`schedule_embed` tasks.

        Call before discarding the memory instance.
        """
        for _ in range(_DRAIN_MAX_ROUNDS):
            current = self._current
            if current is None or current.done():
                break
            await _await_task(current, "Background memory flush failed")

        try:
            await self._memory._manage_queue()
        except Exception:
            logger.warning("Final memory flush failed", exc_info=True)

        if self._embeds:
            await asyncio.gather(*self._embeds, return_exceptions=True)


def _running_loop() -> asyncio.AbstractEventLoop | None:
    """Return the running loop, or ``None`` outside async context."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _log_task_failure(task: asyncio.Task, message: str) -> None:
    """Log a background task's exception so it is never swallowed."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning(f"{message}: {exc!r}")


async def _await_task(task: asyncio.Task, message: str) -> None:
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.warning(message, exc_info=True)


def wrap_memory(memory: Memory) -> BackgroundFlushMemory:
    """Return a background-flush wrapper around *memory*."""
    return BackgroundFlushMemory(memory)
