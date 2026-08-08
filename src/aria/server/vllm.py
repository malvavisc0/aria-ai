"""vLLM inference server manager.

Manages the vLLM chat process required by the Aria web UI:
  - Chat server (port 9090): ``python -m vllm.entrypoints.openai.api_server``

Process state is persisted to ``data/vllm_servers.json`` so the manager
can track servers started by other processes (e.g. CLI to GUI).

Example:
    ```python
    from aria.server.vllm import VllmServerManager

    manager = VllmServerManager()
    manager.start_all()   # starts chat, waits for /health
    # ... run Chainlit ...
    manager.stop_all()    # graceful shutdown
    ```
"""

import importlib.util
import json
import math
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import NamedTuple
from urllib.error import URLError
from urllib.request import urlopen

from loguru import logger

from aria.config.folders import Data as DataConfig
from aria.helpers.nvidia import (
    _estimate_kv_cache_mb,
    calculate_gpu_memory_utilization,
    get_free_vram_per_gpu,
    get_per_gpu_vram_mb,
)
from aria.server.process_utils import (
    clear_state,
    is_process_running,
    load_state,
    save_state,
    stop_process_group,
)


def _apply_flags(cmd: list[str], flags: list[tuple[str, object, bool]]) -> None:
    """Extend ``cmd`` from a ``(flag, value, condition)`` table.

    - ``value is None`` → boolean flag (append ``flag`` only).
    - ``value`` is a list/tuple → ``flag`` followed by each element.
    - otherwise → ``[flag, str(value)]``.
    """
    for flag, value, cond in flags:
        if not cond:
            continue
        if value is None:
            cmd.append(flag)
        elif isinstance(value, (list, tuple)):
            cmd.append(flag)
            cmd.extend(str(x) for x in value)
        else:
            cmd.append(flag)
            cmd.append(str(value))


def _resolve_quant_and_dtype(
    quantization: str | None, dtype: str
) -> tuple[str | None, str]:
    """Resolve effective quantization (gptq→gptq_marlin) and dtype."""
    effective_quant: str | None = None
    if quantization:
        # vLLM v0.20+: gptq kernel is buggy for 4-bit; use gptq_marlin
        effective_quant = "gptq_marlin" if quantization == "gptq" else quantization
    effective_dtype = dtype
    # GPTQ only supports float16
    if (
        effective_quant is not None
        and effective_quant.startswith("gptq")
        and dtype == "auto"
    ):
        effective_dtype = "float16"
    return effective_quant, effective_dtype


class _KvBreakdown(NamedTuple):
    """Per-GPU memory breakdown used for KV-cache context clamping."""

    tp: int
    total_vram_mb: int
    managed_vram_mb: int
    per_gpu_model_mb: float
    overhead_mb: int
    available_kv_mb: float


def _kv_offloading_active(
    kv_offload_mode: str, kv_offloading_size_gb: float | None
) -> bool:
    """True when KV RAM offloading is actually in effect (mode + positive size)."""
    return (
        kv_offload_mode in ("auto", "ram")
        and kv_offloading_size_gb is not None
        and kv_offloading_size_gb > 0
    )


def _resolve_kv_cache_flags(
    kv_cache_dtype: str,
    offloading_active: bool,
    kv_offloading_backend: str,
    vision_enabled: bool,
) -> list[str]:
    """Build kv-cache-dtype/attention-backend flags.

    When KV offloading is active with the native backend, force
    kv_cache_dtype to fp16 ("auto"): the OffloadingConnector doesn't support
    HMA, so we disable it, but HMA-disabled mode requires all KV cache specs
    to be one unified type (fp8 on GPU + fp16 offload = two types → crash).
    """
    flags: list[str] = []
    if offloading_active and kv_offloading_backend == "native":
        if kv_cache_dtype and kv_cache_dtype != "auto":
            logger.info(
                "KV offloading with native backend: forcing "
                "kv_cache_dtype from {orig} to auto (fp16) — "
                "native OffloadingConnector is incompatible with "
                "fp8 KV cache and HMA-disabled mode.",
                orig=kv_cache_dtype,
            )
            kv_cache_dtype = "auto"

    if kv_cache_dtype and kv_cache_dtype != "auto":
        flags.extend(["--kv-cache-dtype", kv_cache_dtype])
        if kv_cache_dtype.startswith("fp8") and not vision_enabled:
            # FlashAttention v2 doesn't support fp8 KV cache — switch to FlashInfer.
            # Skip for vision/multimodal models where FlashInfer doesn't support
            # partial multimodal token full attention; vLLM auto-selects a backend.
            flags.extend(["--attention-backend", "flashinfer"])
    return flags


