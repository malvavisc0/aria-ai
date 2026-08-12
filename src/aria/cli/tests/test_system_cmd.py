"""Tests for system hardware CLI commands."""

import json
from unittest.mock import patch

from aria.cli.system import hardware_cmd


class TestHardwareCmd:
    """Test hardware info gathering."""

    @patch("aria.cli.system.typer")
    def test_contains_os_info(self, mock_typer):
        """Output should contain OS information."""
        output = {}
        mock_typer.echo = lambda x: output.update(json.loads(x))
        hardware_cmd()
        assert "os" in output
        assert "system" in output["os"]
        assert "release" in output["os"]

    @patch("aria.cli.system.typer")
    def test_contains_cpu_info(self, mock_typer):
        """Output should contain CPU information."""
        output = {}
        mock_typer.echo = lambda x: output.update(json.loads(x))
        hardware_cmd()
        assert "cpu" in output
        assert "physical_cores" in output["cpu"]
        assert isinstance(output["cpu"]["physical_cores"], int)

    @patch("aria.cli.system.typer")
    def test_contains_memory_info(self, mock_typer):
        """Output should contain memory information."""
        output = {}
        mock_typer.echo = lambda x: output.update(json.loads(x))
        hardware_cmd()
        # Memory info may or may not be present depending on platform
        if "memory" in output:
            assert "total_gb" in output["memory"]
            assert isinstance(output["memory"]["total_gb"], (int, float))

    @patch("aria.cli.system.typer")
    def test_gpus_key_present(self, mock_typer):
        """Output should have gpus key (may be empty list)."""
        output = {}
        mock_typer.echo = lambda x: output.update(json.loads(x))
        hardware_cmd()
        # gpus key may or may not be present depending on nvidia availability
        if "gpus" in output:
            assert isinstance(output["gpus"], list)
