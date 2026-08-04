"""Tests for process manager tool."""

import json
import subprocess
import sys
import tempfile
import time

import pytest

from aria.tools.process import process
from aria.tools.process.functions import (
    _STATE_FILE,
    _cleanup_logs,
    _load_processes,
    _save_processes,
)


@pytest.fixture(autouse=True)
def clean_processes():
    """Clean up any processes and persisted state after each test."""
    yield
    # Kill any remaining processes from persisted state
    entries = _load_processes()
    for name, entry in list(entries.items()):
        pid = entry.get("pid")
        if pid:
            try:
                subprocess.run(
                    ["kill", str(pid)],
                    capture_output=True,
                    timeout=2,
                )
            except Exception:
                pass
        _cleanup_logs(name)
    # Clear state file
    _save_processes({})


class TestProcessManager:
    """Test suite for process manager tool."""

    def test_start_process(self):
        """Test starting a background process."""
        result = process(
            "Start echo server",
            action="start",
            name="test_echo",
            command=sys.executable,
            args=["-c", "import time; time.sleep(0.5)"],
        )
        data = json.loads(result)
        assert data["data"]["action"] == "start"
        assert data["data"]["name"] == "test_echo"
        assert data["data"]["pid"] is not None

    def test_start_duplicate_process(self):
        """Test that starting a duplicate process fails."""
        process(
            "Start first",
            action="start",
            name="dup_test",
            command=sys.executable,
            args=["-c", "import time; time.sleep(2)"],
        )
        result = process(
            "Start duplicate",
            action="start",
            name="dup_test",
            command=sys.executable,
            args=["-c", "print('hello')"],
        )
        data = json.loads(result)
        assert "error" in data["data"]
        assert "already running" in data["data"]["error"].lower()

    def test_start_blocked_command(self):
        """Test that blocked commands are rejected."""
        result = process(
            "Blocked command",
            action="start",
            name="blocked",
            command="shutdown",
            args=["-h", "now"],
        )
        data = json.loads(result)
        assert "error" in data["data"]
        assert "blocked" in data["data"]["error"].lower()

    def test_start_sudo_blocked(self):
        """Test that sudo is rejected by the process tool (privilege escalation)."""
        result = process(
            "Privilege escalation attempt",
            action="start",
            name="sudo_test",
            command="sudo",
            args=["apt", "update"],
        )
        data = json.loads(result)
        assert "error" in data["data"]
        assert "blocked" in data["data"]["error"].lower()

    def test_start_doas_blocked(self):
        """Test that doas is rejected — list must stay in sync with shell tool."""
        result = process(
            "Privilege escalation attempt via doas",
            action="start",
            name="doas_test",
            command="doas",
            args=["apt", "update"],
        )
        data = json.loads(result)
        assert "error" in data["data"]
        assert "blocked" in data["data"]["error"].lower()

    def test_start_missing_name(self):
        """Test start without name returns error."""
        result = process("No name", action="start", command="echo")
        data = json.loads(result)
        assert "error" in data["data"]

    def test_start_missing_command(self):
        """Test start without command returns error."""
        result = process("No command", action="start", name="no_cmd")
        data = json.loads(result)
        assert "error" in data["data"]

    def test_start_command_not_found(self):
        """Test that non-existent command returns error."""
        result = process(
            "Not found",
            action="start",
            name="not_found",
            command="nonexistent_command_xyz",
        )
        data = json.loads(result)
        assert "error" in data["data"]
        assert "not found" in data["data"]["error"].lower()

    def test_stop_process(self):
        """Test stopping a running process."""
        process(
            "Start for stop",
            action="start",
            name="stop_test",
            command=sys.executable,
            args=["-c", "import time; time.sleep(10)"],
        )
        result = process("Stop process", action="stop", name="stop_test")
        data = json.loads(result)
        assert data["data"]["action"] == "stop"
        assert data["data"]["name"] == "stop_test"

    def test_stop_nonexistent_process(self):
        """Test stopping a non-existent process."""
        result = process("Stop nonexistent", action="stop", name="ghost")
        data = json.loads(result)
        assert "error" in data["data"]

    def test_status_running(self):
        """Test status of a running process."""
        process(
            "Start for status",
            action="start",
            name="status_test",
            command=sys.executable,
            args=["-c", "import time; time.sleep(2)"],
        )
        result = process("Get status", action="status", name="status_test")
        data = json.loads(result)
        assert data["data"]["status"] == "running"
        assert data["data"]["pid"] is not None

    def test_status_nonexistent(self):
        """Test status of non-existent process."""
        result = process("Status nonexistent", action="status", name="ghost")
        data = json.loads(result)
        assert "error" in data["data"]

    def test_list_processes(self):
        """Test listing all processes."""
        process(
            "Start for list",
            action="start",
            name="list_test",
            command=sys.executable,
            args=["-c", "import time; time.sleep(1)"],
        )
        result = process("List all", action="list")
        data = json.loads(result)
        assert data["data"]["count"] >= 1
        names = [p["name"] for p in data["data"]["processes"]]
        assert "list_test" in names

    def test_list_empty(self):
        """Test listing when no processes exist."""
        result = process("List empty", action="list")
        data = json.loads(result)
        assert data["data"]["count"] == 0

    def test_invalid_action(self):
        """Test invalid action returns error."""
        result = process("Bad action", action="explode")
        data = json.loads(result)
        assert "error" in data["data"]

    def test_logs_nonblocking_on_running_process(self):
        """Test that logs returns immediately even for a running process.

        With the disk-based implementation, logs are read from log files
        so they never block, even if the process is still running.
        """
        # Start a process that prints output and keeps running
        process(
            "Start for logs",
            action="start",
            name="logs_test",
            command=sys.executable,
            args=[
                "-c",
                (
                    "import sys, time; "
                    "print('hello from stdout', flush=True); "
                    "print('hello from stderr', file=sys.stderr, flush=True); "
                    "time.sleep(30)"
                ),
            ],
        )

        # Give the process a moment to produce output
        time.sleep(0.3)

        # This must return immediately (not block for 30 seconds)
        result = process("Get logs", action="logs", name="logs_test")
        data = json.loads(result)
        assert data["data"]["action"] == "logs"
        assert "hello from stdout" in data["data"]["stdout"]
        assert "hello from stderr" in data["data"]["stderr"]

    def test_logs_after_process_exits(self):
        """Test that logs are available after a process exits."""
        process(
            "Start short-lived",
            action="start",
            name="exited_logs",
            command=sys.executable,
            args=["-c", "print('done')"],
        )

        # Wait for process to finish
        time.sleep(0.5)

        result = process("Get logs", action="logs", name="exited_logs")
        data = json.loads(result)
        assert "done" in data["data"]["stdout"]

    def test_logs_nonexistent(self):
        """Test logs for non-existent process."""
        result = process("Logs nonexistent", action="logs", name="ghost")
        data = json.loads(result)
        assert "error" in data["data"]

    def test_logs_missing_name(self):
        """Test logs without name returns error."""
        result = process("No name", action="logs")
        data = json.loads(result)
        assert "error" in data["data"]


