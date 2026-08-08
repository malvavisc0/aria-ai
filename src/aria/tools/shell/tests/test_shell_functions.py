"""Tests for shell execution functions."""

import json
import tempfile
from pathlib import Path

import pytest

from aria.tools.shell import shell
from aria.tools.shell.constants import IS_WINDOWS
from aria.tools.shell.exceptions import CommandBlockedError
from aria.tools.shell.validation import (
    _extract_all_command_names,
    _is_blocked_command,
    _validate_command,
)


class TestValidateCommand:
    """Tests for _validate_command and related helpers."""

    def test_empty_command_raises_value_error(self):
        """Test that an empty command raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            _validate_command("")

    def test_whitespace_only_raises_value_error(self):
        """Test that whitespace-only command raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            _validate_command("   ")

    def test_too_long_command_raises_value_error(self):
        """Test that an excessively long command raises ValueError."""
        with pytest.raises(ValueError, match="too long"):
            _validate_command("a" * 10001)

    def test_blocked_command_dd(self):
        """Test that dd is blocked."""
        with pytest.raises(CommandBlockedError, match="blocked"):
            _validate_command("dd if=/dev/zero of=/dev/sda")

    def test_blocked_command_shutdown(self):
        """Test that shutdown is blocked."""
        with pytest.raises(CommandBlockedError):
            _validate_command("shutdown -h now")

    def test_blocked_command_in_pipe(self):
        """Test that blocked commands are detected in pipelines."""
        with pytest.raises(CommandBlockedError):
            _validate_command("echo hello | dd of=/dev/null")

    def test_valid_command_passes(self):
        """Test that a valid command passes validation."""
        _validate_command("echo hello")  # Should not raise

    def test_previously_blocked_commands_now_allowed(self):
        """Test that commands only dangerous with root are now allowed."""
        # These should NOT raise
        _validate_command("chmod 755 myfile")
        _validate_command("chown user:group myfile")
        _validate_command("ifconfig")
        _validate_command("mount")

    def test_is_blocked_command_detects_dd(self):
        """Test _is_blocked_command detects dd."""
        assert _is_blocked_command("dd if=/dev/zero of=/dev/sda") is True

    def test_is_blocked_command_allows_echo(self):
        """Test _is_blocked_command allows echo."""
        assert _is_blocked_command("echo hello") is False

    def test_is_blocked_command_allows_chmod(self):
        """Test _is_blocked_command allows chmod (no longer blocked)."""
        assert _is_blocked_command("chmod 755 file") is False

    def test_extract_all_command_names_simple(self):
        """Test extracting command name from simple command."""
        names = _extract_all_command_names("git status")
        assert names == ["git"]

    def test_extract_all_command_names_pipe(self):
        """Test extracting command names from piped commands."""
        names = _extract_all_command_names("cat file | grep pattern")
        assert names == ["cat", "grep"]

    def test_extract_all_command_names_chain(self):
        """Test extracting command names from chained commands."""
        names = _extract_all_command_names("make && make install")
        assert names == ["make", "make"]

    def test_extract_all_command_names_env_prefix(self):
        """Test extracting command name with env var prefix."""
        names = _extract_all_command_names("FOO=bar git status")
        assert names == ["git"]


