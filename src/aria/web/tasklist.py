"""Chainlit adapter: WorkerView → PersistedTaskList."""

from __future__ import annotations

import chainlit as cl
from chainlit.element import Element

from aria.supervision.snapshot import StepView, WorkerView

_STEP_TO_TASK = {
    "pending": cl.TaskStatus.READY,
    "in_progress": cl.TaskStatus.RUNNING,
    "completed": cl.TaskStatus.DONE,
    "failed": cl.TaskStatus.FAILED,
}

_UNFINISHED = {"pending", "in_progress"}


class PersistedTaskList(cl.TaskList):
    """cl.TaskList that keeps its constructor for_id when sending.

    Plain cl.TaskList hard-codes for_id="". Sending with a real for_id
    makes the elements row persist. for_id=None degrades to live-only.
    """

    async def send(self) -> None:
        await self.preprocess_content()
        await Element.send(self, for_id=self.for_id or "")


def _header(view: WorkerView) -> str:
    status = view.worker_status
    if status == "completed":
        return "Done"
    if status in {"failed", "zombie"}:
        return "Failed"
    if status == "cancelled":
        return "Cancelled"
    n = len(view.steps)
    if n == 0:
        return "Ready"
    i = next(
        (idx + 1 for idx, s in enumerate(view.steps) if s.status != "completed"),
        n,
    )
    if i == n and view.steps[-1].status == "completed":
        return "Done"
    return f"Running {i}/{n}"


def _display_status(view: WorkerView, step: StepView) -> cl.TaskStatus:
    terminal = view.worker_status in {"failed", "cancelled", "zombie"}
    if terminal and step.status in _UNFINISHED:
        first = next(s for s in view.steps if s.status in _UNFINISHED)
        if step.id == first.id:
            return cl.TaskStatus.FAILED
    return _STEP_TO_TASK.get(step.status, cl.TaskStatus.READY)


class WorkerTaskList:
    """One PersistedTaskList bound to one worker."""

    def __init__(
        self,
        worker_id: str,
        for_id: str | None = None,
        element_id: str | None = None,
    ) -> None:
        self._worker_id = worker_id
        self._for_id = for_id
        self._element_id = element_id
        self._list: PersistedTaskList | None = None
        self._last: WorkerView | None = None
        self._step_ids: list[str] | None = None

    def _ensure_list(self, header: str) -> PersistedTaskList:
        if self._list is not None:
            return self._list
        self._list = PersistedTaskList(
            status=header, name=self._worker_id, for_id=self._for_id
        )
        if self._element_id is not None:
            self._list.id = self._element_id
        return self._list

    def _rebuild(self, view: WorkerView) -> None:
        assert self._list is not None
        self._list.tasks.clear()
        for step in view.steps:
            self._list.tasks.append(
                cl.Task(
                    title=step.title,
                    status=_display_status(view, step),
                    forId=self._for_id,
                )
            )
        self._step_ids = [s.id for s in view.steps]

    def _mutate(self, view: WorkerView) -> None:
        assert self._list is not None
        for task, step in zip(self._list.tasks, view.steps, strict=True):
            task.status = _display_status(view, step)
            task.title = step.title

    async def render(self, view: WorkerView) -> None:
        if view == self._last:
            return
        header = _header(view)
        lst = self._ensure_list(header)
        ids = [s.id for s in view.steps]
        if self._step_ids != ids:
            self._rebuild(view)
        else:
            self._mutate(view)
        lst.status = header
        await lst.send()
        self._last = view
