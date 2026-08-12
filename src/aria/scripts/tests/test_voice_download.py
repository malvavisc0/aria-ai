"""Tests for whisper.cpp download target detection."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from aria.scripts.voice import _detect_whisper_target, _whisper_download_url


class TestDetectWhisperTarget:
    @patch("aria.scripts.voice.platform.system", return_value="Linux")
    @patch("aria.helpers.nvidia.get_total_vram_mb", return_value=16000)
    @patch("aria.helpers.nvidia.get_cuda_version", return_value="12.6")
    def test_returns_cuda_on_nvidia_linux(self, mock_cuda, mock_vram, mock_sys):
        assert _detect_whisper_target() == "cuda"

    @patch("aria.scripts.voice.platform.system", return_value="Linux")
    @patch("aria.helpers.nvidia.get_total_vram_mb", return_value=0)
    def test_returns_cpu_when_no_gpu(self, mock_vram, mock_sys):
        assert _detect_whisper_target() == "cpu"

    @patch("aria.scripts.voice.platform.system", return_value="Linux")
    @patch("aria.helpers.nvidia.get_total_vram_mb", return_value=8000)
    @patch("aria.helpers.nvidia.get_cuda_version", return_value="11.8")
    def test_returns_cpu_when_cuda_too_old(self, mock_cuda, mock_vram, mock_sys):
        assert _detect_whisper_target() == "cpu"

    @patch("aria.scripts.voice.platform.system", return_value="Darwin")
    def test_raises_on_macos(self, mock_sys):
        with pytest.raises(RuntimeError, match="Only Linux"):
            _detect_whisper_target()


class TestWhisperDownloadUrl:
    def test_cuda_url_uses_aria_releases(self):
        with patch("aria.__version__", "0.3.5"):
            url = _whisper_download_url("cuda")
        assert "malvavisc0/aria-ai" in url
        assert "whisper-server-cuda-12.6-x86_64.tar.gz" in url

    @patch("aria.scripts.voice.platform.machine", return_value="x86_64")
    def test_cpu_url_uses_official_whisper_releases(self, mock_machine):
        url = _whisper_download_url("cpu")
        assert "ggml-org/whisper.cpp" in url
        assert "whisper-bin-ubuntu-x64.tar.gz" in url

    @patch("aria.scripts.voice.platform.machine", return_value="aarch64")
    def test_cpu_url_arm64(self, mock_machine):
        url = _whisper_download_url("cpu")
        assert "whisper-bin-ubuntu-arm64.tar.gz" in url