class TestShellSingleCommand:
    """Tests for shell function with a single command."""

    def _get_result_data(self, result: str) -> dict:
        """Parse result and return the command data dict (flat for single)."""
        data = json.loads(result)
        return data["data"]

    def _get_result_envelope(self, result: str) -> dict:
        """Parse result and return the top-level envelope."""
        return json.loads(result)

    def test_execute_simple_string_command(self):
        """Test executing a simple command string."""
        result = shell(
            reason="Test echo command",
            commands="echo hello",
            timeout=5,
        )
        envelope = self._get_result_envelope(result)
        cmd_data = self._get_result_data(result)

        assert envelope["tool"] == "shell"
        assert cmd_data["return_code"] == 0
        assert "hello" in cmd_data["stdout_head_tail"]

    def test_execute_dict_command(self):
        """Test executing a command via dict format."""
        result = shell(
            reason="Test echo command",
            commands={"command": "echo hello"},
            timeout=5,
        )
        cmd_data = self._get_result_data(result)

        assert cmd_data["return_code"] == 0
        assert "hello" in cmd_data["stdout_head_tail"]

    def test_execute_command_with_timeout(self):
        """Test command execution with custom timeout."""
        result = shell(
            reason="Test sleep command",
            commands="python3 -c 'import time; time.sleep(0.1)'",
            timeout=5,
        )
        cmd_data = self._get_result_data(result)

        assert cmd_data["return_code"] == 0

    def test_execute_command_with_working_dir(self):
        """Test command execution with custom working directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = shell(
                reason="Test pwd in temp dir",
                commands="pwd",
                timeout=5,
                working_dir=tmpdir,
            )
            cmd_data = self._get_result_data(result)

            assert cmd_data["return_code"] == 0
            assert tmpdir in cmd_data["stdout_head_tail"]

    def test_execute_command_timeout(self):
        """Test command execution timeout."""
        result = shell(
            reason="Test timeout",
            commands="python3 -c 'import time; time.sleep(10)'",
            timeout=1,
        )
        cmd_data = self._get_result_data(result)

        assert cmd_data["timed_out"] is True

    def test_execute_command_error_handling(self):
        """Test command execution with non-zero exit code."""
        result = shell(
            reason="Test error handling",
            commands="python3 -c 'import sys; sys.exit(1)'",
            timeout=5,
        )
        cmd_data = self._get_result_data(result)

        assert cmd_data["return_code"] == 1

    def test_execute_blocked_command_returns_error(self):
        """Test that executing a blocked command returns an error result."""
        result = shell(
            reason="Test blocked command",
            commands="shutdown -h now",
            timeout=5,
        )
        data = json.loads(result)

        assert data["data"]["return_code"] == 1
        assert "blocked" in data["data"]["error"].lower()

    def test_response_has_timestamp(self):
        """Test that response includes timestamp at top level."""
        result = shell(
            reason="Test metadata",
            commands="echo test",
            timeout=5,
        )
        envelope = self._get_result_envelope(result)

        assert "timestamp" in envelope

    def test_response_has_execution_time(self):
        """Test that response includes execution time."""
        result = shell(
            reason="Test execution time in response",
            commands="echo test",
            timeout=5,
        )
        cmd_data = self._get_result_data(result)

        assert "execution_time" in cmd_data
        assert cmd_data["execution_time"] >= 0

    def test_execute_command_with_args(self):
        """Test executing command with arguments."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("test content")

            cmd = f"cat {test_file}" if not IS_WINDOWS else f"type {test_file}"
            result = shell(
                reason="Test cat command",
                commands=cmd,
                timeout=5,
            )
            cmd_data = self._get_result_data(result)

            assert cmd_data["return_code"] == 0
            assert "test content" in cmd_data["stdout_head_tail"]

    def test_execute_command_not_found_returns_127(self):
        """Test that a missing command returns 127."""
        result = shell(
            reason="Test command not found",
            commands="nonexistent_command_xyz",
            timeout=5,
        )
        cmd_data = self._get_result_data(result)

        assert cmd_data["return_code"] != 0

    def test_single_command_returns_flat_response(self):
        """Test that single string input returns flat response (no results array)."""
        result = shell(
            reason="Test flat response for single",
            commands="echo test",
            timeout=5,
        )
        data = json.loads(result)

        assert "results" not in data["data"]
        assert data["data"]["return_code"] == 0
        assert "test" in data["data"]["stdout_head_tail"]

    def test_shell_pipe(self):
        """Test that shell pipes work."""
        result = shell(
            reason="Test pipe",
            commands="echo hello world | tr '[:lower:]' '[:upper:]'",
            timeout=5,
        )
        cmd_data = self._get_result_data(result)

        assert cmd_data["return_code"] == 0
        assert "HELLO WORLD" in cmd_data["stdout_head_tail"]

    def test_shell_redirect(self):
        """Test that shell redirects work."""
        with tempfile.TemporaryDirectory() as tmpdir:
            outfile = Path(tmpdir) / "output.txt"
            result = shell(
                reason="Test redirect",
                commands=f"echo hello > {outfile}",
                timeout=5,
            )
            cmd_data = self._get_result_data(result)

            assert cmd_data["return_code"] == 0
            assert outfile.read_text().strip() == "hello"

    def test_shell_env_variable(self):
        """Test that environment variable expansion works."""
        result = shell(
            reason="Test env var",
            commands="echo $HOME",
            timeout=5,
        )
        cmd_data = self._get_result_data(result)

        assert cmd_data["return_code"] == 0
        assert len(cmd_data["stdout_head_tail"].strip()) > 0

    def test_shell_chaining(self):
        """Test that command chaining with && works."""
        result = shell(
            reason="Test chaining",
            commands="echo first && echo second",
            timeout=5,
        )
        cmd_data = self._get_result_data(result)

        assert cmd_data["return_code"] == 0
        assert "first" in cmd_data["stdout_head_tail"]
        assert "second" in cmd_data["stdout_head_tail"]


