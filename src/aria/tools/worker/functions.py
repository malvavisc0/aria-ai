"""Worker tool functions.

Provides Python-callable worker management (spawn, list, status, logs,
cancel, clean) for use via the ax dispatcher.
"""

import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from aria.config.folders import Data, Debug, Storage
from aria.server.process_utils import (
    is_process_running,
    load_state,
    save_state,
    stop_process,
)
from aria.tools import Reason, tool_response
from aria.tools.execution_context import get_execution_context
from aria.tools.worker.results import WorkerResultManifest

WORKERS_DIR = Data.path / "workers"
STORAGE_DIR = Storage.path


def _worker_id() -> str:
    return f"worker_{uuid.uuid4().hex[:8]}"


def _audit_path(wid: str) -> Path:
    return WORKERS_DIR / f"{wid}.json"


def _output_dir(wid: str) -> Path:
    return STORAGE_DIR / wid


def worker(
    reason: Reason,
    action: str,
    prompt: str = "",
    expected: str = "",
    steps: list[str] | None = None,
    instructions: str | None = None,
    thread_id: str | None = None,
    output_dir: str | None = None,
    worker_id: str | None = None,
    tail: int = 50,
    days: int = 7,
) -> str:
    """Manage background worker agents.

    When to use:
        - Delegate long-running or multi-step tasks to autonomous workers.
        - Check on worker progress, view logs, or cancel workers.
        - Clean up old worker artifacts.

    Actions:
        spawn  — Create a new worker. Requires prompt, expected, steps.
            Not available to worker agents (no nested workers).
        list   — List all workers. Optional: thread_id filter.
        status — Get worker status. Requires worker_id.
        logs   — View worker logs. Requires worker_id.
        cancel — Cancel a running worker. Requires worker_id.
        clean  — Remove workers older than N days. Optional: days.

    Args:
        reason: Required. Why you are calling this.
        action: One of spawn, list, status, logs, cancel, clean.
        prompt: (spawn) Self-contained task prompt with objective, context,
            scope, constraints, and success criteria.
        expected: (spawn) Expected deliverable or result.
        steps: (spawn) Required. Ordered execution steps; the worker tracks
            them as a plan visible in the UI.
        instructions: (spawn) Optional extra instructions for the worker.
        thread_id: (spawn/list) Conversation thread ID for tracking.
        output_dir: (spawn) Directory for deliverables. Auto-created if omitted.
        worker_id: (status/logs/cancel) Worker ID to operate on.
        tail: (logs) Number of log lines to return (default 50).
        days: (clean) Remove workers older than N days (default 7).

    Returns:
        Structured JSON response with action results.
    """
    action = action.lower().strip()

    if action == "spawn":
        if get_execution_context().role == "worker":
            return tool_response(
                tool="worker",
                reason=reason,
                data={
                    "error": {
                        "code": "nested_worker_forbidden",
                        "message": "Worker agents cannot spawn sub-workers.",
                    }
                },
            )
        return _spawn(
            reason=reason,
            prompt=prompt,
            expected=expected,
            steps=steps,
            instructions=instructions,
            thread_id=thread_id,
            output_dir=output_dir,
        )
    elif action == "list":
        return _list_workers(reason=reason, thread_id=thread_id)
    elif action == "status":
        return _status(reason=reason, worker_id=worker_id)
    elif action == "logs":
        return _logs(reason=reason, worker_id=worker_id, tail=tail)
    elif action == "cancel":
        return _cancel(reason=reason, worker_id=worker_id)
    elif action == "clean":
        return _clean(reason=reason, days=days)
    else:
        return tool_response(
            tool="worker",
            reason=reason,
            data={
                "error": {
                    "code": "unknown_action",
                    "message": f"Unknown action: '{action}'",
                    "available_actions": [
                        "spawn",
                        "list",
                        "status",
                        "logs",
                        "cancel",
                        "clean",
                    ],
                }
            },
        )


