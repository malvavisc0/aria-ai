"""Tests for watcher lifecycle."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from aria.supervision.snapshot import StepView, WorkerView
from aria.web.supervisor import cancel_all_watchers, ensure_watching


def _session_mock(store: dict) -> MagicMock:
    mock = MagicMock()
    mock.get.side_effect = lambda k, d=None: store.get(k, d)
    mock.set.side_effect = lambda k, v: store.__setitem__(k, v)
    return mock


def _view(status: str = "running") -> WorkerView:
    return WorkerView(
        worker_id="w1",
        plan_id="p",
        task="t",
        steps=(StepView("s1", "a", "pending", None),),
        worker_status=status,
    )


async def test_ensure_watching_arms_one_watcher_per_worker(monkeypatch):
    store: dict = {}
    monkeypatch.setattr("aria.web.supervisor.cl.user_session", _session_mock(store))
    monkeypatch.setattr(
        "aria.web.supervisor.find_supervised_workers", lambda t: ["w1", "w2"]
    )

    async def empty(_wid):
        if False:
            yield _view()

    monkeypatch.setattr("aria.web.supervisor.watch_worker", empty)
    await ensure_watching("T", for_id="M")
    watchers = store["_supervision_watchers"]
    assert set(watchers) == {("T", "w1"), ("T", "w2")}
    for task in watchers.values():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, StopAsyncIteration):
            pass


async def test_ensure_watching_idempotent(monkeypatch):
    store: dict = {}
    monkeypatch.setattr("aria.web.supervisor.cl.user_session", _session_mock(store))
    monkeypatch.setattr("aria.web.supervisor.find_supervised_workers", lambda t: ["w1"])

    async def empty(_wid):
        if False:
            yield _view()

    monkeypatch.setattr("aria.web.supervisor.watch_worker", empty)
    await ensure_watching("T", for_id="M")
    first = store["_supervision_watchers"][("T", "w1")]
    await ensure_watching("T", for_id="M")
    assert store["_supervision_watchers"][("T", "w1")] is first
    first.cancel()
    try:
        await first
    except (asyncio.CancelledError, StopAsyncIteration):
        pass


async def test_ensure_watching_noop_when_no_workers(monkeypatch):
    store: dict = {}
    monkeypatch.setattr("aria.web.supervisor.cl.user_session", _session_mock(store))
    monkeypatch.setattr("aria.web.supervisor.find_supervised_workers", lambda t: [])
    constructed = []
    monkeypatch.setattr(
        "aria.web.supervisor.WorkerTaskList",
        lambda *a, **k: constructed.append((a, k)),
    )
    await ensure_watching("T", for_id="M")
    assert constructed == []
    assert "_supervision_watchers" not in store


async def test_final_render_leaves_tasklist(monkeypatch):
    store: dict = {}
    monkeypatch.setattr("aria.web.supervisor.cl.user_session", _session_mock(store))
    monkeypatch.setattr("aria.web.supervisor.find_supervised_workers", lambda t: ["w1"])

    async def seq(_wid):
        yield _view("running")
        yield _view("completed")

    renders: list[str] = []

    class FakeList:
        def __init__(self, *a, **k):
            pass

        async def render(self, view):
            renders.append(view.worker_status)

    monkeypatch.setattr("aria.web.supervisor.watch_worker", seq)
    monkeypatch.setattr("aria.web.supervisor.WorkerTaskList", FakeList)
    await ensure_watching("T", for_id="M")
    task = store["_supervision_watchers"][("T", "w1")]
    await task
    assert renders == ["running", "completed"]


async def test_cancellation_on_chat_end(monkeypatch):
    store: dict = {}
    monkeypatch.setattr("aria.web.supervisor.cl.user_session", _session_mock(store))
    monkeypatch.setattr("aria.web.supervisor.find_supervised_workers", lambda t: ["w1"])

    async def hang(_wid):
        await asyncio.Event().wait()
        if False:
            yield _view()

    monkeypatch.setattr("aria.web.supervisor.watch_worker", hang)
    await ensure_watching("T", for_id="M")
    task = store["_supervision_watchers"][("T", "w1")]
    cancel_all_watchers()
    assert task.cancelled() or task.cancelling()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def test_resume_re_arms_only_running_and_alive(monkeypatch):
    store: dict = {}
    monkeypatch.setattr("aria.web.supervisor.cl.user_session", _session_mock(store))
    monkeypatch.setattr(
        "aria.web.supervisor.find_supervised_workers", lambda t: ["alive"]
    )

    async def empty(_wid):
        if False:
            yield _view()

    monkeypatch.setattr("aria.web.supervisor.watch_worker", empty)
    await ensure_watching("T", elements=[])
    assert set(store["_supervision_watchers"]) == {("T", "alive")}
    for task in store["_supervision_watchers"].values():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, StopAsyncIteration):
            pass


async def test_resume_reuses_persisted_element_row(monkeypatch):
    store: dict = {}
    monkeypatch.setattr("aria.web.supervisor.cl.user_session", _session_mock(store))
    monkeypatch.setattr("aria.web.supervisor.find_supervised_workers", lambda t: ["w1"])
    captured: list[tuple] = []

    class FakeList:
        def __init__(self, wid, for_id=None, element_id=None):
            captured.append((wid, for_id, element_id))

    async def empty(_wid):
        if False:
            yield _view()

    monkeypatch.setattr("aria.web.supervisor.watch_worker", empty)
    monkeypatch.setattr("aria.web.supervisor.WorkerTaskList", FakeList)
    await ensure_watching(
        "T",
        elements=[
            {"id": "E1", "type": "tasklist", "name": "w1", "forId": "M1"},
            {"id": "E2", "type": "tasklist", "name": "other", "forId": "Mx"},
        ],
    )
    assert captured == [("w1", "M1", "E1")]
    store.clear()
    captured.clear()
    await ensure_watching("T", elements=None)
    assert captured == [("w1", None, None)]
    store.clear()
    captured.clear()
    await ensure_watching(
        "T", elements=[{"id": "E9", "type": "tasklist", "name": "nope"}]
    )
    assert captured == [("w1", None, None)]
    for task in list(store.get("_supervision_watchers", {}).values()):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, StopAsyncIteration):
            pass