class TestShellBatch:
    """Tests for shell function with multiple commands."""

    def test_execute_batch_with_strings(self):
        """Test executing a batch of string commands."""
        commands = ["echo hello", "echo world"]
        result = shell(
            reason="Test batch execution",
            commands=commands,
            stop_on_error=True,
        )
        data = json.loads(result)

        assert data["tool"] == "shell"
        assert len(data["data"]["results"]) == 2
        assert all(r["return_code"] == 0 for r in data["data"]["results"])
        assert data["data"].get("stopped_early", False) is False

    def test_execute_batch_with_dicts(self):
        """Test executing a batch of dict commands."""
        commands = [
            {"command": "echo hello"},
            {"command": "echo world"},
        ]
        result = shell(
            reason="Test batch execution",
            commands=commands,
            stop_on_error=True,
        )
        data = json.loads(result)

        assert len(data["data"]["results"]) == 2
        assert all(r["return_code"] == 0 for r in data["data"]["results"])

    def test_execute_batch_with_error(self):
        """Test executing a batch with one failing command."""
        commands = [
            "echo hello",
            "exit 1",
            "echo world",
        ]
        result = shell(
            reason="Test batch with error",
            commands=commands,
            stop_on_error=True,
        )
        data = json.loads(result)

        results = data["data"]["results"]
        assert len(results) == 2  # stopped after "exit 1"
        assert results[0]["return_code"] == 0
        assert results[1]["return_code"] != 0
        assert data["data"]["stopped_early"] is True

    def test_execute_batch_continue_on_error(self):
        """Test executing a batch with continue_on_error flag."""
        commands = [
            {"command": "echo hello"},
            {"command": "exit 1", "continue_on_error": True},
            {"command": "echo world"},
        ]
        result = shell(
            reason="Test batch continue on error",
            commands=commands,
            stop_on_error=True,
        )
        data = json.loads(result)

        results = data["data"]["results"]
        assert len(results) == 3
        assert results[0]["return_code"] == 0
        assert results[1]["return_code"] != 0
        assert results[2]["return_code"] == 0
        assert data["data"].get("stopped_early", False) is False

    def test_execute_batch_has_timestamp(self):
        """Test that batch response includes timestamp."""
        commands = ["echo test", "echo world"]
        result = shell(
            reason="Test batch metadata",
            commands=commands,
        )
        data = json.loads(result)

        assert "timestamp" in data
        assert len(data["data"]["results"]) == 2

    def test_execute_empty_commands(self):
        """Test that empty commands list returns valid response."""
        result = shell(
            reason="Test empty commands",
            commands=[],
        )
        data = json.loads(result)

        assert "error" in data["data"]