class TestProcessNewFeatures:
    """Tests for new process tool features."""

    def test_start_with_working_dir(self):
        """Test starting a process with custom working directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = process(
                "Working dir test",
                action="start",
                name="wd_test",
                command=sys.executable,
                args=["-c", "import os; print(os.getcwd())"],
                working_dir=tmpdir,
            )
            data = json.loads(result)
            assert data["data"]["action"] == "start"
            assert tmpdir in data["data"]["working_dir"]

    def test_start_with_invalid_working_dir(self):
        """Test that invalid working_dir returns error."""
        result = process(
            "Bad dir",
            action="start",
            name="bad_wd",
            command="echo",
            args=["hi"],
            working_dir="/nonexistent/path/xyz",
        )
        data = json.loads(result)
        assert "error" in data["data"]

    def test_start_with_env(self):
        """Test starting a process with custom environment."""
        result = process(
            "Env test",
            action="start",
            name="env_test",
            command=sys.executable,
            args=["-c", "import os; print(os.environ.get('MY_TEST_VAR', ''))"],
            env={"MY_TEST_VAR": "hello_aria"},
        )
        data = json.loads(result)
        assert data["data"]["action"] == "start"

        time.sleep(0.5)
        logs = process("Get logs", action="logs", name="env_test")
        logs_data = json.loads(logs)
        assert "hello_aria" in logs_data["data"]["stdout"]

    def test_start_with_shell_mode(self):
        """Test starting process with shell=True for pipes."""
        result = process(
            "Shell mode test",
            action="start",
            name="shell_test",
            command="echo hello | tr a-z A-Z",
            use_shell=True,
        )
        data = json.loads(result)
        assert data["data"]["action"] == "start"
        assert data["data"]["use_shell"] is True

        time.sleep(0.5)
        logs = process("Get logs", action="logs", name="shell_test")
        logs_data = json.loads(logs)
        assert "HELLO" in logs_data["data"]["stdout"]

    def test_restart_process(self):
        """Test restarting a process."""
        process(
            "Start for restart",
            action="start",
            name="restart_test",
            command=sys.executable,
            args=["-c", "import time; time.sleep(10)"],
        )
        result = process("Restart it", action="restart", name="restart_test")
        data = json.loads(result)
        assert data["data"]["action"] == "start"
        assert data["data"]["name"] == "restart_test"

    def test_restart_nonexistent(self):
        """Test restarting a non-existent process."""
        result = process("Restart ghost", action="restart", name="ghost")
        data = json.loads(result)
        assert "error" in data["data"]

    def test_signal_process(self):
        """Test sending a signal to a running process."""
        process(
            "Start for signal",
            action="start",
            name="signal_test",
            command=sys.executable,
            args=["-c", "import time; time.sleep(10)"],
        )
        result = process(
            "Send SIGTERM",
            action="signal",
            name="signal_test",
            signal_name="SIGTERM",
        )
        data = json.loads(result)
        assert data["data"]["action"] == "signal"
        assert data["data"]["signal"] == "SIGTERM"

    def test_signal_missing_signal_name(self):
        """Test signal without signal_name returns error."""
        process(
            "Start",
            action="start",
            name="sig_missing",
            command=sys.executable,
            args=["-c", "import time; time.sleep(5)"],
        )
        result = process("Signal", action="signal", name="sig_missing")
        data = json.loads(result)
        assert "error" in data["data"]

    def test_signal_invalid_name(self):
        """Test signal with invalid signal name."""
        process(
            "Start",
            action="start",
            name="sig_invalid",
            command=sys.executable,
            args=["-c", "import time; time.sleep(5)"],
        )
        result = process(
            "Bad signal",
            action="signal",
            name="sig_invalid",
            signal_name="SIGFAKE",
        )
        data = json.loads(result)
        assert "error" in data["data"]
        assert "unknown" in data["data"]["error"].lower()

    def test_timeout_auto_kill(self):
        """Test that timeout auto-kills the process and cleans up state."""
        process(
            "Timeout test",
            action="start",
            name="timeout_test",
            command=sys.executable,
            args=["-c", "import time; time.sleep(30)"],
            timeout=1,
        )
        # Wait for timeout + SIGKILL + cleanup
        time.sleep(2.5)
        # After auto-kill, the process is removed from state entirely
        result = process("Check status", action="status", name="timeout_test")
        data = json.loads(result)
        assert "error" in data["data"]
        assert "not found" in data["data"]["error"].lower()

    def test_status_shows_command_and_working_dir(self):
        """Test that status includes command and working_dir."""
        process(
            "Start",
            action="start",
            name="info_test",
            command=sys.executable,
            args=["-c", "import time; time.sleep(2)"],
        )
        result = process("Status", action="status", name="info_test")
        data = json.loads(result)
        assert "command" in data["data"]
        assert "working_dir" in data["data"]

    def test_list_shows_command_info(self):
        """Test that list includes command info for each process."""
        process(
            "Start",
            action="start",
            name="list_info_test",
            command=sys.executable,
            args=["-c", "import time; time.sleep(2)"],
        )
        result = process("List", action="list")
        data = json.loads(result)
        proc_entry = next(
            p for p in data["data"]["processes"] if p["name"] == "list_info_test"
        )
        assert "command" in proc_entry
        assert "working_dir" in proc_entry

    def test_persistence_across_invocations(self):
        """Test that a process can be found from a different 'invocation'.

        Simulates CLI behavior: start a process, then verify status/logs
        work by reading from disk (not in-memory registry).
        """
        result = process(
            "Start for persistence",
            action="start",
            name="persist_test",
            command=sys.executable,
            args=[
                "-c",
                "import sys, time; print('persistent output', flush=True); time.sleep(10)",
            ],
        )
        data = json.loads(result)
        pid = data["data"]["pid"]

        # Verify the state file exists on disk
        assert _STATE_FILE.exists()

        # Verify we can read state from disk
        entries = _load_processes()
        assert "persist_test" in entries
        assert entries["persist_test"]["pid"] == pid

        # Verify status works (reads from disk)
        time.sleep(0.3)
        result = process("Check status", action="status", name="persist_test")
        status_data = json.loads(result)
        assert status_data["data"]["status"] == "running"
        assert status_data["data"]["pid"] == pid

        # Verify logs work (reads from disk)
        result = process("Get logs", action="logs", name="persist_test")
        logs_data = json.loads(result)
        assert "persistent output" in logs_data["data"]["stdout"]
