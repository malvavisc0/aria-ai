"""Tests for WorkerView snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from aria.server.process_utils import save_state
from aria.supervision.snapshot import find_supervised_workers, load_worker_view
from aria.tools.planner.database import PlannerDatabase


def _write_audit(path, **fields):
    base = {
        "worker_id": fields.get("worker_id", "worker_aaaa1111"),
        "pid": 1,
        "status": "running",
        "thread_id": "T",
        "plan_id": fields.get("plan_id"),
        "prompt": "p",
    }
    base.update(fields)
    save_state(path, base)


def _plan(n: int = 3) -> str:
    plan_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    PlannerDatabase().save_plan(
        plan_id=plan_id,
        agent_id="worker_aaaa1111",
        task="the task",
        steps=[
            {
                "id": f"s{i}",
                "description": f"step {i}",
                "status": "pending",
                "created_at": now,
                "updated_at": now,
            }
            for i in range(n)
        ],
        created_at=now,
    )
    return plan_id


def test_load_worker_view_returns_ordered_steps(test_tools_db, tmp_path, monkeypatch):
    monkeypatch.setattr("aria.tools.worker.functions.WORKERS_DIR", tmp_path)
    plan_id = _plan(3)
    _write_audit(tmp_path / "worker_aaaa1111.json", plan_id=plan_id)
    monkeypatch.setattr(
        "aria.supervision.snapshot.is_process_running", lambda pid: True
    )
    view = load_worker_view("worker_aaaa1111")
    assert view is not None
    assert view.worker_status == "running"
    assert [s.id for s in view.steps] == ["s0", "s1", "s2"]


def test_load_worker_view_orphan_plan_returns_none(
    test_tools_db, tmp_path, monkeypatch
):
    monkeypatch.setattr("aria.tools.worker.functions.WORKERS_DIR", tmp_path)
    _write_audit(tmp_path / "worker_aaaa1111.json", plan_id="missing")
    assert load_worker_view("worker_aaaa1111") is None


def test_load_worker_view_missing_audit_returns_none(
    test_tools_db, tmp_path, monkeypatch
):
    monkeypatch.setattr("aria.tools.worker.functions.WORKERS_DIR", tmp_path)
    assert load_worker_view("worker_missing") is None


def test_load_worker_view_zombie_when_dead_pid(test_tools_db, tmp_path, monkeypatch):
    monkeypatch.setattr("aria.tools.worker.functions.WORKERS_DIR", tmp_path)
    plan_id = _plan(1)
    _write_audit(tmp_path / "worker_aaaa1111.json", plan_id=plan_id)
    monkeypatch.setattr(
        "aria.supervision.snapshot.is_process_running", lambda pid: False
    )
    view = load_worker_view("worker_aaaa1111")
    assert view is not None
    assert view.worker_status == "zombie"


def test_find_supervised_workers_filters_by_thread(
    test_tools_db, tmp_path, monkeypatch
):
    monkeypatch.setattr("aria.tools.worker.functions.WORKERS_DIR", tmp_path)
    monkeypatch.setattr(
        "aria.supervision.snapshot.is_process_running", lambda pid: True
    )
    _write_audit(
        tmp_path / "worker_runn0001.json",
        worker_id="worker_runn0001",
        thread_id="T",
        status="running",
        plan_id="p",
    )
    _write_audit(
        tmp_path / "worker_done0001.json",
        worker_id="worker_done0001",
        thread_id="T",
        status="completed",
        plan_id="p",
    )
    _write_audit(
        tmp_path / "worker_othr0001.json",
        worker_id="worker_othr0001",
        thread_id="other",
        status="running",
        plan_id="p",
    )
    assert find_supervised_workers("T") == ["worker_runn0001"]


def test_find_supervised_workers_excludes_dead_pid_and_terminal(
    test_tools_db, tmp_path, monkeypatch
):
    monkeypatch.setattr("aria.tools.worker.functions.WORKERS_DIR", tmp_path)

    def alive(pid):
        return pid == 11

    monkeypatch.setattr("aria.supervision.snapshot.is_process_running", alive)
    _write_audit(
        tmp_path / "worker_live0001.json",
        worker_id="worker_live0001",
        pid=11,
        status="running",
        plan_id="p",
    )
    _write_audit(
        tmp_path / "worker_dead0001.json",
        worker_id="worker_dead0001",
        pid=22,
        status="running",
        plan_id="p",
    )
    _write_audit(
        tmp_path / "worker_done0001.json",
        worker_id="worker_done0001",
        pid=11,
        status="completed",
    )
    assert find_supervised_workers("T") == ["worker_live0001"]


def test_find_supervised_workers_empty_when_no_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("aria.tools.worker.functions.WORKERS_DIR", tmp_path / "missing")
    assert find_supervised_workers("T") == []
