"""Tests for the `aria init` command (``src/aria/cli/init.py``).

Covers the dry-run, non-interactive, and no-GPU abort paths from plan §8.
Heavy install/download steps are mocked so the tests stay fast and hermetic.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from aria.cli.init import app
from aria.config.api import KnowledgeHub, Lightpanda, Vllm, Voice

runner = CliRunner()


@contextmanager
def _isolated_reloaded_config() -> Iterator[None]:
    environment = os.environ.copy()
    classes = (Vllm, Voice, Lightpanda, KnowledgeHub)
    attributes = {
        cls: {
            name: value
            for name, value in vars(cls).items()
            if not name.startswith("__")
        }
        for cls in classes
    }

    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(environment)
        for cls, original in attributes.items():
            for name in set(vars(cls)) - set(original):
                if not name.startswith("__"):
                    delattr(cls, name)
            for name, value in original.items():
                setattr(cls, name, value)


def _no_gpu():
    from aria.bootstrap.detect import HardwareProfile

    return HardwareProfile(
        has_nvidia_gpu=False,
        has_rocm=False,
        cuda_version="",
        vram_mb=0,
        platform="cpu",
    )


def _gpu(vram: int = 24576):
    from aria.bootstrap.detect import HardwareProfile

    return HardwareProfile(
        has_nvidia_gpu=True,
        has_rocm=False,
        cuda_version="12.8",
        vram_mb=vram,
        platform="nvidia",
    )


def _copy_template_env(tmp_path: Path) -> None:
    """Seed an ARIA_HOME with a .env from the packaged template."""
    from importlib.resources import as_file, files

    with as_file(files("aria").joinpath(".env.example")) as src:
        (tmp_path / ".env").write_text(src.read_text(), encoding="utf-8")
    (tmp_path / ".chainlit").mkdir(parents=True, exist_ok=True)
    with as_file(files("aria").joinpath(".chainlit", "config.toml")) as src:
        (tmp_path / ".chainlit" / "config.toml").write_text(
            src.read_text(), encoding="utf-8"
        )


def test_init_dry_run_writes_nothing(monkeypatch, tmp_path: Path) -> None:
    """``--dry-run`` computes the plan but writes no marker / .env / config."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _copy_template_env(tmp_path)

    with (
        patch("aria.cli.init.detect_hardware", return_value=_gpu()),
        patch("aria.cli.init.run_init") as mock_run,
        patch("aria.cli.init._install_binaries", return_value=[]) as mock_install,
        patch("aria.cli.init._download_models", return_value=[]) as mock_download,
        patch("aria.preflight.run_preflight_checks"),
    ):
        from aria.bootstrap import InitReport

        mock_run.return_value = InitReport(
            chat_mode="local",
            hardware=_gpu(),
            tier=None,
            dry_run=True,
        )
        result = runner.invoke(app, ["--mode", "local", "--dry-run"])

    assert result.exit_code == 0, result.output
    mock_install.assert_called_once()
    mock_download.assert_called_once()
    # Dry-run must not write the marker.
    assert not (tmp_path / ".init-completed.json").exists()
    # The run_init report must record dry_run=True so the orchestrator skips writes.
    assert mock_run.call_args.kwargs.get("dry_run") is True


def test_init_mode_local_without_gpu_aborts(monkeypatch, tmp_path: Path) -> None:
    """``--mode local`` with no NVIDIA GPU must exit non-zero (Decision 1)."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _copy_template_env(tmp_path)

    with patch("aria.cli.init.detect_hardware", return_value=_no_gpu()):
        result = runner.invoke(app, ["--mode", "local", "--dry-run"])

    assert result.exit_code != 0
    assert "NVIDIA GPU" in result.output or "remote" in result.output.lower()


def test_init_non_interactive_remote_from_env(monkeypatch, tmp_path: Path) -> None:
    """``--non-interactive`` with ``ARIA_VLLM_REMOTE=true`` + endpoint env
    resolves remote mode without prompts and writes the marker."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _copy_template_env(tmp_path)
    monkeypatch.setenv("ARIA_VLLM_REMOTE", "true")
    monkeypatch.setenv("CHAT_OPENAI_API", "https://api.example.com/v1")
    monkeypatch.setenv("ARIA_VLLM_API_KEY", "sk-test")
    monkeypatch.setenv("CHAT_MODEL", "gpt-4o")

    with (
        _isolated_reloaded_config(),
        patch("aria.cli.init.detect_hardware", return_value=_no_gpu()),
        patch("aria.cli.init._install_binaries", return_value=[]),
        patch("aria.cli.init._download_models", return_value=[]),
        patch("aria.preflight.run_preflight_checks"),
    ):
        result = runner.invoke(app, ["--non-interactive"])

    assert result.exit_code == 0, result.output
    # The real run_init wrote the marker.
    assert (tmp_path / ".init-completed.json").exists()
    import json

    data = json.loads((tmp_path / ".init-completed.json").read_text())
    assert data["chat_mode"] == "remote"


def test_init_non_interactive_no_gpu_no_remote_aborts(
    monkeypatch, tmp_path: Path
) -> None:
    """No GPU + no ``ARIA_VLLM_REMOTE`` → abort (no CPU-local mode)."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _copy_template_env(tmp_path)
    monkeypatch.delenv("ARIA_VLLM_REMOTE", raising=False)

    with patch("aria.cli.init.detect_hardware", return_value=_no_gpu()):
        result = runner.invoke(app, ["--non-interactive"])

    assert result.exit_code != 0


def test_init_non_interactive_readonly_env_tolerated(
    monkeypatch, tmp_path: Path
) -> None:
    """A read-only .env (Docker ``:ro`` mount) is tolerated: run_init's
    env write is skipped, but the marker + config.toml sync still run."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _copy_template_env(tmp_path)
    env = tmp_path / ".env"
    env.chmod(0o444)  # read-only

    monkeypatch.setenv("ARIA_VLLM_REMOTE", "true")
    monkeypatch.setenv("CHAT_OPENAI_API", "https://api.example.com/v1")
    monkeypatch.setenv("ARIA_VLLM_API_KEY", "sk-test")
    monkeypatch.setenv("CHAT_MODEL", "gpt-4o")

    try:
        with (
            _isolated_reloaded_config(),
            patch("aria.cli.init.detect_hardware", return_value=_no_gpu()),
            patch("aria.cli.init._install_binaries", return_value=[]),
            patch("aria.cli.init._download_models", return_value=[]),
            patch("aria.preflight.run_preflight_checks"),
        ):
            result = runner.invoke(app, ["--non-interactive"])
    finally:
        env.chmod(0o644)

    assert result.exit_code == 0, result.output
    # The marker must still be written (init completed).
    assert (tmp_path / ".init-completed.json").exists()


def test_init_registered_in_main_app() -> None:
    """The init sub-app is registered on the main aria CLI."""
    from aria.cli.main import app as main_app

    result = runner.invoke(main_app, ["init", "--help"])
    assert result.exit_code == 0
    assert "Bootstrap" in result.output or "init" in result.output.lower()
