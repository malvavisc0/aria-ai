"""Tests for worker spawn with required steps."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from aria.server.process_utils import load_state
from aria.tools.execution_context import (
    ExecutionContext,
    reset_execution_context,
    set_execution_context,
)
from aria.tools.planner.database import PlannerDatabase
from aria.tools.worker.functions import _spawn


def _parse(resp: str) -> dict:
    return json.loads(resp)["data"]


@patch("aria.tools.worker.functions.subprocess.Popen")
def test_spawn_with_steps_creates_plan(
    mock_popen, test_tools_db, tmp_path, monkeypatch
):
    mock_popen.return_value = MagicMock(pid=4242)
    monkeypatch.setattr("aria.tools.worker.functions.WORKERS_DIR", tmp_path / "workers")
    monkeypatch.setattr("aria.tools.worker.functions.STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr("aria.tools.worker.functions.Debug.path", tmp_path / "debug")
    resp = _spawn(
        reason="r",
        prompt="do the thing",
        expected="out.md",
        steps=["a", "b", "c"],
        thread_id="T",
    )
    data = _parse(resp)
    plan = PlannerDatabase().load_plan(data["plan_id"])
    assert plan is not None
    assert plan["agent_id"] == data["worker_id"]
    assert [s["description"] for s in plan["steps"]] == ["a", "b", "c"]
    assert all(s["status"] == "pending" for s in plan["steps"])
    cmd = mock_popen.call_args[0][0]
    assert "--plan-id" in cmd
    assert data["plan_id"] in cmd
    audit = load_state(tmp_path / "workers" / f"{data['worker_id']}.json")
    assert audit["plan_id"] == data["plan_id"]


@patch("aria.tools.worker.functions.subprocess.Popen")
def test_spawn_response_includes_plan_id(
    mock_popen, test_tools_db, tmp_path, monkeypatch
):
    mock_popen.return_value = MagicMock(pid=1)
    monkeypatch.setattr("aria.tools.worker.functions.WORKERS_DIR", tmp_path / "workers")
    monkeypatch.setattr("aria.tools.worker.functions.STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr("aria.tools.worker.functions.Debug.path", tmp_path / "debug")
    data = _parse(_spawn(reason="r", prompt="p", expected="e", steps=["a"]))
    assert data["plan_id"]


@pytest.mark.parametrize("steps", [None, []])
@patch("aria.tools.worker.functions.subprocess.Popen")
def test_spawn_empty_steps_returns_missing_steps(
    mock_popen, steps, test_tools_db, tmp_path, monkeypatch
):
    workers = tmp_path / "workers"
    monkeypatch.setattr("aria.tools.worker.functions.WORKERS_DIR", workers)
    with patch.object(PlannerDatabase, "save_plan") as save:
        data = _parse(_spawn(reason="r", prompt="p", expected="e", steps=steps))
    assert data["error"]["code"] == "missing_steps"
    save.assert_not_called()
    mock_popen.assert_not_called()
    assert not workers.exists() or not list(workers.glob("*.json"))


def test_worker_context_rejects_nested_spawn():
    token = set_execution_context(ExecutionContext(role="worker", worker_id="worker_x"))
    try:
        data = _parse(_spawn(reason="r", prompt="p", expected="e", steps=["a"]))
    finally:
        reset_execution_context(token)
    assert data["error"]["code"] == "nested_worker_forbidden"


def test_worker_context_cannot_spawn_through_public_tool(test_tools_db):
    from aria.tools.worker.functions import worker

    token = set_execution_context(ExecutionContext(role="worker", worker_id="worker_x"))
    try:
        data = _parse(
            worker(reason="r", action="spawn", prompt="p", expected="e", steps=["a"])
        )
    finally:
        reset_execution_context(token)
    assert data["error"]["code"] == "nested_worker_forbidden"


@patch("aria.tools.worker.functions.subprocess.Popen")
def test_spawn_save_plan_failure_aborts(
    mock_popen, test_tools_db, tmp_path, monkeypatch
):
    workers = tmp_path / "workers"
    monkeypatch.setattr("aria.tools.worker.functions.WORKERS_DIR", workers)
    monkeypatch.setattr("aria.tools.worker.functions.STORAGE_DIR", tmp_path / "storage")
    with patch(
        "aria.tools.planner.database.PlannerDatabase.save_plan",
        side_effect=RuntimeError("db down"),
    ):
        data = _parse(_spawn(reason="r", prompt="p", expected="e", steps=["a"]))
    assert "error" in data
    mock_popen.assert_not_called()
    assert not workers.exists() or not list(workers.glob("*.json"))


def test_spawn_creates_plans_table_if_absent(tmp_path, monkeypatch):
    from aria.tools.database import ToolsDatabase
    from aria.tools.memory.database import MemoryDatabase
    from aria.tools.planner.database import PlannerDatabase as PDB
    from aria.tools.reasoning.database import ReasoningDatabase
    from aria.tools.scratchpad.database import ScratchpadDatabase

    for cls in (
        ToolsDatabase,
        PDB,
        ScratchpadDatabase,
        ReasoningDatabase,
        MemoryDatabase,
    ):
        setattr(cls, "_instance", None)

    db_path = str(tmp_path / "bare.db")
    ToolsDatabase(db_path)
    monkeypatch.setattr("aria.tools.worker.functions.WORKERS_DIR", tmp_path / "workers")
    monkeypatch.setattr("aria.tools.worker.functions.STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr("aria.tools.worker.functions.Debug.path", tmp_path / "debug")
    with patch("aria.tools.worker.functions.subprocess.Popen") as popen:
        popen.return_value = MagicMock(pid=9)
        data = _parse(_spawn(reason="r", prompt="p", expected="e", steps=["only"]))
    plan = PDB().load_plan(data["plan_id"])
    assert plan is not None
    assert plan["steps"][0]["description"] == "only"
    for cls in (
        ToolsDatabase,
        PDB,
        ScratchpadDatabase,
        ReasoningDatabase,
        MemoryDatabase,
    ):
        inst = getattr(cls, "_instance", None)
        if inst is not None and hasattr(inst, "close"):
            inst.close()
        setattr(cls, "_instance", None)
