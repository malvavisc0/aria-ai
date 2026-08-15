"""Tests for check CLI commands (preflight and instructions)."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from aria.cli.check import app

runner = CliRunner()


class TestCheckPreflight:
    """Test the ``aria check preflight`` subcommand."""

    @patch("aria.cli.get_db_session")
    @patch("aria.preflight.run_preflight_checks")
    def test_preflight_runs_all_checks(self, mock_run, mock_db):
        """Should call run_preflight_checks and display results."""
        from aria.preflight import CheckResult, PreflightResult

        mock_run.return_value = PreflightResult(
            passed=True,
            checks=[
                CheckResult(
                    name="Test",
                    passed=True,
                    category="environment",
                    details="ok",
                ),
            ],
        )
        mock_ctx = MagicMock()
        mock_db.return_value.__enter__ = MagicMock(return_value=mock_ctx)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)
        mock_ctx.execute.return_value = None

        result = runner.invoke(app, ["preflight"])
        assert result.exit_code == 0
        mock_run.assert_called_once()

    @patch("aria.cli.get_db_session")
    @patch("aria.preflight.run_preflight_checks")
    def test_preflight_exits_1_on_failure(self, mock_run, mock_db):
        """Should exit with code 1 when any check fails."""
        from aria.preflight import CheckResult, PreflightResult

        mock_run.return_value = PreflightResult(
            passed=False,
            checks=[
                CheckResult(
                    name="Test",
                    passed=False,
                    category="environment",
                    error="missing",
                    hint="fix it",
                ),
            ],
        )
        mock_ctx = MagicMock()
        mock_db.return_value.__enter__ = MagicMock(return_value=mock_ctx)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)
        mock_ctx.execute.return_value = None

        result = runner.invoke(app, ["preflight"])
        assert result.exit_code == 1


class TestCheckInstructions:
    """Test the ``aria check instructions`` subcommand."""

    @patch("aria.agents.prompt_enhancer.PromptEnhancerAgent.get_instructions")
    @patch("aria.agents.worker.WorkerAgent.get_instructions")
    @patch("aria.agents.aria.ChatterAgent.get_instructions")
    def test_instructions_all_agents(self, mock_aria, mock_worker, mock_pe):
        """Should display instructions for all agents when no filter given."""
        mock_aria.return_value = "# Aria instructions"
        mock_worker.return_value = "# Worker instructions"
        mock_pe.return_value = "# PE instructions"

        result = runner.invoke(app, ["instructions"])
        assert result.exit_code == 0
        mock_aria.assert_called_once()
        mock_worker.assert_called_once()
        mock_pe.assert_called_once()

    @patch("aria.agents.aria.ChatterAgent.get_instructions")
    def test_instructions_specific_agent(self, mock_aria):
        """Should display instructions for only the requested agent."""
        mock_aria.return_value = "# Aria instructions"

        result = runner.invoke(app, ["instructions", "--agent", "aria"])
        assert result.exit_code == 0
        mock_aria.assert_called_once()

    @patch("aria.agents.worker.WorkerAgent.get_instructions")
    def test_instructions_short_flag(self, mock_worker):
        """Should accept -a as short flag for --agent."""
        mock_worker.return_value = "# Worker instructions"

        result = runner.invoke(app, ["instructions", "-a", "worker"])
        assert result.exit_code == 0
        mock_worker.assert_called_once()

    def test_instructions_unknown_agent(self):
        """Should exit with error for unknown agent name."""
        result = runner.invoke(app, ["instructions", "--agent", "nonexistent"])
        assert result.exit_code == 1
        assert "Unknown agent" in result.output

    @patch("aria.agents.aria.ChatterAgent.get_instructions")
    def test_instructions_raw_mode(self, mock_aria):
        """Should output raw markdown when --raw is passed."""
        mock_aria.return_value = "# Raw test"

        result = runner.invoke(app, ["instructions", "--agent", "aria", "--raw"])
        assert result.exit_code == 0
        # Raw mode should not include Rich panel borders
        assert "╭" not in result.output
        assert "Raw test" in result.output

    @patch("aria.agents.aria.ChatterAgent.get_instructions")
    def test_instructions_raw_mode_preserves_markdown(self, mock_aria):
        mock_aria.return_value = "# Heading\n\n| A | B |\n|---|---|"

        result = runner.invoke(app, ["instructions", "--agent", "aria", "--raw"])
        assert result.exit_code == 0
        assert "| A | B |" in result.output

    @patch("aria.agents.aria.ChatterAgent.get_instructions")
    def test_instructions_includes_extras(self, mock_aria):
        """Should show the full prompt returned by get_instructions."""
        mock_aria.return_value = "# Base prompt\n\n- Date: Jan 1st 2026"

        result = runner.invoke(app, ["instructions", "--agent", "aria", "--raw"])
        assert result.exit_code == 0
        assert "Base prompt" in result.output
        assert "Date: Jan 1st 2026" in result.output

    @patch("aria.agents.worker.WorkerAgent.get_instructions")
    def test_instructions_uses_agent_class(self, mock_worker):
        """Should call get_instructions on the agent class."""
        mock_worker.return_value = "# Worker prompt"

        result = runner.invoke(app, ["instructions", "--agent", "worker", "--raw"])
        assert result.exit_code == 0
        mock_worker.assert_called_once()
        assert "Worker prompt" in result.output

    @patch("aria.agents.prompt_enhancer.PromptEnhancerAgent.get_instructions")
    def test_instructions_prompt_enhancer_uses_agent_class(self, mock_pe):
        """Should call get_instructions on PromptEnhancerAgent."""
        mock_pe.return_value = "# PE prompt"

        result = runner.invoke(
            app, ["instructions", "--agent", "prompt_enhancer", "--raw"]
        )
        assert result.exit_code == 0
        mock_pe.assert_called_once()
        assert "PE prompt" in result.output
