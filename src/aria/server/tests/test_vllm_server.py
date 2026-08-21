"""Tests for VllmServerManager in server/vllm.py."""

import sys
from unittest.mock import patch

from aria.server.vllm import VllmServerManager


class TestBuildVllmCmd:
    """Tests for VllmServerManager._build_vllm_cmd()."""

    def setup_method(self):
        with patch("aria.server.vllm.load_state", return_value={}):
            self.manager = VllmServerManager()

    def test_uses_isolated_interpreter_not_sys_executable(self):
        """cmd[0] must be the isolated venv python, not Aria's sys.executable."""
        from aria.config.api import Vllm

        cmd = self.manager._build_vllm_cmd(
            model_path="/data/models/chat",
            port=9090,
        )
        assert cmd[0] == str(Vllm.get_python_executable())
        assert cmd[0] != sys.executable

    def test_basic_cmd_structure(self):
        """Command must include required vLLM entrypoint arguments."""
        cmd = self.manager._build_vllm_cmd(
            model_path="BAAI/bge-m3",
            port=9090,
        )
        assert "-m" in cmd
        assert "vllm.entrypoints.openai.api_server" in cmd
        assert "--model" in cmd
        assert "BAAI/bge-m3" in cmd
        assert "--port" in cmd
        assert "9090" in cmd
        assert "--api-key" in cmd
        assert "sk-aria" in cmd

    def test_embed_task_flag(self):
        """Embeddings server should use --runner pooling --convert embed."""
        cmd = self.manager._build_vllm_cmd(
            model_path="BAAI/bge-m3",
            port=9092,
            task="embed",
        )
        assert "--runner" in cmd
        assert "pooling" in cmd
        assert "--convert" in cmd
        assert "embed" in cmd

    def test_quantization_flag(self):
        """GPTQ quantization should auto-upgrade to gptq_marlin."""
        cmd = self.manager._build_vllm_cmd(
            model_path="/data/models/chat",
            port=9090,
            quantization="gptq",
        )
        assert "--quantization" in cmd
        assert "gptq_marlin" in cmd

    def test_gptq_forces_float16_dtype(self):
        """GPTQ quantization should force --dtype float16 when dtype is auto."""
        cmd = self.manager._build_vllm_cmd(
            model_path="/data/models/chat",
            port=9090,
            quantization="gptq",
            dtype="auto",
        )
        dtype_idx = cmd.index("--dtype")
        assert cmd[dtype_idx + 1] == "float16"

    def test_gptq_preserves_explicit_dtype(self):
        """GPTQ quantization should not override an explicit dtype."""
        cmd = self.manager._build_vllm_cmd(
            model_path="/data/models/chat",
            port=9090,
            quantization="gptq",
            dtype="float16",
        )
        dtype_idx = cmd.index("--dtype")
        assert cmd[dtype_idx + 1] == "float16"

    def test_quantization_not_added_when_none(self):
        """No --quantization flag when quantization is None."""
        cmd = self.manager._build_vllm_cmd(
            model_path="BAAI/bge-m3",
            port=9090,
            quantization=None,
        )
        assert "--quantization" not in cmd

    def test_tensor_parallel_flag(self):
        """Tensor parallel size > 1 should add --tensor-parallel-size."""
        cmd = self.manager._build_vllm_cmd(
            model_path="/data/models/chat",
            port=9090,
            tensor_parallel_size=2,
        )
        assert "--tensor-parallel-size" in cmd
        assert "2" in cmd

    def test_no_tensor_parallel_for_single_gpu(self):
        """No --tensor-parallel-size flag for single GPU."""
        cmd = self.manager._build_vllm_cmd(
            model_path="/data/models/chat",
            port=9090,
            tensor_parallel_size=1,
        )
        assert "--tensor-parallel-size" not in cmd

    def test_chat_template_not_added_for_embed(self):
        """Chat template should NOT be added for embedding task."""
        cmd = self.manager._build_vllm_cmd(
            model_path="BAAI/bge-m3",
            port=9092,
            task="embed",
            chat_template_file="/path/to/template.jinja",
        )
        assert "--chat-template" not in cmd


