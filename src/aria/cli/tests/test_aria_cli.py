"""Tests for the Aria CLI entry point and command registration."""

from typer.testing import CliRunner

from aria.cli.main import app

runner = CliRunner()


class TestAriaCliRegistration:
    """Verify the Aria CLI registers only human/infra commands."""

    def test_help_shows_banner(self):
        """Running aria with no args should display the ARIA banner."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "ARIA CLI" in result.output

    def test_help_lists_management_commands(self):
        """Help output should list all human/infra commands."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        for cmd in (
            "server",
            "users",
            "models",
            "vllm",
            "config",
            "system",
            "lightpanda",
        ):
            assert cmd in result.output

    def test_help_excludes_agent_commands(self):
        """Help output should NOT list agent-facing commands."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        for cmd in (
            "web",
            "memory",
            "knowledge",
            "dev",
            "worker",
            "processes",
            "check",
        ):
            # These commands should not appear as registered subcommands
            assert f"  {cmd} " not in result.output
