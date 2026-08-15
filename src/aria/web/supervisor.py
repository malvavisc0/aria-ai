"""Per-session watcher lifecycle for worker TaskLists."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import chainlit as cl

from aria.supervision.snapshot import find_supervised_workers
from aria.supervision.watch import watch_worker
from aria.web.tasklist import WorkerTaskList

_WATCHERS_KEY = "_supervision_watchers"


def _watchers() -> dict[tuple[str, str], asyncio.Task]:
    store = cl.user_session.get(_WATCHERS_KEY)
    if store is None:
        store = {}
        cl.user_session.set(_WATCHERS_KEY, store)
    return store


def _row_identity(
    worker_id: str, elements: Sequence[Mapping[str, Any]] | None
) -> tuple[str | None, str | None]:
    if not elements:
        return None, None
    for row in elements:
        if row.get("type") == "tasklist" and row.get("name") == worker_id:
            return row.get("id"), row.get("forId")
    return None, None


async def _run_watch(worker_id: str, renderer: WorkerTaskList) -> None:
    async for view in watch_worker(worker_id):
        await renderer.render(view)


async def ensure_watching(
    thread_id: str,
    *,
    for_id: str | None = None,
    elements: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    """Arm one watcher per supervised worker not already tracked."""
    wids = find_supervised_workers(thread_id)
    if not wids:
        return
    store = _watchers()
    for wid in wids:
        key = (thread_id, wid)
        existing = store.get(key)
        if existing is not None and not existing.cancelled():
            continue
        if elements is not None:
            element_id, persist_for = _row_identity(wid, elements)
        else:
            element_id, persist_for = None, for_id
        renderer = WorkerTaskList(wid, for_id=persist_for, element_id=element_id)
        store[key] = asyncio.create_task(_run_watch(wid, renderer))


def cancel_all_watchers() -> None:
    """Cancel every stored watcher task (chat end). Entries stay."""
    store = cl.user_session.get(_WATCHERS_KEY)
    if not store:
        return
    for task in store.values():
        task.cancel()
