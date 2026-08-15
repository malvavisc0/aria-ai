"""Tests for the cross-process digest lease."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time

import pytest

from aria.server import digest_lease
from aria.server.digest_lease import (
    LEASE_FILE,
    DigestLease,
    active_digest,
    block_if_digesting,
)
from aria.server.process_utils import save_state


@pytest.fixture(autouse=True)
def _clean_lease():
    LEASE_FILE.unlink(missing_ok=True)
    yield
    LEASE_FILE.unlink(missing_ok=True)


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "pid": os.getpid(),
        "started_at": time.time(),
        "heartbeat": time.time(),
        "current_file": None,
    }
    base.update(overrides)
    return base


class TestActiveDigest:
    def test_no_lease_file_returns_none(self) -> None:
        assert active_digest() is None

    def test_live_lease_returns_payload(self) -> None:
        save_state(LEASE_FILE, _payload(current_file="a.pdf"))
        payload = active_digest()
        assert payload is not None
        assert payload["current_file"] == "a.pdf"

    def test_dead_pid_returns_none(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        save_state(LEASE_FILE, _payload(pid=proc.pid))
        assert active_digest() is None

    def test_stale_heartbeat_returns_none(self) -> None:
        stale = time.time() - digest_lease.LEASE_STALE_AFTER - 1
        save_state(LEASE_FILE, _payload(heartbeat=stale))
        assert active_digest() is None

    def test_corrupt_file_returns_none(self) -> None:
        LEASE_FILE.parent.mkdir(parents=True, exist_ok=True)
        LEASE_FILE.write_text("{not json")
        assert active_digest() is None


class TestDigestLease:
    @pytest.mark.asyncio
    async def test_acquire_then_release(self) -> None:
        async with DigestLease():
            payload = active_digest()
            assert payload is not None
            assert payload["pid"] == os.getpid()
        assert active_digest() is None
        assert not LEASE_FILE.exists()

    @pytest.mark.asyncio
    async def test_set_current_file_updates_lease(self) -> None:
        async with DigestLease() as lease:
            lease.set_current_file("docs/report.pdf")
            payload = active_digest()
            assert payload is not None
            assert payload["current_file"] == "docs/report.pdf"

    @pytest.mark.asyncio
    async def test_heartbeat_refreshes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(digest_lease, "HEARTBEAT_INTERVAL", 0.05)
        async with DigestLease():
            first = active_digest()
            assert first is not None
            await asyncio.sleep(0.12)
            second = active_digest()
            assert second is not None
            assert second["heartbeat"] > first["heartbeat"]

    @pytest.mark.asyncio
    async def test_cancellation_releases_lease(self) -> None:
        async def _run() -> None:
            async with DigestLease():
                await asyncio.sleep(60)

        task = asyncio.create_task(_run())
        await asyncio.sleep(0.05)
        assert active_digest() is not None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert active_digest() is None


class TestBlockIfDigesting:
    def test_no_lease_returns_false(self) -> None:
        messages: list[str] = []
        assert block_if_digesting(messages.append) is False
        assert messages == []

    def test_live_lease_blocks_with_message(self) -> None:
        save_state(LEASE_FILE, _payload(current_file="big.pdf"))
        messages: list[str] = []
        assert block_if_digesting(messages.append) is True
        assert len(messages) == 1
        assert "big.pdf" in messages[0]
        assert "--force-stop" not in messages[0]

    def test_live_lease_blocks_without_progress(self) -> None:
        save_state(LEASE_FILE, _payload())
        assert block_if_digesting() is True


class TestStopServerGuard:
    def test_live_lease_blocks_stop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from aria.server import lifecycle

        save_state(LEASE_FILE, _payload(current_file="big.pdf"))
        stop_called = False

        class _FakeManager:
            def stop(self) -> bool:
                nonlocal stop_called
                stop_called = True
                return True

        monkeypatch.setattr("aria.server.manager.ServerManager", _FakeManager)

        result = lifecycle.stop_server()
        assert result.blocked_by_digest is True
        assert result.web_stopped is False
        assert stop_called is False

    def test_force_bypasses_guard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from aria.server import lifecycle

        save_state(LEASE_FILE, _payload())

        class _FakeManager:
            def stop(self) -> bool:
                return True

        class _FakeVllm:
            _pids: dict[str, int] = {}

            def stop_all(self) -> None:
                pass

        monkeypatch.setattr("aria.server.manager.ServerManager", _FakeManager)
        monkeypatch.setattr("aria.server.vllm.VllmServerManager", _FakeVllm)
        monkeypatch.setattr("aria.server.voice.stop_voice_servers", lambda p: None)
        monkeypatch.setattr(
            "aria.server.process_utils.stop_port_listeners", lambda *a, **k: None
        )

        result = lifecycle.stop_server(force=True)
        assert result.blocked_by_digest is False
        assert result.web_stopped is True