def _kv_offload_flags(
    kv_offload_mode: str,
    kv_offloading_size_gb: float | None,
    kv_offloading_backend: str,
    offloading_active: bool,
) -> list[str]:
    """Build the kv-offloading-size/backend/disable-hybrid flags when active."""
    if not offloading_active or kv_offloading_size_gb is None:
        return []
    logger.info(
        "KV cache offload enabled: {size} GiB via {backend} backend (mode={mode})",
        size=kv_offloading_size_gb,
        backend=kv_offloading_backend,
        mode=kv_offload_mode,
    )
    # OffloadingConnector is incompatible with HMA (Hybrid KV Cache Manager).
    return [
        "--kv-offloading-size",
        str(kv_offloading_size_gb),
        "--kv-offloading-backend",
        kv_offloading_backend,
        "--disable-hybrid-kv-cache-manager",
    ]


class VllmServerManager:
    """Manages vLLM inference server processes for chat.

    All chat servers are launched as
    ``python -m vllm.entrypoints.openai.api_server`` with model-specific flags.

    Process state is persisted to ``data/vllm_servers.json`` so the manager
    can track servers started by other processes (e.g. CLI to GUI).

    Args:
        host: Host address for all servers.

    Example:
        ```python
        manager = VllmServerManager()
        manager.start_all()
        # ... run Chainlit ...
        manager.stop_all()
        ```
    """

    PID_FILE = DataConfig.path / "vllm_servers.json"
    HEALTH_POLL_INTERVAL = 1.0
    HEALTH_TIMEOUT = 300  # vLLM model loading can take longer than llama.cpp

    def __init__(
        self,
        host: str = "0.0.0.0",
    ):
        self._host = host
        self._pids: dict[str, int] = self._load_valid_pids()

    def _load_valid_pids(self) -> dict[str, int]:
        """Load PIDs from state file, filtering to only running processes."""
        state = load_state(self.PID_FILE)
        return {
            role: pid
            for role, pid in state.items()
            if isinstance(pid, int) and is_process_running(pid)
        }

    def _save_pids(self) -> None:
        """Save current PIDs to state file."""
        save_state(self.PID_FILE, self._pids)

    @staticmethod
    def _get_model_max_context(model_path: str) -> int | None:
        """Read the model's maximum context length from its config.json.

        Inspects ``max_position_embeddings``, ``model_max_length``, or
        ``max_seq_len`` fields in the model's config file.

        Args:
            model_path: Local path to the model directory.

        Returns:
            The model's maximum context length, or None if it cannot
            be determined.
        """
        config_path = Path(model_path) / "config.json"
        if not config_path.is_file():
            return None
        try:
            with open(config_path) as f:
                config = json.load(f)
            # Architecture parameters may live at the top level (e.g. Llama,
            # Mistral-7B) or nested inside "text_config" for multimodal /
            # vision models (e.g. Mistral3 / Pixtral, LLaVA).
            text_cfg = config.get("text_config") or {}
            for key in (
                "max_position_embeddings",
                "model_max_length",
                "max_seq_len",
            ):
                val = config.get(key) or text_cfg.get(key)
                if isinstance(val, (int, float)) and val > 0:
                    return int(val)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not read model config at {config_path}: {e}")
        return None

    @classmethod
    def _resolve_max_model_len(cls, model_path: str, requested_context: int) -> int:
        """Clamp requested context length to the model's supported maximum."""
        model_max = cls._get_model_max_context(model_path)
        if model_max is not None and requested_context > model_max:
            logger.info(
                f"Clamping max_model_len from {requested_context} to "
                f"{model_max} (model's max_position_embeddings)"
            )
            return model_max
        return requested_context

    @staticmethod
    def _available_kv_breakdown(
        model_path: str,
        gpu_memory_utilization: float,
        tensor_parallel_size: int,
        enforce_eager: bool,
    ) -> _KvBreakdown | None:
        """Compute the per-GPU memory available for the KV cache.

        Returns ``None`` when VRAM or model size cannot be determined —
        the caller should then skip clamping and let vLLM decide.
        """
        from aria.helpers.memory import get_model_file_size
        from aria.helpers.nvidia import estimate_per_gpu_memory_mb

        total_vram_mb = get_per_gpu_vram_mb()
        if total_vram_mb <= 0:
            return None

        model_size_mb = get_model_file_size(Path(model_path))
        if model_size_mb <= 0:
            return None

        # vLLM overhead: activation/scratch buffers and CUDA context.
        # CUDA graph memory is profiled separately by vLLM v0.21+,
        # so we only need to account for the non-profiled fixed costs.
        # Eager mode (--enforce-eager) skips graph capture entirely, so
        # its overhead is lower.  Keep in sync with
        # calculate_gpu_memory_utilization()'s defaults.
        overhead_mb = 768 if enforce_eager else 1536
        tp = max(1, tensor_parallel_size)

        managed_vram_mb = int(total_vram_mb * gpu_memory_utilization)
        per_gpu_model_mb, _, _ = estimate_per_gpu_memory_mb(
            model_weights_mb=model_size_mb,
            kv_cache_mb=0,
            tensor_parallel_size=tp,
            overhead_mb=overhead_mb,
        )
        available_kv_mb = managed_vram_mb - per_gpu_model_mb - overhead_mb
        if available_kv_mb <= 0:
            return None

        return _KvBreakdown(
            tp=tp,
            total_vram_mb=total_vram_mb,
            managed_vram_mb=managed_vram_mb,
            per_gpu_model_mb=per_gpu_model_mb,
            overhead_mb=overhead_mb,
            available_kv_mb=available_kv_mb,
        )

    @staticmethod
    def _max_context_for_kv(
        model_path: str,
        available_kv_mb: float,
        tp: int,
        kv_cache_dtype: str,
    ) -> int | None:
        """Derive the largest context length that fits *available_kv_mb*.

        Uses a small reference context to compute per-token KV bytes per
        GPU, then scales.  Returns ``None`` when the estimate fails.
        """
        reference_ctx = 4096
        kv_ref_mb = _estimate_kv_cache_mb(model_path, reference_ctx, kv_cache_dtype)
        if kv_ref_mb is None or kv_ref_mb <= 0:
            return None

        kv_ref_per_gpu_mb = kv_ref_mb / tp
        bytes_per_token_per_gpu = (kv_ref_per_gpu_mb * 1024 * 1024) / reference_ctx
        max_context = int((available_kv_mb * 1024 * 1024) / bytes_per_token_per_gpu)

        # Align down to 256 (vLLM's KV cache block size) for clean allocation
        return (max_context // 256) * 256

    @staticmethod
    def _clamp_context_to_gpu_kv(
        model_path: str,
        requested_context: int,
        gpu_memory_utilization: float,
        kv_cache_dtype: str,
        tensor_parallel_size: int = 1,
        enforce_eager: bool = False,
    ) -> int:
        """Clamp ``max_model_len`` to what the GPU KV cache can hold.

        vLLM requires the GPU KV cache to hold at least **one** request
        at ``max_model_len``.  KV offloading to CPU RAM only helps with
        *concurrent* requests — it cannot extend the per-request maximum.

        This method estimates the available per-GPU KV cache memory and
        auto-reduces ``max_model_len`` if the requested context would
        overflow.  A warning is logged with the full breakdown so the
        user understands why the clamp occurred.

        When ``tensor_parallel_size > 1``, model weights and KV cache are
        sharded across GPUs, so per-GPU memory is divided accordingly.

        Args:
            model_path: Path to the model directory.
            requested_context: Desired ``max_model_len``.
            gpu_memory_utilization: vLLM ``gpu_memory_utilization`` fraction.
            kv_cache_dtype: KV cache data type (``auto``, ``fp8``, etc.).
            tensor_parallel_size: Number of GPUs for tensor parallelism.
                Model weights and KV cache are divided by this to get
                per-GPU memory.  Default 1 (single GPU).

        Returns:
            Effective ``max_model_len`` — either the requested value or
            the maximum the GPU can support, whichever is smaller.
        """
        breakdown = VllmServerManager._available_kv_breakdown(
            model_path,
            gpu_memory_utilization,
            tensor_parallel_size,
            enforce_eager,
        )
        if breakdown is None:
            return requested_context

        kv_mb = _estimate_kv_cache_mb(model_path, requested_context, kv_cache_dtype)
        if kv_mb is None or kv_mb <= 0:
            return requested_context

        per_gpu_kv_mb = kv_mb / breakdown.tp
        if per_gpu_kv_mb <= breakdown.available_kv_mb:
            return requested_context

        max_context = VllmServerManager._max_context_for_kv(
            model_path, breakdown.available_kv_mb, breakdown.tp, kv_cache_dtype
        )
        if max_context is None or max_context >= requested_context:
            return requested_context

        per_gpu_kv_clamped_mb = _estimate_kv_cache_mb(
            model_path, max_context, kv_cache_dtype
        )
        if per_gpu_kv_clamped_mb is not None:
            per_gpu_kv_clamped_mb = int(per_gpu_kv_clamped_mb / breakdown.tp)
        else:
            per_gpu_kv_clamped_mb = 0
        logger.warning(
            "Auto-clamping max_model_len: {requested:,} → {clamped:,}\n"
            "  Reason: GPU KV cache cannot fit {requested:,} tokens.\n"
            "  vLLM requires the GPU KV cache to hold at least one\n"
            "  request at max_model_len.  KV offloading to CPU RAM\n"
            "  only helps with concurrent requests, not per-request\n"
            "  context length.\n"
            "  ─────────────────────────────────────────────\n"
            "  Tensor parallel:     {tp:>8}\n"
            "  VRAM per GPU:        {vram:>8,} MiB\n"
            "  GPU utilization:     {util:>8.0%}\n"
            "  Managed VRAM/GPU:    {managed:>8,} MiB\n"
            "  Model weights/GPU:   {model:>8,.0f} MiB\n"
            "  vLLM overhead:       {overhead:>8,} MiB\n"
            "  Available for KV:    {avail:>8,.0f} MiB\n"
            "  KV needed (orig):    {kv_orig:>8,.0f} MiB/GPU  "
            "({requested:,} tokens, {dtype})\n"
            "  KV needed (clamped): {kv_clmp:>8,.0f} MiB/GPU  "
            "({clamped:,} tokens, {dtype})",
            requested=requested_context,
            clamped=max_context,
            tp=breakdown.tp,
            vram=breakdown.total_vram_mb,
            util=gpu_memory_utilization,
            managed=breakdown.managed_vram_mb,
            model=breakdown.per_gpu_model_mb,
            overhead=breakdown.overhead_mb,
            avail=breakdown.available_kv_mb,
            kv_orig=per_gpu_kv_mb,
            kv_clmp=per_gpu_kv_clamped_mb,
            dtype=kv_cache_dtype,
        )
        return max_context

    @staticmethod
    def _kv_offloading_backend_available(backend: str) -> bool:
        """Return whether the requested KV offloading backend is usable."""
        if backend == "native":
            return True
        if backend == "lmcache":
            return importlib.util.find_spec("lmcache") is not None
        return False

    def _clear_pids(self) -> None:
        """Clear state file and reset in-memory PIDs."""
        self._pids.clear()
        clear_state(self.PID_FILE)

    @staticmethod
    def _find_orphan_pids() -> list[int]:
        """Scan for running vLLM processes not tracked by the PID file.

        Uses ``pgrep`` to find processes matching the vLLM entrypoint
        command pattern. Returns only the group-leader PIDs (lowest PID
        per process group) so that ``stop_process_group`` can kill the
        entire tree.

        Returns:
            Sorted list of vLLM group-leader PIDs found on the system.
        """
        try:
            result = subprocess.run(
                ["pgrep", "-f", "vllm.entrypoints.openai.api_server"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return []
        except (FileNotFoundError, OSError):
            return []

        pids = [int(p) for p in result.stdout.strip().split("\n") if p.strip()]
        if not pids:
            return []

        # Determine group leaders: for each PID get its PGID, keep only
        # those where PID == PGID (i.e. group leaders started with
        # start_new_session=True).
        leaders: set[int] = set()
        for pid in pids:
            try:
                pgid = os.getpgid(pid)
                leaders.add(pgid)
            except (OSError, ProcessLookupError):
                # Process vanished between pgrep and getpgid
                continue

        return sorted(leaders)

    @staticmethod
    def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
        """Return True if *port* already has a listener on *host*.

        Uses a raw TCP connect (no HTTP) so it detects any process bound
        to the port, not just a healthy vLLM server.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        try:
            return sock.connect_ex((host, port)) == 0
        finally:
            sock.close()

    def _preflight_port_check(self, port: int) -> None:
        """Detect and clean up stale vLLM processes before starting.

        When a previous aria instance was killed (not shut down gracefully),
        its vLLM child can survive as an orphan — holding VRAM and the
        target port.  Starting a new vLLM alongside produces a confusing
        ``OSError: Address already in use`` or, worse, a silently wrong
        GPU-memory clamp (low free VRAM → tiny context → history eviction).

        This check runs before any server config is computed:

        1. If the port is free, return immediately (the common case).
        2. If the port is occupied **by a vLLM orphan** we own, stop it
           automatically and log clearly.
        3. If the port is occupied by something else, abort with an
           actionable error so the user can stop it manually.

        Args:
            port: Target port for the new vLLM server.
        """
        if not self._port_in_use(port):
            return

        logger.warning(
            f"Port {port} is already in use — checking for stale vLLM processes..."
        )

        # Try to identify the process listening on the port.
        stale_pids = self._find_orphan_pids()

        if not stale_pids:
            raise RuntimeError(
                f"Port {port} is already in use by a non-vLLM process. "
                f"Stop it manually before starting aria:\n"
                f"  lsof -ti :{port} | xargs kill"
            )

        logger.info(
            f"Found {len(stale_pids)} stale vLLM process group(s) on "
            f"port {port}: {stale_pids} — stopping them..."
        )
        for pid in stale_pids:
            stop_process_group(pid, timeout=10.0)

        # Give the OS a moment to release the port.
        time.sleep(1)

        if self._port_in_use(port):
            raise RuntimeError(
                f"Port {port} is still in use after stopping stale vLLM "
                f"processes. A non-vLLM process may be holding it.\n"
                f"  lsof -ti :{port} | xargs kill"
            )

        logger.info(f"Port {port} is now free after cleaning up stale vLLM.")

    def _build_vllm_cmd(
        self,
        model_path: str,
        port: int,
        task: str = "auto",
        max_model_len: int | None = None,
        max_num_seqs: int | None = None,
        gpu_memory_utilization: float | None = None,
        quantization: str | None = None,
        tensor_parallel_size: int = 1,
        dtype: str = "auto",
        chat_template_file: str | None = None,
        kv_cache_dtype: str = "auto",
        api_key: str = "sk-aria",
        served_model_name: str | None = None,
        tool_call_parser: str | None = None,
        reasoning_parser: str | None = None,
        chat_template_kwargs: str | None = None,
        vision_enabled: bool = False,
        enforce_eager: bool = True,
        data_parallel_size: int = 1,
        expert_parallel: bool = False,
        moe_backend: str = "",
        linear_backend: str = "",
        mm_encoder_tp_mode: str = "",
        mm_processor_cache_type: str = "",
        prefix_caching: bool = False,
        kv_offload_mode: str = "off",
        kv_offloading_size_gb: float | None = None,
        kv_offloading_backend: str = "native",
    ) -> list[str]:
        """Build command to launch a vLLM server.

        Args:
            model_path: HuggingFace model ID or local path.
            port: Port to run the server on.
            task: vLLM task type (``auto``, ``embed``, ``generate``).
            max_model_len: Maximum sequence length.
            gpu_memory_utilization: Fraction of GPU memory to use (0.0–1.0).
            quantization: Quantization method (e.g. ``gptq``, ``awq``).
            tensor_parallel_size: Number of GPUs for tensor parallelism.
            dtype: Data type (``auto``, ``float16``, ``bfloat16``).
            chat_template_file: Optional Jinja2 chat template file path.
            chat_template_kwargs: JSON string of kwargs for the chat template
                (e.g. ``'{"enable_thinking": true}'``).
            vision_enabled: Enable multi-modal (vision) support. When
                disabled (default), skips the multi-modal warmup to save
                ~6s startup time.
            data_parallel_size: Number of data-parallel replicas.
            expert_parallel: Enable expert parallelism for MoE models.
            mm_encoder_tp_mode: Multi-modal encoder tensor parallelism mode
                (e.g. ``data``).
            mm_processor_cache_type: Multi-modal processor cache type
                (e.g. ``shm`` for shared memory).
            prefix_caching: Enable automatic prefix caching for faster
                inference with shared prompt prefixes.
            kv_offload_mode: KV cache offload strategy (``off``, ``auto``,
                ``ram``).  Default ``off``.
            kv_offloading_size_gb: KV cache offload buffer size in GiB.
                When None and mode is ``auto``/``ram``, calculated at
                launch time.
            kv_offloading_backend: Backend for KV cache offloading
                (``native``, ``lmcache``).  Default ``native``.
        Returns:
            List of command arguments.
        """
        from aria.config.api import Vllm as VllmConfig

        cmd = [
            str(VllmConfig.get_python_executable()),
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--model",
            model_path,
            "--port",
            str(port),
            "--host",
            self._host,
        ]

        effective_quant, effective_dtype = _resolve_quant_and_dtype(quantization, dtype)
        offloading_active = _kv_offloading_active(
            kv_offload_mode, kv_offloading_size_gb
        )

        # ``--runner`` (embed task) and ``--convert`` (non-auto, non-embed
        # task) are mutually exclusive — keep the conditions as written so
        # at most one fires.
        flags: list[tuple[str, object, bool]] = [
            ("--runner", ["pooling", "--convert", "embed"], task == "embed"),
            (
                "--convert",
                task,
                bool(task) and task != "auto" and task != "embed",
            ),
            ("--max-model-len", max_model_len, bool(max_model_len)),
            ("--max-num-seqs", max_num_seqs, bool(max_num_seqs)),
            (
                "--gpu-memory-utilization",
                gpu_memory_utilization,
                gpu_memory_utilization is not None,
            ),
            ("--quantization", effective_quant, effective_quant is not None),
            ("--dtype", effective_dtype, True),
            (
                "--tensor-parallel-size",
                tensor_parallel_size,
                tensor_parallel_size > 1,
            ),
            (
                "--chat-template",
                chat_template_file,
                bool(chat_template_file) and task != "embed",
            ),
            ("--served-model-name", served_model_name, bool(served_model_name)),
            ("--enable-auto-tool-choice", None, bool(tool_call_parser)),
            ("--tool-call-parser", tool_call_parser, bool(tool_call_parser)),
            ("--reasoning-parser", reasoning_parser, bool(reasoning_parser)),
            (
                "--default-chat-template-kwargs",
                chat_template_kwargs,
                bool(chat_template_kwargs),
            ),
            ("--data-parallel-size", data_parallel_size, data_parallel_size > 1),
            ("--enable-expert-parallel", None, expert_parallel),
            ("--moe-backend", moe_backend, bool(moe_backend)),
            ("--linear-backend", linear_backend, bool(linear_backend)),
            ("--mm-encoder-tp-mode", mm_encoder_tp_mode, bool(mm_encoder_tp_mode)),
            (
                "--mm-processor-cache-type",
                mm_processor_cache_type,
                bool(mm_processor_cache_type),
            ),
            ("--enable-prefix-caching", None, prefix_caching),
            ("--limit-mm-per-prompt", '{"image": 0}', not vision_enabled),
            ("--trust-remote-code", None, True),
            ("--api-key", api_key, True),
            ("--enforce-eager", None, enforce_eager),
        ]
        _apply_flags(cmd, flags)

        # Prefix caching sets block_size to the Mamba page size (e.g. 2096);
        # vLLM requires block_size <= max_num_batched_tokens (default 2048).
        if prefix_caching:
            cmd.extend(["--max-num-batched-tokens", "4096"])

        cmd.extend(
            _resolve_kv_cache_flags(
                kv_cache_dtype, offloading_active, kv_offloading_backend, vision_enabled
            )
        )
        cmd.extend(
            _kv_offload_flags(
                kv_offload_mode,
                kv_offloading_size_gb,
                kv_offloading_backend,
                offloading_active,
            )
        )
        return cmd

    def _wait_for_ready(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        proc: subprocess.Popen | None = None,
    ) -> bool:
        """Poll ``/health`` until the server returns HTTP 200 or timeout.

        Also checks if the process is still alive — if it exits before
        becoming healthy, returns False immediately.

        Args:
            host: Server host.
            port: Server port.
            timeout: Maximum seconds to wait (default: ``HEALTH_TIMEOUT``).
            proc: Optional subprocess to check for early exit.

        Returns:
            True if the server became ready, False if timed out or crashed.
        """
        if timeout is None:
            timeout = self.HEALTH_TIMEOUT

        url = f"http://{host}:{port}/health"
        deadline = time.time() + timeout

        while time.time() < deadline:
            # Check if process crashed
            if proc is not None and proc.poll() is not None:
                return False

            try:
                with urlopen(url, timeout=2) as resp:
                    if resp.status == 200:
                        return True
            except (URLError, OSError):
                pass
            time.sleep(self.HEALTH_POLL_INTERVAL)

        return False

    def start_all(self, force_restart: bool = False) -> None:
        """Start the chat vLLM server process.

        Args:
            force_restart: If True, stop any running vLLM servers before
                starting fresh. Useful for reloading with new config.

        Raises:
            RuntimeError: If the server fails to start or become ready.
        """
        if force_restart and self._pids:
            logger.info("Force restart requested — stopping existing vLLM servers")
            self.stop_all()
        from aria.config.api import Vllm as VllmConfig
        from aria.config.models import Chat
        from aria.scripts.vllm import is_vllm_installed

        if not VllmConfig.remote and not is_vllm_installed():
            raise RuntimeError("vLLM is not installed. Run: aria vllm install")

        # Preflight runs before any GPU-memory/context-size computation so a
        # surviving orphan (holding VRAM + the port) doesn't silently produce
        # a tiny context clamp or an Address-already-in-use error.
        if not VllmConfig.remote:
            self._preflight_port_check(Chat.get_port())

        if not Chat.model_path:
            raise RuntimeError(
                "Chat model path is not configured. "
                "Set CHAT_MODEL_PATH in your .env file."
            )

        chat_cmd = self._prepare_chat_cmd()
        servers: list[tuple[str, list[str], int]] = [
            ("chat", chat_cmd, Chat.get_port())
        ]

        procs, log_files = self._launch_servers(servers)
        self._save_pids()
        self._await_ready(servers, procs, log_files)
        logger.info("All vLLM server instances are ready.")

    def _prepare_chat_cmd(self) -> list[str]:
        """Resolve hardware/context/KV-offload values and build the chat cmd."""
        from aria.config.api import Vllm as VllmConfig
        from aria.config.models import Chat

        # Clamp max_model_len to the model's actual maximum BEFORE gpu_mem
        # calculation so the KV cache estimate uses the real context size.
        max_model_len = self._resolve_max_model_len(
            Chat.model_path, VllmConfig.chat_context_size
        )

        backend = VllmConfig.kv_offloading_backend
        if not isinstance(backend, str) or not backend:
            backend = "native"
        if VllmConfig.kv_offload_mode in (
            "auto",
            "ram",
        ) and not self._kv_offloading_backend_available(backend):
            raise RuntimeError(
                "KV cache offloading backend "
                f"'{backend}' is not available. "
                "Install the required package or set "
                "ARIA_VLLM_KV_OFFLOADING_BACKEND=native."
            )

        gpu_mem = self._resolve_gpu_mem(max_model_len)

        # Clamp max_model_len to GPU KV cache capacity. vLLM requires the GPU
        # KV cache to hold at least one request at max_model_len; RAM offload
        # helps concurrency but cannot extend the per-request maximum.
        max_model_len = self._clamp_context_to_gpu_kv(
            model_path=Chat.model_path,
            requested_context=max_model_len,
            gpu_memory_utilization=gpu_mem,
            kv_cache_dtype=VllmConfig.kv_cache_dtype,
            tensor_parallel_size=VllmConfig.tensor_parallel_size,
            enforce_eager=VllmConfig.enforce_eager,
        )

        kv_offload_size = self._resolve_kv_offload_size(max_model_len)

        return self._build_vllm_cmd(
            model_path=Chat.model_path,
            port=Chat.get_port(),
            max_model_len=max_model_len,
            max_num_seqs=VllmConfig.max_num_seqs,
            gpu_memory_utilization=gpu_mem,
            quantization=VllmConfig.quantization,
            tensor_parallel_size=VllmConfig.tensor_parallel_size,
            dtype=VllmConfig.dtype,
            chat_template_file=(
                str(VllmConfig.chat_template_file)
                if VllmConfig.chat_template_file
                else None
            ),
            kv_cache_dtype=VllmConfig.kv_cache_dtype,
            api_key=VllmConfig.api_key,
            served_model_name=Chat.model,
            tool_call_parser=VllmConfig.tool_call_parser,
            reasoning_parser=VllmConfig.reasoning_parser,
            chat_template_kwargs=VllmConfig.chat_template_kwargs or None,
            vision_enabled=VllmConfig.vision_enabled,
            data_parallel_size=VllmConfig.data_parallel_size,
            expert_parallel=VllmConfig.expert_parallel,
            moe_backend=VllmConfig.moe_backend,
            linear_backend=VllmConfig.linear_backend,
            mm_encoder_tp_mode=VllmConfig.mm_encoder_tp_mode,
            mm_processor_cache_type=VllmConfig.mm_processor_cache_type,
            prefix_caching=VllmConfig.prefix_caching,
            kv_offload_mode=VllmConfig.kv_offload_mode,
            kv_offloading_size_gb=kv_offload_size,
            kv_offloading_backend=backend,
            enforce_eager=VllmConfig.enforce_eager,
        )

    def _resolve_gpu_mem(self, max_model_len: int) -> float:
        """Return the explicit gpu_memory_utilization, or auto-calculate it."""
        from aria.config.api import Vllm as VllmConfig
        from aria.config.models import Chat

        gpu_mem = VllmConfig.gpu_memory_utilization
        if gpu_mem is not None:
            return gpu_mem

        total_vram = get_per_gpu_vram_mb()
        free_vram_list = get_free_vram_per_gpu()
        # Use the most-constrained GPU's free VRAM (relevant for TP)
        free_vram = min(free_vram_list) if free_vram_list else 0
        return calculate_gpu_memory_utilization(
            total_vram_mb=total_vram,
            model_path=Chat.model_path,
            context_size=max_model_len,
            kv_cache_dtype=VllmConfig.kv_cache_dtype,
            free_vram_mb=free_vram,
            tensor_parallel_size=VllmConfig.tensor_parallel_size,
            enforce_eager=VllmConfig.enforce_eager,
        )

    def _resolve_kv_offload_size(self, max_model_len: int) -> float | None:
        """Resolve KV offload size: explicit > auto-calculated > None."""
        from aria.config.api import Vllm as VllmConfig
        from aria.config.models import Chat

        kv_offload_size = VllmConfig.kv_offloading_size_gb
        if (
            VllmConfig.kv_offload_mode not in ("auto", "ram")
            or kv_offload_size is not None
        ):
            return kv_offload_size

        kv_mb = _estimate_kv_cache_mb(
            Chat.model_path, max_model_len, VllmConfig.kv_cache_dtype
        )
        if kv_mb is None or kv_mb <= 0:
            return None
        size = math.ceil(kv_mb / 1024)  # MiB → GiB
        logger.info(
            "Auto-calculated KV offload size: {size} GiB "
            "(estimated KV cache: {kv_mb} MiB)",
            size=size,
            kv_mb=kv_mb,
        )
        return size

    def _launch_servers(
        self, servers: list[tuple[str, list[str], int]]
    ) -> tuple[dict[str, subprocess.Popen], dict[str, Path]]:
        """Spawn each server process, returning procs and log-file paths."""
        from aria.config.api import Vllm as VllmConfig
        from aria.config.folders import Debug as DebugConfig
        from aria.config.folders import get_augmented_env

        DebugConfig.path.mkdir(parents=True, exist_ok=True)
        procs: dict[str, subprocess.Popen] = {}
        log_files: dict[str, Path] = {}
        for role, cmd, port in servers:
            log_file = DebugConfig.logs_path.parent / "vllm.log"
            log_files[role] = log_file
            logger.info(f"Starting {role} server on port {port}: {' '.join(cmd)}")
            logger.info(f"  stderr → {log_file}")

            log_fh = open(log_file, "w")
            env = get_augmented_env()
            # Prepend the vLLM venv bin dir so JIT build tools (ninja, cc, …)
            # are discoverable by worker subprocesses spawned during
            # profiling/warmup. flashinfer's sampling kernel and Triton both
            # shell out to these tools at runtime.
            vllm_bin = VllmConfig.get_venv_path() / "bin"
            if vllm_bin.is_dir():
                env["PATH"] = f"{vllm_bin}{os.pathsep}{env['PATH']}"

            proc = subprocess.Popen(
                cmd,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
            )
            log_fh.close()
            self._pids[role] = proc.pid
            procs[role] = proc

            # If the process exits immediately it failed validation.
            time.sleep(3)
            if proc.poll() is not None:
                stderr_output = (
                    log_file.read_text().strip()[-2000:] if log_file.exists() else ""
                )
                raise RuntimeError(
                    f"vLLM server for '{role}' exited immediately "
                    f"(exit code {proc.returncode}). "
                    f"Log: {log_file}\n"
                    f"stderr: {stderr_output or '(none)'}"
                )
        return procs, log_files

    def _await_ready(
        self,
        servers: list[tuple[str, list[str], int]],
        procs: dict[str, subprocess.Popen],
        log_files: dict[str, Path],
    ) -> None:
        """Wait for every server to become ready; stop_all and raise on failure."""
        failed: list[str] = []
        for role, _, port in servers:
            logger.info(f"Waiting for {role} server on port {port}...")
            if self._wait_for_ready(self._host, port, proc=procs.get(role)):
                continue
            failed.append(role)
            log_tail = ""
            lf = log_files.get(role)
            if lf and lf.exists():
                log_tail = lf.read_text().strip()[-2000:]
            logger.error(
                f"{role} server failed to become ready on port {port}. "
                f"Log: {lf}\n"
                f"Last output: {log_tail or '(empty)'}"
            )

        if failed:
            self.stop_all()
            raise RuntimeError(
                f"The following servers failed to start: {', '.join(failed)}. "
                f"Check logs: {', '.join(str(log_files[f]) for f in failed)}"
            )

    def _stop_tracked_pids(self, timeout: float) -> tuple[set[int], dict[str, int]]:
        killed: set[int] = set()
        survivors: dict[str, int] = {}
        for role, pid in list(self._pids.items()):
            if not is_process_running(pid):
                continue
            logger.info(f"Stopping {role} server (PID/PGID {pid})...")
            stopped = stop_process_group(pid, timeout)
            if not stopped and is_process_running(pid):
                logger.warning(
                    f"{role} server (PID {pid}) did not stop — PID preserved for retry"
                )
                survivors[role] = pid
            else:
                killed.add(pid)
        return killed, survivors

    def _stop_orphans(
        self, orphans: list[int], killed: set[int], timeout: float
    ) -> tuple[set[int], dict[str, int]]:
        new_survivors: dict[str, int] = {}
        for pid in orphans:
            if pid in killed or not is_process_running(pid):
                continue
            stopped = stop_process_group(pid, timeout)
            if stopped or not is_process_running(pid):
                killed.add(pid)
            else:
                new_survivors[f"orphan-{pid}"] = pid
        return killed, new_survivors

    def stop_all(self, timeout: float = 10.0, skip_vllm: bool = False) -> None:
        """Stop all running vLLM server processes.

        Sends SIGTERM to the process group, waits for graceful shutdown,
        then SIGKILL if needed. Falls back to scanning for orphaned vLLM
        processes when the PID file is stale or empty.

        Args:
            timeout: Maximum seconds to wait for graceful shutdown per process.
            skip_vllm: If True, clear PID tracking without killing the
                vLLM processes. The processes will keep running as orphans.
                Useful for rapid web UI restarts without model reload.
        """
        if skip_vllm:
            logger.info("Skipping vLLM shutdown — processes will keep running")
            self._clear_pids()
            return

        killed_pids, survivors = self._stop_tracked_pids(timeout)

        # Phase 2: Scan for orphaned vLLM processes not in the PID file
        orphans = self._find_orphan_pids()
        orphan_leaders = [p for p in orphans if p not in killed_pids]
        if orphan_leaders:
            logger.info(
                f"Found {len(orphan_leaders)} orphaned vLLM process "
                f"group(s): {orphan_leaders}"
            )
            killed_pids, orphan_survivors = self._stop_orphans(
                orphan_leaders, killed_pids, timeout
            )
            survivors.update(orphan_survivors)

        if survivors:
            self._pids = survivors
            self._save_pids()
            logger.warning(f"Some vLLM processes survived shutdown: {survivors}")
        else:
            self._clear_pids()
            logger.info("All vLLM server instances stopped.")