class TestKvCacheOffload:
    """Tests for KV cache RAM offload command construction."""

    def setup_method(self):
        with patch("aria.server.vllm.load_state", return_value={}):
            self.manager = VllmServerManager()

    def test_default_mode_adds_no_offload_flags(self):
        """Default 'off' mode should not add any offload flags."""
        cmd = self.manager._build_vllm_cmd(
            model_path="/data/models/chat",
            port=9090,
            kv_offload_mode="off",
        )
        assert "--kv-offloading-size" not in cmd
        assert "--kv-offloading-backend" not in cmd

    def test_ram_mode_adds_kv_offloading_size(self):
        """RAM mode with explicit size should add --kv-offloading-size."""
        cmd = self.manager._build_vllm_cmd(
            model_path="/data/models/chat",
            port=9090,
            kv_offload_mode="ram",
            kv_offloading_size_gb=8,
        )
        assert "--kv-offloading-size" in cmd
        size_idx = cmd.index("--kv-offloading-size")
        assert cmd[size_idx + 1] == "8"

    def test_ram_mode_adds_backend(self):
        """Should add --kv-offloading-backend with the specified backend."""
        cmd = self.manager._build_vllm_cmd(
            model_path="/data/models/chat",
            port=9090,
            kv_offload_mode="ram",
            kv_offloading_size_gb=8,
            kv_offloading_backend="lmcache",
        )
        assert "--kv-offloading-backend" in cmd
        backend_idx = cmd.index("--kv-offloading-backend")
        assert cmd[backend_idx + 1] == "lmcache"

    def test_ram_mode_no_size_adds_nothing(self):
        """RAM mode without a size should not add offload flags."""
        cmd = self.manager._build_vllm_cmd(
            model_path="/data/models/chat",
            port=9090,
            kv_offload_mode="ram",
            kv_offloading_size_gb=None,
        )
        assert "--kv-offloading-size" not in cmd
        assert "--kv-offloading-backend" not in cmd

    def test_auto_mode_with_size_adds_flags(self):
        """Auto mode with calculated size should add offload flags."""
        cmd = self.manager._build_vllm_cmd(
            model_path="/data/models/chat",
            port=9090,
            kv_offload_mode="auto",
            kv_offloading_size_gb=4,
        )
        assert "--kv-offloading-size" in cmd
        size_idx = cmd.index("--kv-offloading-size")
        assert cmd[size_idx + 1] == "4"
        assert "--kv-offloading-backend" in cmd

    def test_zero_size_adds_nothing(self):
        """Zero size should not add offload flags even with valid mode."""
        cmd = self.manager._build_vllm_cmd(
            model_path="/data/models/chat",
            port=9090,
            kv_offload_mode="ram",
            kv_offloading_size_gb=0,
        )
        assert "--kv-offloading-size" not in cmd
        assert "--kv-offloading-backend" not in cmd

    def test_native_backend_is_default(self):
        """Should default to native backend."""
        cmd = self.manager._build_vllm_cmd(
            model_path="/data/models/chat",
            port=9090,
            kv_offload_mode="ram",
            kv_offloading_size_gb=4,
        )
        backend_idx = cmd.index("--kv-offloading-backend")
        assert cmd[backend_idx + 1] == "native"

    def test_native_backend_availability_check(self):
        """Native backend should always be available."""
        assert self.manager._kv_offloading_backend_available("native") is True

    def test_lmcache_backend_availability_check(self):
        """lmcache backend should require the lmcache package."""
        with patch("aria.server.vllm.importlib.util.find_spec", return_value=None):
            assert self.manager._kv_offloading_backend_available("lmcache") is False


