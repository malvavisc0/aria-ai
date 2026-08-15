"""Tests for watch_worker polling."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from aria.server.process_utils import save_state
from aria.supervision.snapshot import WorkerView
from aria.supervision.watch import watch_worker
from aria.tools.planner.database import PlannerDatabase


def _seed(tmp_path, monkeypatch, statuses: list[str]) -> str:
    monkeypatch.setattr("aria.tools.worker.functions.WORKERS_DIR", tmp_path)
    monkeypatch.setattr(
        "aria.supervision.snapshot.is_process_running", lambda pid: True
    )
    plan_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    PlannerDatabase().save_plan(
        plan_id=plan_id,
        agent_id="worker_watch01",
        task="t",
        steps=[
            {
                "id": f"s{i}",
                "description": f"d{i}",
                "status": st,
                "created_at": now,
                "updated_at": now,
            }
            for i, st in enumerate(statuses)
        ],
        created_at=now,
    )
    save_state(
        tmp_path / "worker_watch01.json",
        {
            "worker_id": "worker_watch01",
            "pid": 1,
            "status": "running",
            "thread_id": "T",
            "plan_id": plan_id,
        },
    )
    return plan_id


async def test_first_yield_is_immediate(test_tools_db, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, ["pending"])
    slept = False

    async def fake_sleep(_):
        nonlocal slept
        slept = True

    monkeypatch.setattr("aria.supervision.watch.asyncio.sleep", fake_sleep)
    view = await anext(watch_worker("worker_watch01", interval=0.01))
    assert view.worker_id == "worker_watch01"
    assert slept is False


async def test_yields_only_on_change(test_tools_db, tmp_path, monkeypatch):
    plan_id = _seed(tmp_path, monkeypatch, ["pending", "pending"])
    gen = watch_worker("worker_watch01", interval=0.01)
    await anext(gen)
    PlannerDatabase().update_step(plan_id, "s0", status="in_progress")
    nxt = await anext(gen)
    assert nxt.steps[0].status == "in_progress"
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(gen), timeout=0.05)


async def test_terminates_after_final_yield(test_tools_db, tmp_path, monkeypatch):
    plan_id = _seed(tmp_path, monkeypatch, ["pending"])
    save_state(
        tmp_path / "worker_watch01.json",
        {
            "worker_id": "worker_watch01",
            "pid": 1,
            "status": "completed",
            "thread_id": "T",
            "plan_id": plan_id,
        },
    )
    gen = watch_worker("worker_watch01", interval=0.01)
    terminal = await anext(gen)
    assert terminal.worker_status == "completed"
    with pytest.raises(StopAsyncIteration):
        await anext(gen)


async def test_swallows_transient_load_error(test_tools_db, monkeypatch):
    calls = {"n": 0}
    view = WorkerView(
        worker_id="w",
        plan_id="p",
        task="t",
        steps=(),
        worker_status="running",
    )

    def flaky(_wid):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("blip")
        return view

    monkeypatch.setattr("aria.supervision.watch.load_worker_view", flaky)

    async def instant(_):
        return None

    monkeypatch.setattr("aria.supervision.watch.asyncio.sleep", instant)
    got = await anext(watch_worker("w", interval=0.01))
    assert got == view
    assert calls["n"] == 2
