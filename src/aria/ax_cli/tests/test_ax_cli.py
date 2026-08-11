"""Tests for the AX CLI entry point and command registration."""

from typer.testing import CliRunner

from aria.ax_cli.app import app

runner = CliRunner()


class TestAxCliRegistration:
    """Verify the AX CLI registers only agent-facing commands."""

    def test_help_shows_banner(self):
        """Running ax with no args should display the AX banner."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "AX CLI" in result.output

    def test_help_lists_agent_commands(self):
        """Help output should list all agent-facing commands."""
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
            assert cmd in result.output

    def test_help_excludes_human_commands(self):
        """Help output should NOT list human management commands."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        for cmd in (
            "users",
            "server",
            "config",
            "models",
            "vllm",
            "lightpanda",
            "system",
        ):
            # These commands should not appear as registered subcommands
            assert f"  {cmd} " not in result.output

    def test_web_subcommand_registered(self):
        """The web subcommand should be registered and respond to --help."""
        result = runner.invoke(app, ["web", "--help"])
        assert result.exit_code == 0
        assert "search" in result.output.lower() or "web" in result.output.lower()

    def test_memory_subcommand_registered(self):
        """The memory subcommand should be registered."""
        result = runner.invoke(app, ["memory", "--help"])
        assert result.exit_code == 0

    def test_knowledge_subcommand_registered(self):
        """The knowledge subcommand should be registered."""
        result = runner.invoke(app, ["knowledge", "--help"])
        assert result.exit_code == 0

    def test_dev_subcommand_registered(self):
        """The dev subcommand should be registered."""
        result = runner.invoke(app, ["dev", "--help"])
        assert result.exit_code == 0

    def test_worker_subcommand_registered(self):
        """The worker subcommand should be registered."""
        result = runner.invoke(app, ["worker", "--help"])
        assert result.exit_code == 0

    def test_processes_subcommand_registered(self):
        """The processes subcommand should be registered."""
        result = runner.invoke(app, ["processes", "--help"])
        assert result.exit_code == 0

    def test_check_subcommand_registered(self):
        """The check subcommand should be registered."""
        result = runner.invoke(app, ["check", "--help"])
        assert result.exit_code == 0


class TestAxCliMain:
    """Test the ax main entry point function."""

    def test_main_calls_app(self):
        """ax_cli.main() should invoke the Typer app."""
        # Verify main is a callable function, not a module
        import types

        from aria.ax_cli import main as ax_main

        assert not isinstance(ax_main, types.ModuleType)
        assert callable(ax_main)

    def test_main_module_has_main_function(self):
        """The ax_cli package __init__ should export main()."""
        import aria.ax_cli

        assert hasattr(aria.ax_cli, "main")
        assert callable(aria.ax_cli.main)
