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
from urllib.error import URLError

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


def _passed_preflight():
    from aria.preflight.results import PreflightResult

    return PreflightResult(passed=True, checks=[])


def _failure(name: str, category: str):
    from aria.preflight.results import CheckResult

    return CheckResult(
        name=name, passed=False, category=category, error=f"{name} failed"
    )


def _failed_preflight(*checks):
    from aria.preflight.results import PreflightResult

    return PreflightResult(passed=False, checks=list(checks))


class _HttpStubResponse:
    def __init__(self, status: int):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@contextmanager
def _stub_remote_probe(status: int = 200, unreachable: bool = False) -> Iterator[list]:
    """Stub ``urlopen`` at the lifecycle boundary; record the Request objects."""

    captured: list = []

    def fake_urlopen(request, timeout=None):
        captured.append(request)
        if unreachable:
            raise URLError("connection refused")
        return _HttpStubResponse(status)

    with patch("aria.server.lifecycle.urlopen", side_effect=fake_urlopen):
        yield captured


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
        patch("aria.preflight.run_preflight_checks", return_value=_passed_preflight()),
    ):
        result = runner.invoke(app, ["--non-interactive"])

    assert result.exit_code == 0, result.output
    # The marker is written by the CLI only after preflight succeeds (B2).
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
            patch(
                "aria.preflight.run_preflight_checks",
                return_value=_passed_preflight(),
            ),
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


# ---------------------------------------------------------------------------
# B1: interactive remote probe targets the prompted values
# ---------------------------------------------------------------------------


def test_interactive_remote_probe_uses_prompted_values(
    monkeypatch, tmp_path: Path
) -> None:
    """The probe must hit the prompted URL with the prompted key — never the
    stock template's localhost:9090 / sk-aria — and the step-4 writer must
    persist the prompted endpoint to .env (one code path, no env mutation)."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _copy_template_env(tmp_path)

    with (
        _isolated_reloaded_config(),
        patch("aria.cli.init.detect_hardware", return_value=_gpu()),
        patch(
            "typer.prompt",
            side_effect=[
                "remote",
                "https://remote.example.com/v1",
                "sk-prompted",
                "gpt-4o-mini",
            ],
        ),
        patch("aria.cli.init._install_binaries", return_value=[]),
        patch("aria.cli.init._download_models", return_value=[]),
        patch(
            "aria.preflight.run_preflight_checks",
            return_value=_passed_preflight(),
        ),
        _stub_remote_probe() as captured,
    ):
        result = runner.invoke(app, [])

    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    assert captured[0].full_url == "https://remote.example.com/v1/models"
    assert captured[0].headers.get("Authorization") == "Bearer sk-prompted"
    env = (tmp_path / ".env").read_text()
    assert "CHAT_OPENAI_API = https://remote.example.com/v1" in env
    assert "ARIA_VLLM_API_KEY = sk-prompted" in env
    assert "CHAT_MODEL = gpt-4o-mini" in env
    assert "ARIA_VLLM_REMOTE = true" in env
    # The marker lands only after a fully successful init (B2).
    assert (tmp_path / ".init-completed.json").exists()


def test_interactive_remote_probe_failure_aborts_before_env_write(
    monkeypatch, tmp_path: Path
) -> None:
    """Probe failure → non-zero exit; .env keeps the template values and no
    marker is written (fail fast at init)."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _copy_template_env(tmp_path)

    with (
        _isolated_reloaded_config(),
        patch("aria.cli.init.detect_hardware", return_value=_gpu()),
        patch(
            "typer.prompt",
            side_effect=[
                "remote",
                "https://remote.example.com/v1",
                "sk-prompted",
                "gpt-4o-mini",
            ],
        ),
        _stub_remote_probe(unreachable=True),
    ):
        result = runner.invoke(app, [])

    assert result.exit_code != 0
    assert "unreachable" in result.output.lower()
    env = (tmp_path / ".env").read_text()
    assert "CHAT_OPENAI_API = https://remote.example.com/v1" not in env
    assert not (tmp_path / ".init-completed.json").exists()


