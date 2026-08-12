"""Tests for ARIA_VLLM_REMOTE (remote vLLM mode) behaviour."""

from unittest.mock import patch

from aria.preflight import (
    CheckResult,
    _check_binaries,
    _check_kv_cache_memory,
    _check_memory_requirements,
    _check_models,
)


class TestCheckBinariesRemoteMode:
    """_check_binaries should skip vLLM install check in remote mode."""

    def test_skips_vllm_check_in_remote_mode(self):
        """Should pass with 'remote' details when remote=True."""
        with patch("aria.config.api.Vllm.remote", True, create=True):
            checks: list[CheckResult] = []
            _check_binaries(checks)
            assert len(checks) == 1
            assert checks[0].passed is True
            assert "remote" in checks[0].details.lower()


class TestCheckModelsRemoteMode:
    """_check_models should skip chat model check in remote mode."""

    @patch("aria.config.api.Vllm")
    def test_skips_chat_model_in_remote_mode(self, mock_vllm):
        """Should only check embeddings model when remote=True."""
        mock_vllm.remote = True
        checks: list[CheckResult] = []
        _check_models(checks)
        # Only embeddings model should be checked, not chat
        names = [c.name for c in checks]
        assert "chat model" not in names


class TestCheckMemoryRemoteMode:
    """_check_memory_requirements should skip GPU checks in remote mode."""

    @patch("aria.config.api.Vllm")
    def test_skips_gpu_check_in_remote_mode(self, mock_vllm):
        """Should pass with 'remote' details when remote=True."""
        mock_vllm.remote = True
        checks: list[CheckResult] = []
        _check_memory_requirements(checks)
        assert len(checks) == 1
        assert checks[0].passed is True
        assert "remote" in checks[0].details.lower()


class TestCheckKvCacheRemoteMode:
    """_check_kv_cache_memory should be skipped in remote mode."""

    @patch("aria.config.api.Vllm")
    def test_skips_kv_cache_check_in_remote_mode(self, mock_vllm):
        """Should produce no checks when remote=True."""
        mock_vllm.remote = True
        checks: list[CheckResult] = []
        _check_kv_cache_memory(checks)
        assert len(checks) == 0
