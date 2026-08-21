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


class TestDownloadWhisperCppCudaFallback:
    """The CUDA build is hosted on Aria's own releases and may be absent
    (asset 404) for some versions. The download must fall back to the
    CPU prebuilt so the wizard/CLI install still succeeds — parity."""

    @patch("aria.scripts.voice._extract_whisper_binary")
    @patch("aria.scripts.voice._download_file")
    @patch("aria.scripts.voice._detect_whisper_target", return_value="cuda")
    @patch("aria.config.api.Voice.whisper_model", "large-v3-turbo-q5_0")
    @patch("aria.scripts.voice.Bin.path")
    @patch("aria.scripts.voice.Models.path")
    def test_falls_back_to_cpu_on_cuda_404(
        self, _models, _bin, _detect, mock_dl, _extract, tmp_path
    ) -> None:

        import aria.scripts.voice as v

        _bin.__truediv__ = lambda self, other: tmp_path / other
        _models.__truediv__ = lambda self, other: tmp_path / other
        binary = tmp_path / "whisper-server"
        binary.touch()
        _extract.return_value = binary

        calls = []

        def _fake_download(url, dest):
            calls.append(url)
            if "malvavisc0/aria-ai" in url:
                raise RuntimeError("Failed to download from x: HTTP 404 Not Found")

        mock_dl.side_effect = _fake_download

        v.download_whisper_cpp()

        # CUDA attempted first, then the CPU fallback binary, then the GGUF
        # model named after the configured Voice.whisper_model (not a hardcoded
        # base.en) so the downloaded file matches the preflight check's path.
        assert "malvavisc0/aria-ai" in calls[0]
        assert "ggml-org/whisper.cpp" in calls[1]
        assert calls[2].endswith("ggml-large-v3-turbo-q5_0.bin")

    @patch("aria.scripts.voice._download_file")
    @patch("aria.scripts.voice._detect_whisper_target", return_value="cuda")
    def test_non_404_cuda_error_is_raised(self, _detect, mock_dl) -> None:
        import aria.scripts.voice as v

        mock_dl.side_effect = RuntimeError("Failed to download from x: HTTP 500")
        with __import__("pytest").raises(RuntimeError, match="500"):
            v.download_whisper_cpp()


class TestDownloadWhisperModelDefault:
    """``download_whisper_cpp()`` with no model must resolve the configured
    ``Voice.whisper_model`` (not a hardcoded base.en) so the downloaded
    GGUF file matches the path the preflight check expects — otherwise
    the wizard/CLI install a model the check never finds (the bug where
    the Download button reappeared after a successful install)."""

    @patch("aria.scripts.voice._extract_whisper_binary")
    @patch("aria.scripts.voice._download_file")
    @patch("aria.scripts.voice._detect_whisper_target", return_value="cpu")
    @patch("aria.config.api.Voice.whisper_model", "large-v3-turbo-q5_0")
    @patch("aria.scripts.voice.Bin.path")
    @patch("aria.scripts.voice.Models.path")
    def test_no_model_uses_configured_default(
        self, _models, _bin, _detect, mock_dl, _extract, tmp_path
    ) -> None:
        import aria.scripts.voice as v

        _bin.__truediv__ = lambda self, other: tmp_path / other
        _models.__truediv__ = lambda self, other: tmp_path / other
        binary = tmp_path / "whisper-server"
        binary.touch()
        _extract.return_value = binary

        v.download_whisper_cpp()

        # The model URL (the one pointing at huggingface.co) uses the
        # configured name, not a hardcoded base.en.
        model_urls = [
            str(c) for c in mock_dl.call_args_list if "huggingface.co" in str(c)
        ]
        assert model_urls, "expected a HuggingFace model download"
        assert "ggml-large-v3-turbo-q5_0.bin" in model_urls[0]
        assert "ggml-base.en.bin" not in model_urls[0]
