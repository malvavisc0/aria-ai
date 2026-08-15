"""Tests for worker result manifests."""

from datetime import UTC, datetime
from uuid import uuid4

from aria.tools.planner.database import PlannerDatabase
from aria.tools.worker.results import build_manifest, write_manifest


def _plan(statuses: list[str]) -> str:
    plan_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    PlannerDatabase().save_plan(
        plan_id=plan_id,
        agent_id="worker_test",
        task="task",
        steps=[
            {
                "id": f"s{i}",
                "description": f"step {i}",
                "status": status,
                "created_at": now,
                "updated_at": now,
            }
            for i, status in enumerate(statuses)
        ],
        created_at=now,
    )
    return plan_id


def test_completed_manifest_requires_all_steps_and_report(test_tools_db, tmp_path):
    plan_id = _plan(["completed", "completed"])
    report = tmp_path / "result.md"
    report.write_text("# Result\n")
    manifest = build_manifest(
        worker_id="worker_test",
        plan_id=plan_id,
        status="completed",
        summary="done",
        report_path=report,
        started_at=datetime.now(UTC).isoformat(),
    )
    target = tmp_path / "result.json"
    write_manifest(target, manifest)
    assert manifest.status == "completed"
    assert manifest.completed_steps == 2
    assert manifest.report is not None
    assert manifest.report.path == str(report.resolve())
    assert target.exists()


def test_incomplete_completed_manifest_becomes_partial(test_tools_db, tmp_path):
    plan_id = _plan(["completed", "pending"])
    report = tmp_path / "result.md"
    report.write_text("partial")
    manifest = build_manifest(
        worker_id="worker_test",
        plan_id=plan_id,
        status="completed",
        summary="partial",
        report_path=report,
        started_at=datetime.now(UTC).isoformat(),
    )
    assert manifest.status == "partial"
    assert manifest.completed_steps == 1
    assert manifest.total_steps == 2


def test_manifest_is_readable_after_restart(test_tools_db, tmp_path):
    plan_id = _plan(["completed"])
    report = tmp_path / "result.md"
    report.write_text("done")
    manifest = build_manifest(
        worker_id="worker_test",
        plan_id=plan_id,
        status="completed",
        summary="restart-safe",
        report_path=report,
        started_at=datetime.now(UTC).isoformat(),
    )
    manifest_path = tmp_path / "result.json"
    write_manifest(manifest_path, manifest)
    loaded = manifest.model_validate_json(manifest_path.read_text())
    assert loaded.summary == "restart-safe"
    assert loaded.report is not None
    assert loaded.report.path == str(report.resolve())
