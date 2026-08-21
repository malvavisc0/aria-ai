from unittest.mock import patch

from typer.testing import CliRunner

from aria.cli.server import app

runner = CliRunner()


def _preflight_ok():
    class _Result:
        passed = True

        @staticmethod
        def group_by_category():
            return {}

    return _Result()


def test_server_run_shows_clean_failure_panel() -> None:
    with (
        patch("aria.cli.server._ensure_endpoint_reachable"),
        patch(
            "aria.cli.server._get_captured_startup_error",
            return_value="vLLM startup failed: model load error",
        ),
        patch(
            "aria.cli.server.run_preflight_checks",
            return_value=_preflight_ok(),
        ),
        patch("aria.cli.server._print_preflight_result", return_value=True),
        patch("aria.cli.server.ServerManager") as mock_manager_cls,
        patch(
            "aria.scripts.vllm.is_vllm_installed",
            return_value=True,
        ),
    ):
        mock_manager = mock_manager_cls.return_value
        mock_manager.host = "127.0.0.1"
        mock_manager.port = 9876
        mock_manager.run.side_effect = RuntimeError("Web UI exited with status 1")

        result = runner.invoke(app, ["run"])

    assert result.exit_code == 1
    assert "Startup failed" in result.output
    assert "model load error" in result.output
    assert "vLLM log:" in result.output


def test_server_run_shows_captured_error_after_clean_return() -> None:
    with (
        patch("aria.cli.server._ensure_endpoint_reachable"),
        patch(
            "aria.cli.server._get_captured_startup_error",
            return_value="vLLM startup failed: model load error",
        ),
        patch(
            "aria.cli.server.run_preflight_checks",
            return_value=_preflight_ok(),
        ),
        patch("aria.cli.server._print_preflight_result", return_value=True),
        patch("aria.cli.server.ServerManager") as mock_manager_cls,
    ):
        mock_manager = mock_manager_cls.return_value
        mock_manager.host = "127.0.0.1"
        mock_manager.port = 9876
        mock_manager.run.side_effect = Exception("silent startup failure")

        result = runner.invoke(app, ["run"])

    assert result.exit_code == 1
    assert "Startup failed" in result.output
    assert "model load error" in result.output


def test_server_start_shows_clean_timeout_panel() -> None:
    with (
        patch("aria.cli.server._ensure_endpoint_reachable"),
        patch(
            "aria.cli.server._get_captured_startup_error",
            return_value="vLLM startup failed: model load error",
        ),
        patch(
            "aria.cli.server.run_preflight_checks",
            return_value=_preflight_ok(),
        ),
        patch("aria.cli.server._print_preflight_result", return_value=True),
        patch("aria.cli.server._wait_for_health", return_value=False),
        patch("aria.cli.server.ServerManager") as mock_manager_cls,
    ):
        mock_manager = mock_manager_cls.return_value
        mock_manager.host = "127.0.0.1"
        mock_manager.port = 9876
        mock_manager.is_running.return_value = False
        mock_manager.start.return_value = True

        result = runner.invoke(app, ["start"])

    assert result.exit_code == 1
    assert "Startup failed" in result.output
    assert "model load error" in result.output


def test_lifecycle_ensure_models_downloaded_skips_chat_in_remote_mode() -> None:
    """When ARIA_VLLM_REMOTE=true the chat model must never be downloaded.

    The CLI no longer calls this helper (init owns installs/downloads now),
    but ``lifecycle.ensure_models_downloaded`` remains the shared building
    block and must keep the remote-skip contract.
    """
    import os

    from aria.server.lifecycle import ensure_models_downloaded

    with (
        patch("aria.config.api.Vllm") as mock_vllm,
        patch("aria.config.models.Chat") as mock_chat,
        patch("aria.config.models.Embeddings") as mock_embed,
        patch("aria.config.huggingface.HuggingFace"),
        patch("huggingface_hub.snapshot_download") as mock_download,
        patch.dict(
            os.environ,
            {
                "CHAT_MODEL_PATH": "org/chat-model",
                "EMBED_MODEL_PATH": "org/embed-model",
            },
        ),
    ):
        mock_vllm.remote = True
        # Both models configured but missing locally.
        mock_chat.model_path = "/nonexistent/chat-model"
        mock_embed.model_path = "/nonexistent/embed-model"

        ensure_models_downloaded()

    # Only the embeddings repo id should have been downloaded — never chat.
    downloaded_repos = {call.kwargs["repo_id"] for call in mock_download.call_args_list}
    assert "org/embed-model" in downloaded_repos
    assert "org/chat-model" not in downloaded_repos


def test_ensure_vllm_running_shows_clean_failure_panel() -> None:
    with (
        patch("aria.cli.server._ensure_endpoint_reachable"),
        patch(
            "aria.cli.server.run_preflight_checks",
            return_value=_preflight_ok(),
        ),
        patch("aria.cli.server._print_preflight_result", return_value=True),
        patch(
            "aria.cli.server._get_captured_startup_error",
            return_value="vLLM startup failed: model load error",
        ),
        patch("aria.cli.server._is_vllm_healthy", return_value=False),
        patch(
            "aria.server.vllm.VllmServerManager.start_all",
            side_effect=RuntimeError("boom"),
        ),
        patch("aria.cli.server.ServerManager") as mock_manager_cls,
    ):
        mock_manager = mock_manager_cls.return_value
        mock_manager.is_running.return_value = True
        mock_manager.host = "127.0.0.1"
        mock_manager.port = 9876
        mock_manager.pid = 12345

        result = runner.invoke(app, ["start"])

    assert result.exit_code == 1
    assert "Startup failed" in result.output
    assert "model load error" in result.output


# ── _format_check_line parity with the GUI wizard _icon_for ────────────────


def _check(**kw) -> "object":
    """Build a minimal check stand-in for _format_check_line tests."""
    from types import SimpleNamespace

    base = dict(
        name="x",
        passed=True,
        warning=False,
        informational=False,
        details="",
        error="",
        hint="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_format_check_line_fail() -> None:
    from aria.cli.server import _format_check_line

    line = _format_check_line(_check(passed=False, error="missing", hint="fix"))
    assert "✗" in line
    assert "x" in line
    assert "missing" in line
    assert "fix" in line


def test_format_check_line_warning() -> None:
    from aria.cli.server import _format_check_line

    line = _format_check_line(_check(passed=True, warning=True, details="degraded"))
    assert "⚠" in line
    assert "degraded" in line


def test_format_check_line_informational_renders_info_icon() -> None:
    """A disabled-feature check renders as ℹ (neutral), not ✓ (pass)."""
    from aria.cli.server import _format_check_line

    line = _format_check_line(
        _check(passed=True, informational=True, details="Disabled")
    )
    assert "ℹ" in line
    assert "Disabled" in line
    assert "✓" not in line


def test_format_check_line_clean_pass() -> None:
    from aria.cli.server import _format_check_line

    line = _format_check_line(_check(passed=True, details="ok"))
    assert "✓" in line
    assert "ℹ" not in line
    assert "⚠" not in line
