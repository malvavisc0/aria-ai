"""Tests for WorkerTaskList rendering."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import chainlit as cl
import pytest

from aria.supervision.snapshot import StepView, WorkerView
from aria.web.tasklist import (
    _STEP_TO_TASK,
    PersistedTaskList,
    WorkerTaskList,
    _header,
)


@pytest.fixture(autouse=True)
def _cl_element_context(monkeypatch):
    monkeypatch.setattr(
        "chainlit.element.context",
        SimpleNamespace(session=SimpleNamespace(thread_id="tid")),
    )


def _lst(wtl: WorkerTaskList) -> PersistedTaskList:
    assert wtl._list is not None
    return wtl._list


def _view(
    status: str = "running",
    steps: list[tuple[str, str, str]] | None = None,
) -> WorkerView:
    if steps is None:
        steps = [("s1", "one", "pending"), ("s2", "two", "pending")]
    return WorkerView(
        worker_id="W",
        plan_id="P",
        task="t",
        steps=tuple(
            StepView(id=i, title=t, status=st, result=None) for i, t, st in steps
        ),
        worker_status=status,
    )


def test_step_to_task_mapping_covers_all_statuses():
    assert set(_STEP_TO_TASK) == {
        "pending",
        "in_progress",
        "completed",
        "failed",
    }
    assert _STEP_TO_TASK["pending"] == cl.TaskStatus.READY
    assert _STEP_TO_TASK["in_progress"] == cl.TaskStatus.RUNNING
    assert _STEP_TO_TASK["completed"] == cl.TaskStatus.DONE
    assert _STEP_TO_TASK["failed"] == cl.TaskStatus.FAILED


async def test_render_first_view_builds_tasks():
    wtl = WorkerTaskList("W", for_id="M")
    with patch.object(PersistedTaskList, "send", new_callable=AsyncMock) as send:
        await wtl.render(_view())
    assert wtl._list is not None
    assert len(wtl._list.tasks) == 2
    send.assert_awaited_once()


async def test_status_only_change_mutates_in_place():
    wtl = WorkerTaskList("W", for_id="M")
    with patch.object(PersistedTaskList, "send", new_callable=AsyncMock) as send:
        await wtl.render(_view())
        tasks = _lst(wtl).tasks
        await wtl.render(
            _view(steps=[("s1", "one", "in_progress"), ("s2", "two", "pending")])
        )
    assert _lst(wtl).tasks is tasks
    assert _lst(wtl).tasks[0].status == cl.TaskStatus.RUNNING
    assert send.await_count == 2


async def test_structural_change_rebuilds_tasks():
    wtl = WorkerTaskList("W", for_id="M")
    with patch.object(PersistedTaskList, "send", new_callable=AsyncMock):
        await wtl.render(_view())
        old = list(_lst(wtl).tasks)
        await wtl.render(_view(steps=[("x", "new", "pending")]))
    assert _lst(wtl).tasks is not old
    assert len(_lst(wtl).tasks) == 1
    assert _lst(wtl).tasks[0].title == "new"


async def test_no_resend_when_unchanged():
    wtl = WorkerTaskList("W", for_id="M")
    view = _view()
    with patch.object(PersistedTaskList, "send", new_callable=AsyncMock) as send:
        await wtl.render(view)
        await wtl.render(view)
    assert send.await_count == 1


async def test_terminal_override_marks_first_unfinished_failed():
    wtl = WorkerTaskList("W", for_id="M")
    view = _view(
        status="zombie",
        steps=[
            ("s1", "a", "completed"),
            ("s2", "b", "in_progress"),
            ("s3", "c", "pending"),
        ],
    )
    with (
        patch.object(PersistedTaskList, "send", new_callable=AsyncMock),
        patch("aria.tools.planner.database.PlannerDatabase.update_step") as upd,
    ):
        await wtl.render(view)
    assert _lst(wtl).tasks[1].status == cl.TaskStatus.FAILED
    upd.assert_not_called()


async def test_persisted_tasklist_forwards_for_id():
    lst = PersistedTaskList(status="Ready", name="W", for_id="M")
    lst.preprocess_content = AsyncMock()
    with patch("aria.web.tasklist.Element.send", new_callable=AsyncMock) as send:
        await lst.send()
    send.assert_awaited_once()
    call = send.await_args
    assert call is not None
    assert call.kwargs.get("for_id") == "M" or (
        len(call.args) > 1 and call.args[1] == "M"
    )

    lst2 = PersistedTaskList(status="Ready", name="W", for_id=None)
    lst2.preprocess_content = AsyncMock()
    with patch("aria.web.tasklist.Element.send", new_callable=AsyncMock) as send2:
        await lst2.send()
    call2 = send2.await_args
    assert call2 is not None
    forwarded = call2.kwargs.get(
        "for_id", call2.args[1] if len(call2.args) > 1 else None
    )
    assert forwarded == ""


async def test_element_identity_set_before_first_send():
    wtl = WorkerTaskList("W", for_id="M", element_id="E")
    with patch.object(PersistedTaskList, "send", new_callable=AsyncMock):
        await wtl.render(_view())
    assert _lst(wtl).id == "E"
    assert _lst(wtl).name == "W"
    assert _lst(wtl).for_id == "M"

    wtl2 = WorkerTaskList("W", for_id="M")
    with patch.object(PersistedTaskList, "send", new_callable=AsyncMock):
        await wtl2.render(_view())
    assert _lst(wtl2).id != "E"
    assert _lst(wtl2).name == "W"


def test_status_header_mapping():
    assert _header(_view(status="completed")) == "Done"
    assert _header(_view(status="zombie")) == "Failed"
    assert _header(_view(status="cancelled")) == "Cancelled"
    done = _view(
        status="running",
        steps=[("s1", "a", "completed"), ("s2", "b", "completed")],
    )
    assert _header(done) == "Done"
    pending = _view(
        status="running",
        steps=[
            ("s1", "a", "pending"),
            ("s2", "b", "pending"),
            ("s3", "c", "pending"),
        ],
    )
    assert _header(pending) == "Running 1/3"
    assert _header(_view(status="running", steps=[])) == "Ready"
    assert _header(_view(status="failed")) == "Failed"