def test_interactive_summary_notes_voice_vision_off(monkeypatch, tmp_path: Path):
    """S5: with both voice and vision resolved off in interactive mode, the
    summary table names the opt-in flags."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _copy_template_env(tmp_path)

    with (
        _isolated_reloaded_config(),
        patch("aria.cli.init.detect_hardware", return_value=_gpu()),
        patch("typer.prompt", side_effect=["local"]),
        patch("aria.cli.init._install_binaries", return_value=[]),
        patch("aria.cli.init._download_models", return_value=[]),
        patch(
            "aria.preflight.run_preflight_checks",
            return_value=_passed_preflight(),
        ),
    ):
        result = runner.invoke(app, [])

    assert result.exit_code == 0, result.output
    flat = " ".join(result.output.split())
    assert "re-run with --with-voice/--with-vision to enable" in flat


# ---------------------------------------------------------------------------
# B2: completion marker only after a fully successful init
# ---------------------------------------------------------------------------


def test_install_failure_leaves_no_marker(monkeypatch, tmp_path: Path) -> None:
    """A raising install step aborts the run and must not leave the
    .init-completed.json marker on disk."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _copy_template_env(tmp_path)
    monkeypatch.setenv("ARIA_VLLM_REMOTE", "true")
    monkeypatch.setenv("CHAT_OPENAI_API", "https://api.example.com/v1")
    monkeypatch.setenv("ARIA_VLLM_API_KEY", "sk-test")
    monkeypatch.setenv("CHAT_MODEL", "gpt-4o")

    with (
        _isolated_reloaded_config(),
        patch("aria.cli.init.detect_hardware", return_value=_no_gpu()),
        patch(
            "aria.cli.init._install_binaries",
            side_effect=RuntimeError("install boom"),
        ),
        patch("aria.cli.init._download_models", return_value=[]),
    ):
        result = runner.invoke(app, ["--non-interactive"])

    assert result.exit_code != 0
    assert not (tmp_path / ".init-completed.json").exists()


def test_preflight_non_hardware_failure_aborts_before_marker(
    monkeypatch, tmp_path: Path
) -> None:
    """A failing models-category check → exit 1, no marker (composes with B2)."""
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
        patch(
            "aria.preflight.run_preflight_checks",
            return_value=_failed_preflight(_failure("chat model", "models")),
        ),
    ):
        result = runner.invoke(app, ["--non-interactive"])

    assert result.exit_code == 1
    assert not (tmp_path / ".init-completed.json").exists()


# ---------------------------------------------------------------------------
# B3: hardware-fit preflight findings are advisory in the init context
# ---------------------------------------------------------------------------


def test_preflight_hardware_failure_is_advisory(monkeypatch, tmp_path: Path) -> None:
    """Only failing hardware-category checks → exit 0, advisory printed,
    marker written (fresh GPU container must not be killed by KV-fit)."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _copy_template_env(tmp_path)
    monkeypatch.setenv("ARIA_VLLM_REMOTE", "true")
    monkeypatch.setenv("CHAT_OPENAI_API", "https://api.example.com/v1")
    monkeypatch.setenv("ARIA_VLLM_API_KEY", "sk-test")
    monkeypatch.setenv("CHAT_MODEL", "gpt-4o")

    with (
        _isolated_reloaded_config(),
        patch("aria.cli.init.detect_hardware", return_value=_gpu()),
        patch("aria.cli.init._install_binaries", return_value=[]),
        patch("aria.cli.init._download_models", return_value=[]),
        patch(
            "aria.preflight.run_preflight_checks",
            return_value=_failed_preflight(_failure("KV cache memory", "hardware")),
        ),
    ):
        result = runner.invoke(app, ["--non-interactive"])

    assert result.exit_code == 0, result.output
    assert "Hardware-fit advisories" in result.output
    assert (tmp_path / ".init-completed.json").exists()


# ---------------------------------------------------------------------------
# S4: --dry-run derives the mode instead of defaulting to local
# ---------------------------------------------------------------------------


def test_dry_run_no_mode_no_gpu_no_remote_shows_abort(
    monkeypatch, tmp_path: Path
) -> None:
    """Dry-run on a no-GPU, no-remote box prints the Decision-1 outcome and
    exits 0 — nothing is written."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _copy_template_env(tmp_path)
    monkeypatch.delenv("ARIA_VLLM_REMOTE", raising=False)

    with patch("aria.cli.init.detect_hardware", return_value=_no_gpu()):
        result = runner.invoke(app, ["--dry-run"])

    assert result.exit_code == 0, result.output
    assert "would abort" in result.output
    assert "ARIA_VLLM_REMOTE = true" not in (tmp_path / ".env").read_text()
    assert not (tmp_path / ".init-completed.json").exists()


