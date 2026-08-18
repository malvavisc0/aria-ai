"""Tests for [`aria.config.api.Voice`](../api.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from aria.config.api import Voice

pytestmark = pytest.mark.voice


class TestVoice:
    def test_not_available_without_binary(self, tmp_path: Path) -> None:
        import aria.config.folders as folders_mod

        with _patch_paths(folders_mod, tmp_path):
            assert Voice.is_available() is False

    def test_disabled_overrides_installed_binary(self, tmp_path: Path) -> None:
        """ARIA_VOICE_ENABLED=false disables voice even when the binary exists."""
        import aria.config.folders as folders_mod

        with _patch_paths(folders_mod, tmp_path):
            exe = tmp_path / "bin" / "whisper-cpp" / "whisper-server"
            exe.parent.mkdir(parents=True)
            exe.touch()
            original = Voice.enabled
            try:
                Voice.enabled = False
                assert Voice.is_available() is False
            finally:
                Voice.enabled = original

    def test_available_with_binary(self, tmp_path: Path) -> None:
        import aria.config.folders as folders_mod

        with _patch_paths(folders_mod, tmp_path):
            exe = tmp_path / "bin" / "whisper-cpp" / "whisper-server"
            exe.parent.mkdir(parents=True)
            exe.touch()
            original = Voice.enabled
            try:
                Voice.enabled = True
                assert Voice.is_available() is True
                assert Voice.get_whisper_binary_path() == exe
            finally:
                Voice.enabled = original

    def test_available_with_nested_release_dir(self, tmp_path: Path) -> None:
        """The extracted bundle nests whisper-server under a release dir."""
        import aria.config.folders as folders_mod

        with _patch_paths(folders_mod, tmp_path):
            exe = (
                tmp_path
                / "bin"
                / "whisper-cpp"
                / "whisper-bin-ubuntu-x64"
                / "whisper-server"
            )
            exe.parent.mkdir(parents=True)
            exe.touch()
            original = Voice.enabled
            try:
                Voice.enabled = True
                assert Voice.is_available() is True
            finally:
                Voice.enabled = original
            assert Voice.get_whisper_binary_path() == exe

    def test_flat_path_preferred_over_nested(self, tmp_path: Path) -> None:
        """A flat whisper-server wins over a legacy nested layout."""
        import aria.config.folders as folders_mod

        with _patch_paths(folders_mod, tmp_path):
            nested = (
                tmp_path
                / "bin"
                / "whisper-cpp"
                / "whisper-bin-ubuntu-x64"
                / "whisper-server"
            )
            nested.parent.mkdir(parents=True)
            nested.touch()
            flat = tmp_path / "bin" / "whisper-cpp" / "whisper-server"
            flat.touch()
            assert Voice.get_whisper_binary_path() == flat

    def test_kokoro_availability(self, tmp_path: Path) -> None:
        import aria.config.folders as folders_mod

        with _patch_paths(folders_mod, tmp_path):
            model = Voice.get_kokoro_model_path()
            model.parent.mkdir(parents=True)
            assert Voice.is_kokoro_available() is False
            model.touch()
            assert Voice.is_kokoro_available() is True

    def test_whisper_model_path_uses_config_model(self, tmp_path: Path) -> None:
        import aria.config.folders as folders_mod

        with _patch_paths(folders_mod, tmp_path):
            assert Voice.get_whisper_model_path() == (
                tmp_path / "models" / f"ggml-{Voice.whisper_model}.bin"
            )


def _patch_paths(folders_mod, tmp_path: Path):
    """Point Bin.path/Models.path at a temp dir for configuration checks."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        old_bin = folders_mod.Bin.path
        old_models = folders_mod.Models.path
        (tmp_path / "bin").mkdir(parents=True, exist_ok=True)
        (tmp_path / "models").mkdir(parents=True, exist_ok=True)
        try:
            folders_mod.Bin.path = tmp_path / "bin"
            folders_mod.Models.path = tmp_path / "models"
            yield
        finally:
            folders_mod.Bin.path = old_bin
            folders_mod.Models.path = old_models

    return _ctx()