def _spawn(
    reason: str,
    prompt: str,
    expected: str,
    steps: list[str] | None = None,
    instructions: str | None = None,
    thread_id: str | None = None,
    output_dir: str | None = None,
) -> str:
    if get_execution_context().role == "worker":
        return tool_response(
            tool="worker",
            reason=reason,
            data={
                "error": {
                    "code": "nested_worker_forbidden",
                    "message": "Worker agents cannot spawn sub-workers.",
                }
            },
        )
    if not prompt:
        return tool_response(
            tool="worker",
            reason=reason,
            data={
                "error": {
                    "code": "missing_prompt",
                    "message": "prompt is required",
                }
            },
        )
    if not expected:
        return tool_response(
            tool="worker",
            reason=reason,
            data={
                "error": {
                    "code": "missing_expected",
                    "message": "expected is required",
                }
            },
        )
    if not steps:
        return tool_response(
            tool="worker",
            reason=reason,
            data={
                "error": {
                    "code": "missing_steps",
                    "message": "steps is required (ordered execution steps)",
                }
            },
        )

    wid = _worker_id()
    out_dir = Path(output_dir) if output_dir else _output_dir(wid)
    out_dir.mkdir(parents=True, exist_ok=True)

    plan_id = str(uuid.uuid4())
    now_iso = datetime.now(UTC).isoformat()
    step_dicts = [
        {
            "id": uuid.uuid4().hex[:8],
            "description": desc,
            "status": "pending",
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        for desc in steps
    ]
    try:
        from aria.tools.planner.database import PlannerDatabase

        PlannerDatabase().save_plan(
            plan_id=plan_id,
            agent_id=wid,
            task=prompt[:500],
            steps=step_dicts,
            created_at=now_iso,
        )
    except Exception as exc:
        return tool_response(
            tool="worker",
            reason=reason,
            data={
                "error": {
                    "code": "plan_create_failed",
                    "message": str(exc),
                }
            },
        )

    cmd = [
        sys.executable,
        "-m",
        "aria.cli.worker._runner",
        "--worker-id",
        wid,
        "--prompt",
        prompt,
        "--output-dir",
        str(out_dir),
        "--reason",
        reason,
        "--expected",
        expected,
        "--plan-id",
        plan_id,
    ]
    if instructions:
        cmd.extend(["--instructions", instructions])

    logs_dir = Debug.path / "workers"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_handle = open(logs_dir / f"{wid}.log", "w")
    process = subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_handle.close()

    # Write audit
    WORKERS_DIR.mkdir(parents=True, exist_ok=True)
    audit = {
        "worker_id": wid,
        "pid": process.pid,
        "status": "running",
        "created_at": datetime.now(UTC).isoformat(),
        "completed_at": None,
        "thread_id": thread_id,
        "prompt": prompt,
        "reason": reason,
        "expected_results": expected,
        "extra_instructions": instructions,
        "output_dir": str(out_dir),
        "plan_id": plan_id,
        "result": None,
        "error": None,
        "tool_calls": [],
        "result_manifest": None,
        "completed_steps": 0,
        "total_steps": len(steps),
        "warnings": [],
    }
    save_state(_audit_path(wid), audit)

    logger.info(f"Spawned worker {wid} (PID {process.pid})")

    return tool_response(
        tool="worker",
        reason=reason,
        data={
            "worker_id": wid,
            "pid": process.pid,
            "output_dir": str(out_dir),
            "status": "running",
            "plan_id": plan_id,
        },
    )


def _list_workers(reason: str, thread_id: str | None = None) -> str:
    if not WORKERS_DIR.exists():
        return tool_response(tool="worker", reason=reason, data={"workers": []})

    workers: list[dict[str, Any]] = []
    for f in sorted(WORKERS_DIR.glob("worker_*.json")):
        audit = load_state(f)
        if not audit:
            continue
        if thread_id and audit.get("thread_id") != thread_id:
            continue
        if audit.get("status") == "running" and not is_process_running(
            audit.get("pid", 0)
        ):
            _mark_zombie(audit)
            save_state(f, audit)
        _attach_manifest(audit)
        workers.append(audit)

    return tool_response(tool="worker", reason=reason, data={"workers": workers})


def _status(reason: str, worker_id: str | None = None) -> str:
    if not worker_id:
        return tool_response(
            tool="worker",
            reason=reason,
            data={
                "error": {
                    "code": "missing_worker_id",
                    "message": "worker_id is required",
                }
            },
        )

    path = _audit_path(worker_id)
    if not path.exists():
        return tool_response(
            tool="worker",
            reason=reason,
            data={
                "error": {
                    "code": "not_found",
                    "message": f"Worker {worker_id} not found",
                }
            },
        )

    audit = load_state(path)
    if audit.get("status") == "running" and not is_process_running(audit.get("pid", 0)):
        _mark_zombie(audit)
        save_state(path, audit)

    _attach_manifest(audit)
    return tool_response(tool="worker", reason=reason, data=audit)


def _mark_zombie(audit: dict[str, Any]) -> None:
    """Mark a dead-pid worker zombie and settle its unfinished plan step.

    The worker process died without writing a terminal audit, so the
    planner DB still shows pending/in_progress steps. Fail the first
    unfinished step so the panel and DB stop claiming live progress.
    """
    from aria.tools.worker.results import settle_unfinished_step

    audit["status"] = "zombie"
    plan_id = audit.get("plan_id")
    if plan_id:
        settle_unfinished_step(plan_id, "worker process died")


def _attach_manifest(audit: dict[str, Any]) -> None:
    """Add validated terminal result data to an audit response.

    On validation/read failure, flag the manifest as unreadable so a
    corrupt result.json is distinguishable from one never written.
    """

    manifest_path = audit.get("result_manifest")
    if not manifest_path:
        return
    try:
        manifest = WorkerResultManifest.model_validate_json(
            Path(manifest_path).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        audit["manifest_error"] = "unreadable"
        return
    audit["result_manifest_data"] = manifest.model_dump(mode="json")


def _logs(reason: str, worker_id: str | None = None, tail: int = 50) -> str:
    if not worker_id:
        return tool_response(
            tool="worker",
            reason=reason,
            data={
                "error": {
                    "code": "missing_worker_id",
                    "message": "worker_id is required",
                }
            },
        )

    log_file = Debug.path / "workers" / f"{worker_id}.log"
    if not log_file.exists():
        return tool_response(
            tool="worker",
            reason=reason,
            data={"error": {"code": "no_logs", "message": "No logs found"}},
        )

    lines = log_file.read_text().splitlines()
    return tool_response(
        tool="worker",
        reason=reason,
        data={"worker_id": worker_id, "lines": lines[-tail:]},
    )


def _cancel(reason: str, worker_id: str | None = None) -> str:
    if not worker_id:
        return tool_response(
            tool="worker",
            reason=reason,
            data={
                "error": {
                    "code": "missing_worker_id",
                    "message": "worker_id is required",
                }
            },
        )

    path = _audit_path(worker_id)
    if not path.exists():
        return tool_response(
            tool="worker",
            reason=reason,
            data={"error": {"code": "not_found", "message": "Not found"}},
        )

    audit = load_state(path)
    if audit.get("status") != "running":
        return tool_response(tool="worker", reason=reason, data=audit)

    stop_process(audit.get("pid", 0))
    audit["status"] = "cancelled"
    audit["completed_at"] = datetime.now(UTC).isoformat()
    save_state(path, audit)

    logger.info(f"Cancelled worker {worker_id}")
    return tool_response(tool="worker", reason=reason, data=audit)


def _clean(reason: str, days: int = 7) -> str:
    if not WORKERS_DIR.exists():
        return tool_response(tool="worker", reason=reason, data={"removed": 0})

    cutoff = datetime.now(UTC) - timedelta(days=days)
    removed = 0
    for f in WORKERS_DIR.glob("worker_*.json"):
        audit = load_state(f)
        if not audit:
            continue
        try:
            created = datetime.fromisoformat(audit["created_at"])
        except (ValueError, KeyError):
            continue
        if created < cutoff:
            f.unlink(missing_ok=True)
            out = _output_dir(audit.get("worker_id", f.stem))
            if out.exists():
                shutil.rmtree(out, ignore_errors=True)
            removed += 1

    logger.info(f"Cleaned {removed} workers older than {days} days")
    return tool_response(tool="worker", reason=reason, data={"removed": removed})
