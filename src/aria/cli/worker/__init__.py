"""Worker CLI — spawn, list, status, logs, cancel, clean.

Workers are background agents that run autonomous tasks as subprocesses.
They share the same tool registry as Aria but cannot spawn sub-workers.
"""

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer
from rich.console import Console

from aria.config.folders import Data, Debug, Storage
from aria.server.process_utils import (
    is_process_running,
    load_state,
    save_state,
    stop_process,
)
from aria.tools.worker.functions import _mark_zombie

app = typer.Typer(
    help=(
        "Background worker management. Use workers for long-running or "
        "multi-step tasks that should continue asynchronously."
    )
)
console = Console()

WORKERS_DIR = Data.path / "workers"
STORAGE_DIR = Storage.path


def _audit_path(wid: str) -> Path:
    return WORKERS_DIR / f"{wid}.json"


def _output_dir(wid: str) -> Path:
    return STORAGE_DIR / wid


@app.command("spawn")
def spawn(
    prompt: str = typer.Option(
        ...,
        "--prompt",
        "-p",
        help="Self-contained task prompt with objective, context, scope, constraints, and success criteria.",
    ),
    reason: str = typer.Option(
        ...,
        "--reason",
        "-r",
        help="Why this task is being delegated to a background worker.",
    ),
    expected: str = typer.Option(
        ...,
        "--expected",
        "-e",
        help="Expected deliverable or result the worker should produce.",
    ),
    steps: list[str] = typer.Option(
        ...,
        "--step",
        help="Ordered execution step. Provide once per step; the final step must verify completion.",
    ),
    instructions: str | None = typer.Option(
        None,
        "--instructions",
        "-i",
        help="Optional extra instructions. Avoid vague additions; the worker should not need follow-up questions.",
    ),
    thread_id: str | None = typer.Option(
        None,
        "--thread-id",
        "-t",
        help="Conversation thread ID that spawned this worker, for session-scoped tracking.",
    ),
    output_dir: str | None = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Directory for worker deliverables. If omitted, a UUID-based directory is created automatically.",
    ),
):
    """Spawn a background worker agent.

    The worker executes autonomously, so the prompt should be specific and
    self-contained.
    """
    from aria.tools.execution_context import get_execution_context
    from aria.tools.worker.functions import worker

    if get_execution_context().role == "worker":
        typer.echo(
            json.dumps(
                {
                    "error": {
                        "code": "nested_worker_forbidden",
                        "message": "Worker agents cannot spawn sub-workers.",
                    }
                }
            )
        )
        raise typer.Exit(1)

    typer.echo(
        worker(
            reason=reason,
            action="spawn",
            prompt=prompt,
            expected=expected,
            steps=steps,
            instructions=instructions,
            thread_id=thread_id,
            output_dir=output_dir,
        )
    )


@app.command("list")
def list_workers(
    thread_id: str | None = typer.Option(
        None,
        "--thread-id",
        "-t",
        help="Filter workers by originating conversation thread ID.",
    ),
):
    """List all workers, optionally filtered by thread ID."""
    if not WORKERS_DIR.exists():
        typer.echo(json.dumps({"workers": []}))
        return

    workers = []
    for f in sorted(WORKERS_DIR.glob("worker_*.json")):
        audit = load_state(f)
        if not audit:
            continue
        # Filter by thread_id if provided
        if thread_id and audit.get("thread_id") != thread_id:
            continue
        # Detect zombies
        if audit.get("status") == "running" and not is_process_running(
            audit.get("pid", 0)
        ):
            _mark_zombie(audit)
            save_state(f, audit)
        workers.append(audit)

    typer.echo(json.dumps({"workers": workers}))


@app.command("status")
def status(
    worker_id: str = typer.Argument(...),
):
    """Get status of a specific worker."""
    path = _audit_path(worker_id)
    if not path.exists():
        typer.echo(json.dumps({"error": f"Worker {worker_id} not found"}))
        raise typer.Exit(1)

    audit = load_state(path)
    if audit.get("status") == "running" and not is_process_running(audit.get("pid", 0)):
        _mark_zombie(audit)
        save_state(path, audit)

    typer.echo(json.dumps(audit))


@app.command("logs")
def logs(
    worker_id: str = typer.Argument(...),
    tail: int = typer.Option(50, "--tail", "-n"),
):
    """View worker logs."""
    log_file = Debug.path / "workers" / f"{worker_id}.log"
    if not log_file.exists():
        typer.echo(json.dumps({"error": "No logs found"}))
        raise typer.Exit(1)
    lines = log_file.read_text().splitlines()
    for line in lines[-tail:]:
        console.print(line)


@app.command("cancel")
def cancel(
    worker_id: str = typer.Argument(...),
):
    """Cancel a running worker."""
    path = _audit_path(worker_id)
    if not path.exists():
        typer.echo(json.dumps({"error": "Not found"}))
        raise typer.Exit(1)

    audit = load_state(path)
    if audit.get("status") != "running":
        typer.echo(json.dumps(audit))
        return

    stop_process(audit.get("pid", 0))
    audit["status"] = "cancelled"
    audit["completed_at"] = datetime.now(UTC).isoformat()
    save_state(path, audit)
    typer.echo(json.dumps(audit))


@app.command("clean")
def clean(
    days: int = typer.Option(7, "--days", "-d"),
):
    """Remove workers older than N days."""
    if not WORKERS_DIR.exists():
        return

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
    typer.echo(json.dumps({"removed": removed}))
