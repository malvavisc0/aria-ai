"""Unit tests for validation helpers in shell module.

These tests directly test the validation functions in validation.py,
providing comprehensive coverage of the security validation logic.
"""

import tempfile
from pathlib import Path

import pytest

from aria.tools.shell.exceptions import (
    CommandBlockedError,
    WorkingDirectoryError,
)
from aria.tools.shell.validation import (
    _extract_all_command_names,
    _extract_command_name,
    _is_blocked_command,
    _validate_command,
    _validate_working_dir,
)


class TestExtractCommandName:
    """Tests for _extract_command_name function."""

    def test_simple_command(self):
        """Test extracting command name from simple command."""
        assert _extract_command_name("ls -la") == "ls"

    def test_command_with_path(self):
        """Test extracting command name with path."""
        assert _extract_command_name("/usr/bin/ls") == "/usr/bin/ls"

    def test_empty_string(self):
        """Test empty string returns empty."""
        assert _extract_command_name("") == ""

    def test_whitespace_only(self):
        """Test whitespace only returns empty."""
        assert _extract_command_name("   ") == ""

    def test_command_with_args(self):
        """Test extracting command with multiple arguments."""
        assert _extract_command_name("git commit -m 'message'") == "git"


class TestIsBlockedCommand:
    """Tests for _is_blocked_command function."""

    def test_dd_blocked(self):
        """Test that dd is blocked."""
        assert _is_blocked_command("dd if=/dev/zero of=/dev/sda") is True

    def test_shutdown_blocked(self):
        """Test that shutdown is blocked."""
        assert _is_blocked_command("shutdown -h now") is True

    def test_wipe_blocked(self):
        """Test that wipe is blocked."""
        assert _is_blocked_command("wipe /dev/sda") is True

    def test_sudo_blocked(self):
        """Test that sudo is blocked (privilege escalation)."""
        assert _is_blocked_command("sudo rm -rf /") is True

    def test_su_blocked(self):
        """Test that su is blocked (privilege escalation)."""
        assert _is_blocked_command("su -c 'reboot'") is True

    def test_doas_blocked(self):
        """Test that doas is blocked (privilege escalation)."""
        assert _is_blocked_command("doas apt update") is True

    def test_pkexec_blocked(self):
        """Test that pkexec is blocked (privilege escalation)."""
        assert _is_blocked_command("pkexec reboot") is True

    def test_sudo_blocked_in_pipe(self):
        """Test sudo as second command in a pipeline is caught."""
        assert _is_blocked_command("echo x | sudo tee /etc/y") is True

    def test_chmod_not_blocked(self):
        """Test that chmod is no longer blocked (harmless without root)."""
        assert _is_blocked_command("chmod 777 /") is False

    def test_blocked_command_in_pipe(self):
        """Test that blocked commands are detected in pipelines."""
        assert _is_blocked_command("echo hello | dd of=/dev/null") is True

    def test_safe_command_not_blocked(self):
        """Test that safe commands are not blocked."""
        assert _is_blocked_command("ls -la") is False
        assert _is_blocked_command("git status") is False
        assert _is_blocked_command("cat file.txt") is False
        assert _is_blocked_command("chmod 755 file") is False
        assert _is_blocked_command("ifconfig") is False


class TestExtractAllCommandNames:
    """Tests for _extract_all_command_names function."""

    def test_simple_command(self):
        """Test extracting from simple command."""
        assert _extract_all_command_names("git status") == ["git"]

    def test_pipe(self):
        """Test extracting from piped commands."""
        result = _extract_all_command_names("cat file | grep pattern")
        assert result == ["cat", "grep"]

    def test_and_chain(self):
        """Test extracting from && chained commands."""
        result = _extract_all_command_names("make && make install")
        assert result == ["make", "make"]

    def test_or_chain(self):
        """Test extracting from || chained commands."""
        result = _extract_all_command_names("cmd1 || cmd2")
        assert result == ["cmd1", "cmd2"]

    def test_semicolon(self):
        """Test extracting from semicolon-separated commands."""
        result = _extract_all_command_names("echo a; echo b")
        assert result == ["echo", "echo"]

    def test_env_prefix(self):
        """Test extracting with env var prefix."""
        result = _extract_all_command_names("FOO=bar git status")
        assert result == ["git"]


class TestValidateCommand:
    """Tests for _validate_command function."""

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

    def test_blocked_command_dd_raises_error(self):
        """Test that dd raises CommandBlockedError."""
        with pytest.raises(CommandBlockedError, match="blocked"):
            _validate_command("dd if=/dev/zero of=/dev/sda")

    def test_blocked_command_shutdown(self):
        """Test that shutdown is blocked."""
        with pytest.raises(CommandBlockedError):
            _validate_command("shutdown -h now")

    def test_blocked_command_in_pipe_raises_error(self):
        """Test that blocked commands in pipeline raise error."""
        with pytest.raises(CommandBlockedError):
            _validate_command("echo hello | dd of=/dev/null")

    def test_sudo_raises_blocked_error(self):
        """Test that sudo raises CommandBlockedError."""
        with pytest.raises(CommandBlockedError, match="blocked"):
            _validate_command("sudo echo hello")

    def test_valid_command_passes(self):
        """Test that valid commands pass validation."""
        # Should not raise any exception
        _validate_command("ls -la")
        _validate_command("git status")
        _validate_command("cat file.txt")
        _validate_command("chmod 755 file")

    def test_pip_blocked(self):
        """Test that pip install is blocked."""
        with pytest.raises(CommandBlockedError):
            _validate_command("pip install requests")


class TestValidateWorkingDir:
    """Tests for _validate_working_dir function."""

    def test_none_returns_base_dir(self):
        """Test that None returns BASE_DIR."""
        from aria.tools.shell.constants import BASE_DIR

        result = _validate_working_dir(None)
        assert result == BASE_DIR

    def test_valid_directory_returns_path(self):
        """Test that valid directory returns resolved Path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _validate_working_dir(tmpdir)
            assert isinstance(result, Path)
            assert result.exists()
            assert result.is_dir()

    def test_nonexistent_directory_raises_error(self):
        """Test that nonexistent directory raises WorkingDirectoryError."""
        with pytest.raises(WorkingDirectoryError, match="does not exist"):
            _validate_working_dir("/nonexistent/path/12345")

    def test_file_not_directory_raises_error(self):
        """Test that a file path raises WorkingDirectoryError."""
        with tempfile.NamedTemporaryFile() as tmpfile:
            with pytest.raises(WorkingDirectoryError, match="not a directory"):
                _validate_working_dir(tmpfile.name)

    def test_invalid_path_raises_error(self):
        """Test that invalid path raises WorkingDirectoryError."""
        with pytest.raises(WorkingDirectoryError):
            # This should fail on most systems
            _validate_working_dir("\x00\x00\x00")
