"""Validated worker result manifests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

WorkerStatus = Literal["completed", "partial", "failed", "cancelled"]


class WorkerStepResult(BaseModel):
    """Terminal snapshot of one planner step."""

    id: str
    description: str
    status: str
    result: str | None = None


class WorkerReport(BaseModel):
    """Metadata for the detailed Markdown report."""

    path: str
    format: Literal["markdown"] = "markdown"
    size_bytes: int
    sha256: str


class WorkerResultManifest(BaseModel):
    """Machine-readable terminal result for a worker execution."""

    schema_version: int = 1
    worker_id: str
    plan_id: str
    status: WorkerStatus
    summary: str = ""
    total_steps: int
    completed_steps: int
    failed_steps: int
    steps: list[WorkerStepResult]
    report: WorkerReport | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    started_at: str
    completed_at: str


def load_plan_steps(plan_id: str) -> list[WorkerStepResult]:
    """Read the current step state from the shared Planner DB."""

    from aria.tools.planner.database import PlannerDatabase

    plan = PlannerDatabase().load_plan(plan_id)
    if plan is None:
        return []
    return [WorkerStepResult(**step) for step in plan["steps"]]


def settle_unfinished_step(plan_id: str, reason: str) -> None:
    """Mark the first unfinished plan step failed so the panel never lies.

    Best-effort attribution: the crashed step is approximated as the
    in_progress step, else the first pending step. No-op when the plan is
    missing or every step is already terminal. Safe on crash/zombie paths:
    uses only PlannerDatabase (a fresh session on the singleton engine).
    """

    from aria.tools.planner.database import PlannerDatabase

    db = PlannerDatabase()
    plan = db.load_plan(plan_id)
    if plan is None:
        return
    target = next(
        (s for s in plan["steps"] if s["status"] == "in_progress"),
        next((s for s in plan["steps"] if s["status"] == "pending"), None),
    )
    if target is not None:
        db.update_step(plan_id, target["id"], status="failed", result=reason)


def report_metadata(path: Path) -> WorkerReport | None:
    """Return absolute report metadata when a report exists."""

    if not path.is_file():
        return None
    content = path.read_bytes()
    return WorkerReport(
        path=str(path.resolve()),
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def build_manifest(
    *,
    worker_id: str,
    plan_id: str,
    status: WorkerStatus,
    summary: str,
    report_path: Path,
    started_at: str,
    error: str | None = None,
    warnings: list[str] | None = None,
) -> WorkerResultManifest:
    """Build a manifest from current Planner DB state and report metadata."""

    steps = load_plan_steps(plan_id)
    completed = sum(step.status == "completed" for step in steps)
    failed = sum(step.status == "failed" for step in steps)
    report = report_metadata(report_path)
    manifest_status = status
    manifest_warnings = list(warnings or [])

    if status == "completed":
        if not steps or completed != len(steps):
            manifest_status = "partial" if not failed else "failed"
            manifest_warnings.append("Not every seeded plan step is completed.")
        if report is None:
            manifest_status = "failed"
            manifest_warnings.append("The detailed Markdown report is missing.")

    return WorkerResultManifest(
        worker_id=worker_id,
        plan_id=plan_id,
        status=manifest_status,
        summary=summary[:4000],
        total_steps=len(steps),
        completed_steps=completed,
        failed_steps=failed,
        steps=steps,
        report=report,
        warnings=manifest_warnings,
        error=error,
        started_at=started_at,
        completed_at=datetime.now(UTC).isoformat(),
    )


def write_manifest(path: Path, manifest: WorkerResultManifest) -> None:
    """Atomically write a validated result manifest."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
