"""Shared utilities for process management.

This module provides common functions for managing external processes,
including state persistence, process checking, and graceful shutdown.
"""

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Callable


def is_process_running(pid: int) -> bool:
    """Check if a process with the given PID is running.

    Args:
        pid: Process ID to check.

    Returns:
        True if the process is running, False otherwise.
    """
    try:
        os.kill(pid, 0)  # Signal 0 doesn't kill, just checks existence
        return True
    except (OSError, ProcessLookupError):
        return False


def load_state(pid_file: Path) -> dict[str, Any]:
    """Load process state from a JSON file.

    Args:
        pid_file: Path to the JSON state file.

    Returns:
        Dictionary with the loaded state, or empty dict if file doesn't exist
        or is invalid.
    """
    if not pid_file.exists():
        return {}
    try:
        with open(pid_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError, ValueError):
        return {}


def save_state(pid_file: Path, data: dict[str, Any]) -> None:
    """Save process state to a JSON file.

    Creates parent directories if they don't exist.

    Args:
        pid_file: Path to the JSON state file.
        data: Dictionary to save.
    """
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    with open(pid_file, "w") as f:
        json.dump(data, f, indent=2)


def clear_state(pid_file: Path) -> None:
    """Clear the state file if it exists.

    Args:
        pid_file: Path to the JSON state file.
    """
    if pid_file.exists():
        pid_file.unlink()


def stop_process(pid: int, timeout: float = 10.0) -> bool:
    """Stop a process by PID with graceful shutdown.

    Sends SIGTERM first, then SIGKILL if the process doesn't stop
    within the timeout period.

    Args:
        pid: Process ID to stop.
        timeout: Maximum seconds to wait for graceful shutdown.

    Returns:
        True if the process was stopped, False if it wasn't running.
    """
    if not is_process_running(pid):
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not is_process_running(pid):
                return True
            time.sleep(0.1)
        # Force kill if still running
        os.kill(pid, signal.SIGKILL)
        # Wait for process to actually terminate (max 2 seconds)
        kill_start = time.time()
        while time.time() - kill_start < 2.0:
            if not is_process_running(pid):
                return True
            time.sleep(0.1)
        # Process still running after SIGKILL (zombie?)
        return False
    except ProcessLookupError:
        return True  # Process already gone


def pids_on_port(port: int) -> list[int]:
    """Return PIDs of processes listening on *port* (via ``lsof``).

    Returns an empty list when ``lsof`` is unavailable or finds nothing.
    Only works on POSIX systems where ``lsof`` is installed.
    """
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [int(p) for p in result.stdout.strip().split() if p.strip()]


def stop_port_listeners(
    port: int,
    name: str,
    progress: Callable[[str], None] | None = None,
    timeout: float = 5.0,
) -> None:
    """Stop any process group listening on *port* (SIGTERM → SIGKILL).

    External safety net for detached child servers that can outlive the
    parent web UI when its own teardown is cut short. No-op when nothing
    is listening on the port.

    Args:
        port: TCP port to inspect.
        name: Human-readable service name for the progress message.
        progress: Optional callback for human-readable progress messages.
        timeout: Maximum seconds to wait for graceful shutdown per process.
    """
    pids = pids_on_port(port)
    if not pids:
        return
    if progress:
        progress(f"Stopping {name} servers…")
    for pid in pids:
        stop_process_group(pid, timeout=timeout)


def stop_process_group(pid: int, timeout: float = 10.0) -> bool:
    """Stop an entire process group by sending signals to the group leader.

    Use this for processes started with ``start_new_session=True`` where
    the PID equals the PGID. Sends SIGTERM to the entire group first,
    then SIGKILL if processes don't stop within the timeout.

    Args:
        pid: Process (group leader) ID — also used as the PGID.
        timeout: Maximum seconds to wait for graceful shutdown.

    Returns:
        True if the group was stopped, False if no process was found.
    """
    if not is_process_running(pid):
        return False

    try:
        # Send SIGTERM to the entire process group
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        # Group already gone or not a group leader — fall back to single PID
        return stop_process(pid, timeout)

    start_time = time.time()
    while time.time() - start_time < timeout:
        if not is_process_running(pid):
            return True
        time.sleep(0.1)

    # Force kill entire group
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass

    kill_start = time.time()
    while time.time() - kill_start < 2.0:
        if not is_process_running(pid):
            return True
        time.sleep(0.1)

    return False