def test_dry_run_no_mode_remote_env_derives_remote(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _copy_template_env(tmp_path)
    monkeypatch.setenv("ARIA_VLLM_REMOTE", "true")

    with (
        patch("aria.cli.init.detect_hardware", return_value=_no_gpu()),
        patch("aria.cli.init.run_init") as mock_run,
    ):
        from aria.bootstrap import InitReport

        mock_run.return_value = InitReport(
            chat_mode="remote", hardware=_no_gpu(), tier=None, dry_run=True
        )
        result = runner.invoke(app, ["--dry-run"])

    assert result.exit_code == 0, result.output
    assert mock_run.call_args.args[0] == "remote"


def test_dry_run_no_mode_gpu_derives_local(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _copy_template_env(tmp_path)
    monkeypatch.delenv("ARIA_VLLM_REMOTE", raising=False)

    with (
        patch("aria.cli.init.detect_hardware", return_value=_gpu()),
        patch("aria.cli.init.run_init") as mock_run,
    ):
        from aria.bootstrap import InitReport

        mock_run.return_value = InitReport(
            chat_mode="local", hardware=_gpu(), tier=None, dry_run=True
        )
        result = runner.invoke(app, ["--dry-run"])

    assert result.exit_code == 0, result.output
    assert mock_run.call_args.args[0] == "local"


# ---------------------------------------------------------------------------
# S6: partial remote endpoint flags are rejected
# ---------------------------------------------------------------------------


def test_remote_mode_with_partial_flags_rejected(monkeypatch, tmp_path: Path) -> None:
    """Any of --remote-url/--api-key/--model → all three are required."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _copy_template_env(tmp_path)

    with patch("aria.cli.init.detect_hardware", return_value=_gpu()):
        result = runner.invoke(
            app,
            ["--mode", "remote", "--remote-url", "https://x.example/v1"],
        )

    assert result.exit_code != 0
    assert "--api-key" in result.output
    assert "--model" in result.output
    assert not (tmp_path / ".init-completed.json").exists()


def test_remote_mode_with_all_flags_writes_endpoint(
    monkeypatch, tmp_path: Path
) -> None:
    """All three flags given → the endpoint is persisted and init completes."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _copy_template_env(tmp_path)

    with (
        _isolated_reloaded_config(),
        patch("aria.cli.init.detect_hardware", return_value=_gpu()),
        patch("aria.cli.init._install_binaries", return_value=[]),
        patch("aria.cli.init._download_models", return_value=[]),
        patch(
            "aria.preflight.run_preflight_checks",
            return_value=_passed_preflight(),
        ),
    ):
        result = runner.invoke(
            app,
            [
                "--mode",
                "remote",
                "--remote-url",
                "https://x.example/v1",
                "--api-key",
                "sk-flag",
                "--model",
                "flag-model",
            ],
        )

    assert result.exit_code == 0, result.output
    env = (tmp_path / ".env").read_text()
    assert "CHAT_OPENAI_API = https://x.example/v1" in env
    assert "ARIA_VLLM_API_KEY = sk-flag" in env
    assert "CHAT_MODEL = flag-model" in env
    assert (tmp_path / ".init-completed.json").exists()