class TestStopAll:
    """Tests for VllmServerManager.stop_all()."""

    def setup_method(self):
        with patch("aria.server.vllm.load_state", return_value={}):
            self.manager = VllmServerManager()

    def test_stop_all_calls_stop_process_group(self):
        """stop_all() should call stop_process_group for each tracked PID."""
        self.manager._pids = {"chat": 1234, "embeddings": 5678}

        with (
            patch("aria.server.vllm.is_process_running", return_value=True),
            patch(
                "aria.server.vllm.VllmServerManager._find_orphan_pids",
                return_value=[],
            ),
            patch(
                "aria.server.vllm.stop_process_group", return_value=True
            ) as mock_stop,
            patch("aria.server.vllm.clear_state"),
        ):
            self.manager.stop_all()

        assert mock_stop.call_count == 2

    def test_stop_all_clears_pids(self):
        """stop_all() should clear the PID dict after stopping."""
        self.manager._pids = {"chat": 1234}

        # is_process_running returns True initially (so stop is attempted),
        # then False after kill (so it's considered dead)
        with (
            patch(
                "aria.server.vllm.is_process_running",
                side_effect=[True, False],
            ),
            patch("aria.server.vllm.stop_process_group", return_value=True),
            patch("aria.server.vllm.clear_state"),
        ):
            self.manager.stop_all()

        assert self.manager._pids == {}

    def test_stop_all_skips_dead_processes(self):
        """stop_all() should not call stop_process_group for dead processes."""
        self.manager._pids = {"chat": 9999}

        with (
            patch("aria.server.vllm.is_process_running", return_value=False),
            patch("aria.server.vllm.stop_process_group") as mock_stop,
            patch("aria.server.vllm.clear_state"),
        ):
            self.manager.stop_all()

        mock_stop.assert_not_called()

    def test_stop_all_preserves_survivors(self):
        """stop_all() should keep PIDs in file if processes survive."""
        self.manager._pids = {"chat": 1234}

        with (
            patch("aria.server.vllm.is_process_running", return_value=True),
            patch(
                "aria.server.vllm.VllmServerManager._find_orphan_pids",
                return_value=[],
            ),
            patch("aria.server.vllm.stop_process_group", return_value=False),
            patch("aria.server.vllm.save_state") as mock_save,
        ):
            self.manager.stop_all()

        # PID should still be tracked
        assert self.manager._pids == {"chat": 1234}
        mock_save.assert_called_once()

    def test_stop_all_skip_vllm(self):
        """stop_all(skip_vllm=True) should clear PIDs without killing."""
        self.manager._pids = {"chat": 1234}

        with (
            patch("aria.server.vllm.stop_process_group") as mock_stop,
            patch("aria.server.vllm.clear_state"),
        ):
            self.manager.stop_all(skip_vllm=True)

        mock_stop.assert_not_called()
        assert self.manager._pids == {}

    def test_start_all_force_restart(self):
        """start_all(force_restart=True) should stop existing first."""
        self.manager._pids = {"chat": 1234}

        with patch.object(self.manager, "stop_all") as mock_stop:
            # start_all will call stop_all (force_restart), then try to
            # actually start vLLM which fails, triggering another stop_all.
            # We just verify stop_all was called (at least once).
            try:
                self.manager.start_all(force_restart=True)
            except Exception:
                pass

        assert mock_stop.call_count >= 1


