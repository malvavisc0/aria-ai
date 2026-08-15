"""Poll worker snapshots; yield only on change."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from aria.supervision.snapshot import WorkerView, load_worker_view

_TERMINAL = {"completed", "partial", "failed", "cancelled", "zombie"}


async def watch_worker(
    worker_id: str, interval: float = 1.5
) -> AsyncIterator[WorkerView]:
    """Poll every ``interval``; yield on change; stop after a terminal view.

    First yield is immediate. Never raises — transient load errors retry.
    """
    previous: WorkerView | None = None
    while True:
        try:
            view = load_worker_view(worker_id)
        except Exception:
            view = None
        if view is not None and view != previous:
            yield view
            previous = view
            if view.worker_status in _TERMINAL:
                return
        await asyncio.sleep(interval)
