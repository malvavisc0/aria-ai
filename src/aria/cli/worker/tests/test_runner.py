"""Tests for worker runner plan settlement."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from aria.cli.worker import _runner
from aria.cli.worker._runner import PLAN_SECTION_TEMPLATE
from aria.tools.planner.database import PlannerDatabase


def _seed(statuses: list[str]) -> str:
    plan_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    steps = [
        {
            "id": f"s{i}",
            "description": f"step {i}",
            "status": status,
            "created_at": now,
            "updated_at": now,
        }
        for i, status in enumerate(statuses)
    ]
    PlannerDatabase().save_plan(
        plan_id=plan_id,
        agent_id="worker_x",
        task="t",
        steps=steps,
        created_at=now,
    )
    return plan_id


def test_parse_plan_id_required():
    with (
        patch(
            "sys.argv",
            ["prog", "--worker-id", "w", "--prompt", "p", "--output-dir", "o"],
        ),
        pytest.raises(SystemExit),
    ):
        _runner.main()


def test_build_prompt_contains_plan_section():
    args = SimpleNamespace(
        prompt="do it",
        reason=None,
        expected=None,
        instructions=None,
        plan_id="P",
        worker_id="W",
    )
    prompt = _runner._build_prompt(args)
    expected = args.prompt + PLAN_SECTION_TEMPLATE.format(plan_id="P", agent_id="W")
    assert prompt == expected
    assert 'plan(action="get"' in prompt


def test_settle_steps_completed_flips_unfinished(test_tools_db):
    plan_id = _seed(["completed", "in_progress", "pending", "pending"])
    _runner._settle_steps(plan_id, "completed")
    plan = PlannerDatabase().load_plan(plan_id)
    assert plan is not None
    statuses = [s["status"] for s in plan["steps"]]
    assert statuses == ["completed"] * 4


def test_settle_steps_failed_fails_in_progress_step(test_tools_db):
    plan_id = _seed(["in_progress", "pending", "pending"])
    _runner._settle_steps(plan_id, "failed", exc=ValueError("boom"))
    loaded = PlannerDatabase().load_plan(plan_id)
    assert loaded is not None
    steps = loaded["steps"]
    assert steps[0]["status"] == "failed"
    assert steps[0]["result"] == "boom"
    assert [s["status"] for s in steps[1:]] == ["pending", "pending"]


def test_settle_steps_failed_no_in_progress_fails_first_pending(test_tools_db):
    plan_id = _seed(["pending", "pending", "pending"])
    _runner._settle_steps(plan_id, "failed", exc=ValueError("x"))
    loaded = PlannerDatabase().load_plan(plan_id)
    assert loaded is not None
    steps = loaded["steps"]
    assert steps[0]["status"] == "failed"
    assert [s["status"] for s in steps[1:]] == ["pending", "pending"]


def test_settle_steps_no_plan_returns_silently(test_tools_db):
    _runner._settle_steps("nonexistent-id", "completed")