class TestPreflightPortCheck:
    """Tests for VllmServerManager preflight port-in-use detection."""

    def setup_method(self):
        with patch("aria.server.vllm.load_state", return_value={}):
            self.manager = VllmServerManager()

    def test_returns_immediately_when_port_is_free(self):
        """No action when the target port has no listener."""
        with (
            patch.object(self.manager, "_port_in_use", return_value=False) as mock_port,
            patch.object(self.manager, "_find_orphan_pids") as mock_orphans,
            patch("aria.server.vllm.stop_process_group") as mock_stop,
        ):
            self.manager._preflight_port_check(9090)

        mock_port.assert_called_once_with(9090)
        mock_orphans.assert_not_called()
        mock_stop.assert_not_called()

    def test_stops_stale_vllm_when_port_occupied(self):
        """Stale vLLM orphans are stopped automatically when port is in use."""
        with (
            patch.object(self.manager, "_port_in_use", side_effect=[True, False]),
            patch.object(self.manager, "_find_orphan_pids", return_value=[9999]),
            patch("aria.server.vllm.stop_process_group") as mock_stop,
            patch("aria.server.vllm.time.sleep"),
        ):
            self.manager._preflight_port_check(9090)

        mock_stop.assert_called_once_with(9999, timeout=10.0)

    def test_aborts_when_non_vllm_process_owns_port(self):
        """Port occupied by non-vLLM process raises actionable error."""
        with (
            patch.object(self.manager, "_port_in_use", return_value=True),
            patch.object(self.manager, "_find_orphan_pids", return_value=[]),
            patch("aria.server.vllm.stop_process_group") as mock_stop,
        ):
            try:
                self.manager._preflight_port_check(9090)
                raise AssertionError("Should have raised RuntimeError")
            except RuntimeError as e:
                assert "9090" in str(e)
                assert "lsof" in str(e)

        mock_stop.assert_not_called()

    def test_aborts_if_port_still_in_use_after_cleanup(self):
        """If orphans are killed but port stays occupied, abort."""
        with (
            patch.object(self.manager, "_port_in_use", return_value=True),
            patch.object(self.manager, "_find_orphan_pids", return_value=[9999]),
            patch("aria.server.vllm.stop_process_group"),
            patch("aria.server.vllm.time.sleep"),
        ):
            try:
                self.manager._preflight_port_check(9090)
                raise AssertionError("Should have raised RuntimeError")
            except RuntimeError as e:
                assert "still in use" in str(e)


class TestMambaClampedCmd:
    """Tests for VllmServerManager._mamba_clamped_cmd() — the hybrid-model
    max_num_seqs retry. The parser must only fire on the exact Mamba-cache
    error and clamp using vLLM's own reported capacity."""

    def _log(self, tmp_path, text: str):
        f = tmp_path / "vllm.log"
        f.write_text(text)
        return f

    def test_parses_capacity_and_appends_flag(self, tmp_path):
        log = self._log(
            tmp_path,
            "ValueError: max_num_seqs (256) exceeds available Mamba cache "
            "blocks (184). Each decode sequence requires one Mamba cache block.",
        )
        cmd = ["python", "-m", "vllm.entrypoints.openai.api_server", "--model", "m"]
        out = VllmServerManager._mamba_clamped_cmd(cmd, log)
        assert out is not None
        i = out.index("--max-num-seqs")
        assert out[i + 1] == "184"

    def test_clamps_down_existing_flag(self, tmp_path):
        log = self._log(
            tmp_path,
            "max_num_seqs (256) exceeds available Mamba cache blocks (184).",
        )
        cmd = ["python", "--max-num-seqs", "256"]
        out = VllmServerManager._mamba_clamped_cmd(cmd, log)
        assert out[out.index("--max-num-seqs") + 1] == "184"

    def test_never_raises_a_lower_user_value(self, tmp_path):
        """A user-set max_num_seqs already under capacity is left alone
        (returns None → no retry, the failure was something else)."""
        log = self._log(
            tmp_path,
            "max_num_seqs (256) exceeds available Mamba cache blocks (184).",
        )
        cmd = ["python", "--max-num-seqs", "128"]
        assert VllmServerManager._mamba_clamped_cmd(cmd, log) is None

    def test_ignores_unrelated_error(self, tmp_path):
        log = self._log(tmp_path, "ValueError: some other startup failure")
        cmd = ["python", "--model", "m"]
        assert VllmServerManager._mamba_clamped_cmd(cmd, log) is None

    def test_missing_log_returns_none(self, tmp_path):
        cmd = ["python", "--model", "m"]
        assert VllmServerManager._mamba_clamped_cmd(cmd, tmp_path / "nope.log") is None
        assert VllmServerManager._mamba_clamped_cmd(cmd, None) is None
