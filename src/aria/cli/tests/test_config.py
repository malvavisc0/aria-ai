"""Tests for the ``aria config optimize`` command."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from aria.cli.config import HardwareInfo, app

runner = CliRunner()


def _hw(gpus: list | None = None) -> HardwareInfo:
    return HardwareInfo(
        gpus=gpus or [],
        total_vram=0,
        free_vram_list=[],
        total_ram_mb=0,
        avail_ram_mb=0,
        gpu_count=0,
        has_nvlink=False,
    )


class TestOptimizeNoGpu:
    """The no-GPU path must fail fast instead of silently writing defaults."""

    def test_no_gpu_exits_nonzero(self):
        with patch("aria.cli.config._collect_hardware", return_value=_hw()):
            result = runner.invoke(app, ["optimize"])
        assert result.exit_code != 0
        assert "No GPU detected" in result.output

    def test_no_gpu_does_not_write_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("aria.cli.config._collect_hardware", return_value=_hw()):
            result = runner.invoke(app, ["optimize"])
        assert result.exit_code != 0
        assert not Path(".env").exists()


class TestOptimizeDryRun:
    """A dry run with a GPU present must not write to .env."""

    def test_dry_run_no_write(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        hw = _hw(gpus=["fake-gpu"])
        optimized = {"CHAT_CONTEXT_SIZE": "32768"}
        with (
            patch("aria.cli.config._collect_hardware", return_value=hw),
            patch("aria.cli.config._print_hardware"),
            patch("aria.cli.config._detect_model_sizes", return_value={}),
            patch(
                "aria.cli.config._compute_optimized",
                return_value=(optimized, {"CHAT_CONTEXT_SIZE": "reason"}),
            ),
            patch("aria.cli.config._read_env_file", return_value={}),
        ):
            result = runner.invoke(app, ["optimize", "--dry-run"])
        assert result.exit_code == 0
        assert "Dry run" in result.output
        assert not Path(".env").exists()
