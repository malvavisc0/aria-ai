"""Cross-process lease for knowledge-hub digestion.

The indexer runs in the web process for minutes at a time. Nothing else
tracks it, so ``aria server stop`` / ``aria vllm stop`` / the GUI stop
button can kill the web process mid-digest — orphaning the in-flight
docling subprocess and losing the end-of-run state flush.

This module provides a small JSON lease file (``~/.aria/digest_lease.json``,
same pattern as ``server.json``) written by the indexer while it runs.
Stop paths check :func:`active_digest` and refuse to stop while a live
lease exists. Validity = PID alive **and** heartbeat fresh: the PID is the
primary signal, the heartbeat guards against a wedged indexer that never
gets scheduled again but whose process still exists.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from aria.config.folders import Data as DataConfig
from aria.server.lifecycle import ProgressFn
from aria.server.process_utils import is_process_running, load_state, save_state

LEASE_FILE = DataConfig.path / "digest_lease.json"
HEARTBEAT_INTERVAL = 15.0  # s between heartbeat writes
LEASE_STALE_AFTER = 120.0  # s without a heartbeat before the lease is ignored


class DigestLease:
    """Async context manager holding the digest lease for one reindex run.

    Writes the lease on enter, rewrites the heartbeat in a background task,
    and removes the file on exit — including task cancellation, which is
    what the web shutdown path relies on.
    """

    def __init__(self) -> None:
        self._payload: dict[str, Any] = {
            "pid": os.getpid(),
            "started_at": time.time(),
            "heartbeat": time.time(),
            "current_file": None,
        }
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> DigestLease:
        save_state(LEASE_FILE, self._payload)
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            await asyncio.gather(self._heartbeat_task, return_exceptions=True)
        LEASE_FILE.unlink(missing_ok=True)

    def set_current_file(self, rel: str) -> None:
        """Record which file is being digested (surfaced in block messages)."""
        self._payload["current_file"] = rel
        save_state(LEASE_FILE, self._payload)

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            self._payload["heartbeat"] = time.time()
            save_state(LEASE_FILE, self._payload)


def active_digest() -> dict[str, Any] | None:
    """Return the live lease payload, or None when no digest is running.

    A lease is live when its PID exists and its heartbeat is younger than
    ``LEASE_STALE_AFTER``. Missing/corrupt files and dead or stale leases
    all return None (fail-open: never block a stop on a phantom digest).
    """
    payload = load_state(LEASE_FILE)
    if not payload:
        return None
    pid = payload.get("pid")
    if not isinstance(pid, int) or not is_process_running(pid):
        return None
    heartbeat = payload.get("heartbeat")
    if not isinstance(heartbeat, int | float):
        return None
    if time.time() - heartbeat > LEASE_STALE_AFTER:
        return None
    return payload


def block_if_digesting(progress: ProgressFn | None = None) -> bool:
    """True (emitting a message via *progress*) when a live digest lease exists."""
    lease = active_digest()
    if lease is None:
        return False
    current = lease.get("current_file") or "unknown"
    if progress:
        progress(
            f"Knowledge hub is digesting documents (file: {current}) — "
            "refusing to stop. Wait for indexing to finish."
        )
    return True
