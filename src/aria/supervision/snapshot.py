"""Read-only worker views from audit JSON + planner DB."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aria.tools.worker.functions as worker_tool
from aria.server.process_utils import is_process_running, load_state
from aria.tools.planner.database import PlannerDatabase


@dataclass(frozen=True)
class StepView:
    id: str
    title: str
    status: str
    result: str | None


@dataclass(frozen=True)
class WorkerView:
    worker_id: str
    plan_id: str
    task: str
    steps: tuple[StepView, ...]
    worker_status: str


def _audit_status(audit: dict[str, Any]) -> str:
    status = audit.get("status", "")
    if status == "running" and not is_process_running(audit.get("pid", 0)):
        return "zombie"
    return status


def load_worker_view(worker_id: str) -> WorkerView | None:
    """audit JSON (status/task/plan_id) + PlannerDatabase (steps, ordered).

    Returns None only when the audit file is missing/unreadable or its
    plan_id has no plan row in the DB.
    """
    path = worker_tool.WORKERS_DIR / f"{worker_id}.json"
    if not path.exists():
        return None
    audit = load_state(path)
    if not audit:
        return None
    plan_id = audit.get("plan_id")
    if not plan_id:
        return None
    plan = PlannerDatabase().load_plan(plan_id)
    if plan is None:
        return None
    steps = tuple(
        StepView(
            id=step["id"],
            title=step["description"],
            status=step["status"],
            result=step.get("result"),
        )
        for step in plan["steps"]
    )
    return WorkerView(
        worker_id=worker_id,
        plan_id=plan_id,
        task=plan["task"],
        steps=steps,
        worker_status=_audit_status(audit),
    )


def find_supervised_workers(thread_id: str) -> list[str]:
    """Alive-running worker ids for ``thread_id``. Empty if workers dir missing."""
    workers_dir = worker_tool.WORKERS_DIR
    if not workers_dir.exists():
        return []
    found: list[str] = []
    for path in sorted(workers_dir.glob("worker_*.json")):
        audit = load_state(path)
        if not audit:
            continue
        if audit.get("thread_id") != thread_id:
            continue
        if audit.get("status") != "running":
            continue
        if not audit.get("plan_id"):
            continue
        if not is_process_running(audit.get("pid", 0)):
            continue
        found.append(audit["worker_id"])
    return found
