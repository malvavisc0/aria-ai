"""Tests for new preflight checks (LLM server, knowledge DB, tool loading)."""

from unittest.mock import MagicMock, patch

from aria.preflight import run_preflight_checks


class TestCheckLlmServer:
    """Test LLM server connectivity check (non-blocking)."""

    @patch("httpx.get")
    def test_llm_server_reachable(self, mock_get):
        """Should pass with model count when server responds."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"id": "model-1"}]}
        mock_get.return_value = mock_resp

        from aria.preflight import _check_llm_server

        checks = []
        _check_llm_server(checks)
        assert len(checks) == 1
        assert checks[0].passed is True
        assert checks[0].category == "connectivity"
        assert "model" in checks[0].details

    @patch("httpx.get")
    def test_llm_server_unreachable_is_non_blocking(self, mock_get):
        """Should pass even when server is unreachable (non-blocking)."""
        import httpx

        mock_get.side_effect = httpx.ConnectError("refused")

        from aria.preflight import _check_llm_server

        checks = []
        _check_llm_server(checks)
        assert len(checks) == 1
        assert checks[0].passed is True
        assert checks[0].category == "connectivity"
        assert "not running" in checks[0].details.lower()


class TestCheckMemoryDb:
    """Test memory database check."""

    @patch("aria.tools.memory.database.MemoryDatabase.__new__")
    def test_memory_db_accessible(self, mock_new):
        """Should pass when memory DB is accessible."""
        mock_new.return_value = MagicMock()

        from aria.preflight import _check_memory_db

        checks = []
        _check_memory_db(checks)
        assert len(checks) == 1
        assert checks[0].passed is True
        assert checks[0].category == "storage"

    @patch(
        "aria.tools.memory.database.MemoryDatabase.__init__",
        side_effect=Exception("DB not found"),
    )
    def test_memory_db_fails(self, mock_init):
        """Should fail when memory DB raises an error."""
        from aria.preflight import _check_memory_db

        checks = []
        _check_memory_db(checks)
        assert len(checks) == 1
        assert checks[0].passed is False
        assert checks[0].category == "storage"


class TestCheckToolLoading:
    """Test tool loading check."""

    def test_tool_loading_ok(self):
        """Should pass when tools load correctly."""
        from aria.preflight import _check_tool_loading

        checks = []
        _check_tool_loading(checks)
        assert len(checks) == 1
        assert checks[0].passed is True
        assert checks[0].category == "tools"
        assert "11" in checks[0].details

    @patch("aria.tools.registry.get_tools")
    def test_tool_loading_fails(self, mock_get_tools):
        """Should fail when tool loading raises an error."""
        mock_get_tools.side_effect = Exception("Import error")

        from aria.preflight import _check_tool_loading

        checks = []
        _check_tool_loading(checks)
        assert len(checks) == 1
        assert checks[0].passed is False
        assert checks[0].category == "tools"


class TestCheckKvCacheMemory:
    """Test KV cache memory preflight check."""

    @patch("aria.helpers.memory.detect_system_ram", return_value=(32768, 28000))
    @patch("aria.helpers.nvidia.get_free_vram_per_gpu", return_value=[20000])
    @patch("aria.helpers.nvidia.get_total_vram_mb", return_value=24576)
    @patch("aria.helpers.nvidia._estimate_kv_cache_mb", return_value=5000)
    @patch("aria.helpers.memory.get_model_file_size", return_value=4000)
    @patch("aria.config.models.Chat")
    @patch("aria.config.api.Vllm")
    def test_kv_cache_fits_in_vram(self, mock_vllm, mock_chat, *args):
        """Should pass with VRAM detail when KV cache fits."""
        mock_vllm.remote = False
        mock_chat.model_path = "/models/chat"
        mock_vllm.chat_context_size = 32768
        mock_vllm.kv_cache_dtype = "auto"
        mock_vllm.kv_offload_mode = "off"
        mock_vllm.tensor_parallel_size = 1

        from aria.preflight import _check_kv_cache_memory

        checks = []
        _check_kv_cache_memory(checks)
        assert len(checks) == 1
        assert checks[0].passed is True
        assert "needed" in checks[0].details
        assert "free" in checks[0].details

    @patch("aria.helpers.memory.detect_system_ram", return_value=(32768, 28000))
    @patch("aria.helpers.nvidia.get_free_vram_per_gpu", return_value=[2000])
    @patch("aria.helpers.nvidia.get_total_vram_mb", return_value=8192)
    @patch("aria.helpers.nvidia._estimate_kv_cache_mb", return_value=10000)
    @patch("aria.helpers.memory.get_model_file_size", return_value=5000)
    @patch("aria.config.models.Chat")
    @patch("aria.config.api.Vllm")
    def test_kv_cache_vram_tight_off_mode(self, mock_vllm, mock_chat, *args):
        """Should pass (warning) when VRAM tight and mode is off."""
        mock_vllm.remote = False
        mock_chat.model_path = "/models/chat"
        mock_vllm.chat_context_size = 131072
        mock_vllm.kv_cache_dtype = "auto"
        mock_vllm.kv_offload_mode = "off"
        mock_vllm.tensor_parallel_size = 1

        from aria.preflight import _check_kv_cache_memory

        checks = []
        _check_kv_cache_memory(checks)
        assert len(checks) == 1
        assert checks[0].passed is True  # Warning only
        assert "needed >" in checks[0].details
        assert "Consider ARIA_VLLM_KV_OFFLOAD_MODE=auto" in checks[0].details

    @patch("aria.helpers.memory.detect_system_ram", return_value=(32768, 28000))
    @patch("aria.helpers.nvidia.get_free_vram_per_gpu", return_value=[2000])
    @patch("aria.helpers.nvidia.get_total_vram_mb", return_value=8192)
    @patch("aria.helpers.nvidia._estimate_kv_cache_mb", return_value=10000)
    @patch("aria.helpers.memory.get_model_file_size", return_value=5000)
    @patch("aria.config.models.Chat")
    @patch("aria.config.api.Vllm")
    def test_kv_cache_offloaded_to_ram(self, mock_vllm, mock_chat, *args):
        """Should pass when VRAM tight but RAM sufficient in auto mode."""
        mock_vllm.remote = False
        mock_chat.model_path = "/models/chat"
        mock_vllm.chat_context_size = 131072
        mock_vllm.kv_cache_dtype = "auto"
        mock_vllm.kv_offload_mode = "auto"
        mock_vllm.tensor_parallel_size = 1

        from aria.preflight import _check_kv_cache_memory

        checks = []
        _check_kv_cache_memory(checks)
        assert len(checks) == 1
        assert checks[0].passed is True
        assert "offloaded to RAM" in checks[0].details

    @patch("aria.helpers.memory.detect_system_ram", return_value=(8192, 6000))
    @patch("aria.helpers.nvidia.get_free_vram_per_gpu", return_value=[2000])
    @patch("aria.helpers.nvidia.get_total_vram_mb", return_value=8192)
    @patch("aria.helpers.nvidia._estimate_kv_cache_mb", return_value=10000)
    @patch("aria.helpers.memory.get_model_file_size", return_value=5000)
    @patch("aria.config.models.Chat")
    @patch("aria.config.api.Vllm")
    def test_kv_cache_ram_insufficient(self, mock_vllm, mock_chat, *args):
        """Should fail when neither VRAM nor RAM can hold KV cache."""
        mock_vllm.remote = False
        mock_chat.model_path = "/models/chat"
        mock_vllm.chat_context_size = 131072
        mock_vllm.kv_cache_dtype = "auto"
        mock_vllm.kv_offload_mode = "auto"
        mock_vllm.tensor_parallel_size = 1

        from aria.preflight import _check_kv_cache_memory

        checks = []
        _check_kv_cache_memory(checks)
        assert len(checks) == 1
        assert checks[0].passed is False
        assert "needs" in checks[0].error
        assert "CHAT_CONTEXT_SIZE" in checks[0].hint

    @patch(
        "aria.server.vllm.VllmServerManager._kv_offloading_backend_available",
        return_value=False,
    )
    @patch(
        "aria.server.vllm.VllmServerManager._resolve_max_model_len",
        side_effect=lambda model_path, context_size: context_size,
    )
    @patch("aria.helpers.memory.detect_system_ram", return_value=(32768, 28000))
    @patch("aria.helpers.nvidia.get_free_vram_per_gpu", return_value=[2000])
    @patch("aria.helpers.nvidia.get_total_vram_mb", return_value=8192)
    @patch("aria.helpers.nvidia._estimate_kv_cache_mb", return_value=10000)
    @patch("aria.helpers.memory.get_model_file_size", return_value=5000)
    @patch("aria.config.models.Chat")
    @patch("aria.config.api.Vllm")
    def test_kv_cache_backend_unavailable(self, mock_vllm, mock_chat, *args):
        """Should fail when selected backend is unavailable."""
        mock_vllm.remote = False
        mock_chat.model_path = "/models/chat"
        mock_vllm.chat_context_size = 131072
        mock_vllm.kv_cache_dtype = "auto"
        mock_vllm.kv_offload_mode = "auto"
        mock_vllm.tensor_parallel_size = 1
        mock_vllm.kv_offloading_backend = "lmcache"

        from aria.preflight import _check_kv_cache_memory

        checks = []
        _check_kv_cache_memory(checks)
        assert len(checks) == 1
        assert checks[0].passed is False
        assert "backend" in checks[0].error.lower()
        assert "native" in checks[0].hint

    @patch(
        "aria.server.vllm.VllmServerManager._kv_offloading_backend_available",
        return_value=True,
    )
    @patch(
        "aria.server.vllm.VllmServerManager._resolve_max_model_len",
        return_value=32768,
    )
    @patch("aria.helpers.memory.detect_system_ram", return_value=(8192, 6000))
    @patch("aria.helpers.nvidia.get_free_vram_per_gpu", return_value=[2000])
    @patch("aria.helpers.nvidia.get_total_vram_mb", return_value=8192)
    @patch("aria.helpers.nvidia._estimate_kv_cache_mb", return_value=10000)
    @patch("aria.helpers.memory.get_model_file_size", return_value=5000)
    @patch("aria.config.models.Chat")
    @patch("aria.config.api.Vllm")
    def test_kv_cache_uses_clamped_context_for_hint(self, mock_vllm, mock_chat, *args):
        """Should reference the clamped context size in failure hints."""
        mock_vllm.remote = False
        mock_chat.model_path = "/models/chat"
        mock_vllm.chat_context_size = 131072
        mock_vllm.kv_cache_dtype = "auto"
        mock_vllm.kv_offload_mode = "auto"
        mock_vllm.tensor_parallel_size = 1

        from aria.preflight import _check_kv_cache_memory

        checks = []
        _check_kv_cache_memory(checks)
        assert len(checks) == 1
        assert checks[0].passed is False
        assert "32768" in checks[0].hint


class TestRunPreflightChecks:
    """Test that run_preflight_checks includes new checks."""

    def test_includes_new_categories(self):
        """Preflight result should include connectivity and tools checks."""
        result = run_preflight_checks()
        categories = {c.category for c in result.checks}
        assert "connectivity" in categories
        assert "tools" in categories
