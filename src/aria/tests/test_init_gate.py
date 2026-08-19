"""Tests for the entry-point init-completed gate (Decision 3).

The ``aria``, ``ax``, and ``aria-gui`` entry points refuse to run non-init
commands until ``$ARIA_HOME/.init-completed.json`` exists. ``init`` and
``config paths`` plus help-style invocation are exempt; the GUI routes
into the wizard instead of exiting.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from aria.bootstrap import (
    _allowed_before_init,
    is_init_completed,
    marker_path,
    write_init_completed_marker,
)
from aria.bootstrap.defaults import TierDefaults


def test_marker_round_trip(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    assert not is_init_completed()
    write_init_completed_marker("remote", None)
    assert is_init_completed()
    assert marker_path().read_text().count("remote") == 1


def test_marker_records_tier(monkeypatch, tmp_path: Path) -> None:
    import json

    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    tier = TierDefaults(
        chat_model="org/model",
        quant="gptq",
        context_size=131072,
        voice_allowed=True,
    )
    write_init_completed_marker("local", tier)
    data = json.loads(marker_path().read_text())
    assert data["chat_mode"] == "local"
    assert data["tier"]["chat_model"] == "org/model"
    assert data["tier"]["context_size"] == 131072


def test_allowed_before_init_exempts_init_command() -> None:
    assert _allowed_before_init("init") is True
    assert _allowed_before_init(None) is True  # bare → help
    assert _allowed_before_init("--help") is True


def test_allowed_before_init_refuses_other_commands() -> None:
    assert _allowed_before_init("server") is False
    assert _allowed_before_init("models") is False
    assert _allowed_before_init("users") is False


def test_allowed_before_init_config_paths_is_escape_hatch(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["aria", "config", "paths"])
    assert _allowed_before_init("config") is True


def test_allowed_before_init_config_other_subcommands_refused(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["aria", "config", "show"])
    assert _allowed_before_init("config") is False


def test_allowed_before_init_help_flag_anywhere(monkeypatch) -> None:
    """``aria config --help`` and any ``--help``/``-h`` subcommand position
    are introspection — allowed before init completes."""
    monkeypatch.setattr("sys.argv", ["aria", "config", "--help"])
    assert _allowed_before_init("config") is True

    monkeypatch.setattr("sys.argv", ["aria", "server", "--help"])
    assert _allowed_before_init("server") is True

    monkeypatch.setattr("sys.argv", ["aria", "users", "-h"])
    assert _allowed_before_init("users") is True


def test_allowed_before_init_subcommand_action_still_refused(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["aria", "server", "start"])
    assert _allowed_before_init("server") is False


def test_aria_main_refuses_when_marker_absent(monkeypatch, tmp_path: Path) -> None:
    """``aria server start`` must exit 1 with the init hint when the
    marker is missing — the gate fires before Typer dispatch."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["aria", "server", "start"])

    with pytest.raises(SystemExit) as exc:
        from aria import _init_gate_should_pass

        # Simulate the gate check the entry point runs.
        if not _init_gate_should_pass():
            raise SystemExit(1)
    assert exc.value.code == 1


def test_aria_main_allows_init_when_marker_absent(monkeypatch, tmp_path: Path) -> None:
    """``aria init`` is exempt — the gate passes even before the marker
    exists so the user can actually run init."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["aria", "init"])
    from aria import _init_gate_should_pass

    assert _init_gate_should_pass() is True


def test_aria_main_allows_anything_when_marker_present(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    write_init_completed_marker("local", None)
    monkeypatch.setattr("sys.argv", ["aria", "server", "start"])
    from aria import _init_gate_should_pass

    assert _init_gate_should_pass() is True


def test_should_show_wizard_keys_off_marker(monkeypatch, tmp_path: Path) -> None:
    """The GUI wizard shows when the marker is absent (the wizard IS the
    GUI's init path), and stops showing once it's written."""
    with (
        patch("aria.gui.wizard.flow._has_admin_user", return_value=True),
        patch("aria.gui.wizard.flow._is_model_downloaded", return_value=True),
        patch("aria.config.api.Vllm") as mock_vllm,
        patch("aria.config.api.Lightpanda") as mock_lightpanda,
    ):
        mock_vllm.remote = False
        mock_lightpanda.is_available.return_value = True

        from aria.gui.wizard.flow import should_show_wizard

        monkeypatch.setenv("ARIA_HOME", str(tmp_path))
        # No marker → wizard shows.
        assert should_show_wizard() is True
        # Marker written → wizard no longer shows (other gates pass here).
        write_init_completed_marker("local", None)
        assert should_show_wizard() is False
