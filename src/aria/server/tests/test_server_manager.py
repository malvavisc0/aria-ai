"""Tests for [`ServerManager`](../manager.py)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aria.server.manager import ServerManager, sync_chainlit_audio_feature


def _make_manager() -> ServerManager:
    with patch("aria.server.manager.load_state", return_value={}):
        return ServerManager()


class TestServerManagerRun:
    """Tests for [`ServerManager.run()`](../manager.py)."""

    def test_run_raises_when_web_ui_exits_nonzero(self) -> None:
        manager = _make_manager()

        with (
            patch.object(manager, "_build_command", return_value=["chainlit"]),
            patch("aria.server.manager.subprocess.run") as mock_run,
            patch("aria.config.folders.get_augmented_env", return_value={}),
            patch.object(manager, "_clear_state") as mock_clear,
            patch.object(manager, "_save_state"),
            patch("aria.server.manager.sync_chainlit_audio_feature"),
        ):
            mock_run.return_value = MagicMock(returncode=1)

            with pytest.raises(RuntimeError, match="status 1"):
                manager.run()

        mock_clear.assert_called_once()

    def test_run_redirects_output_to_debug_log(self) -> None:
        manager = _make_manager()

        with (
            patch.object(manager, "_build_command", return_value=["chainlit"]),
            patch("aria.server.manager.subprocess.run") as mock_run,
            patch("aria.config.folders.get_augmented_env", return_value={}),
            patch.object(manager, "_clear_state"),
            patch.object(manager, "_save_state"),
            patch("aria.server.manager.sync_chainlit_audio_feature"),
        ):
            mock_run.return_value = MagicMock(returncode=0)
            manager.run()

        _, kwargs = mock_run.call_args
        assert kwargs["stdout"] is kwargs["stderr"]


# ---------------------------------------------------------------------------
# sync_chainlit_audio_feature
# ---------------------------------------------------------------------------

_AUDIO_CONFIG = (
    "[features.audio]\n"
    "# Enable audio features\n"
    "enabled = true\n"
    "# Sample rate of the audio\n"
    "sample_rate = 16000\n"
)


def _audio_enabled(config_text: str) -> bool:
    import re

    m = re.search(
        r"\[features\.audio\]\n[^\[]*?enabled\s*=\s*(true|false)", config_text
    )
    assert m is not None
    return m.group(1).lower() == "true"


def test_sync_audio_disables_for_lan_host(tmp_path: Path) -> None:
    config = tmp_path / ".chainlit" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(_AUDIO_CONFIG)

    sync_chainlit_audio_feature("192.168.1.220", tmp_path)

    assert _audio_enabled(config.read_text()) is False


def test_sync_audio_enables_for_localhost(tmp_path: Path) -> None:
    from aria.config.api import Voice

    config = tmp_path / ".chainlit" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(_AUDIO_CONFIG.replace("enabled = true", "enabled = false"))

    original = Voice.enabled
    try:
        Voice.enabled = True
        sync_chainlit_audio_feature("localhost", tmp_path)
    finally:
        Voice.enabled = original

    assert _audio_enabled(config.read_text()) is True


def test_sync_audio_disables_when_voice_disabled(tmp_path: Path) -> None:
    """ARIA_VOICE_ENABLED=false forces audio off even on loopback."""
    from aria.config.api import Voice

    config = tmp_path / ".chainlit" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(_AUDIO_CONFIG.replace("enabled = true", "enabled = false"))

    original = Voice.enabled
    try:
        Voice.enabled = False
        sync_chainlit_audio_feature("localhost", tmp_path)
    finally:
        Voice.enabled = original

    assert _audio_enabled(config.read_text()) is False


def test_sync_audio_noop_when_already_correct(tmp_path: Path) -> None:
    config = tmp_path / ".chainlit" / "config.toml"
    config.parent.mkdir(parents=True)
    original = _AUDIO_CONFIG.replace("enabled = true", "enabled = false")
    config.write_text(original)

    sync_chainlit_audio_feature("192.168.1.220", tmp_path)

    assert config.read_text() == original


def test_sync_audio_skips_missing_config(tmp_path: Path) -> None:
    sync_chainlit_audio_feature("localhost", tmp_path)


def test_sync_audio_preserves_other_sections(tmp_path: Path) -> None:
    config = tmp_path / ".chainlit" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "[features.spontaneous_file_upload]\nenabled = true\n\n"
        + _AUDIO_CONFIG
        + "\n[features.mcp]\nenabled = true\n"
    )

    sync_chainlit_audio_feature("10.0.0.5", tmp_path)

    text = config.read_text()
    assert _audio_enabled(text) is False
    assert "[features.spontaneous_file_upload]\nenabled = true" in text
    assert "[features.mcp]\nenabled = true" in text
