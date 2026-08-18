"""Hardware preflight checks: platform, memory, and KV cache budget."""

from dataclasses import dataclass

from aria.preflight.checks_models import _format_context_size
from aria.preflight.results import CheckResult


def _detect_compute_platform() -> str:
    """Detect the compute platform: nvidia, metal, or cpu.

    Priority: NVIDIA > Metal > CPU.
    """
    import platform

    try:
        from aria.helpers.nvidia import get_total_vram_mb

        if get_total_vram_mb() > 0:
            return "nvidia"
    except Exception:
        pass

    if platform.system() == "Darwin":
        import subprocess

        try:
            arch = subprocess.check_output(
                ["uname", "-m"], stderr=subprocess.DEVNULL
            ).decode()
            if arch.strip() == "arm64":
                return "metal"
        except Exception:
            pass

    return "cpu"


def _check_memory_requirements(checks: list[CheckResult]) -> None:
    """Check if models fit in available GPU VRAM and RAM.

    Platform-aware:
        - NVIDIA: Check VRAM and RAM separately
        - Metal: Use unified memory (system RAM)
        - CPU: Only check system RAM

    In remote mode, GPU checks are skipped — the remote server
    manages its own hardware.
    """
    from aria.config.api import Vllm as VllmConfig

    if VllmConfig.remote:
        checks.append(
            CheckResult(
                name="Hardware",
                passed=True,
                category="hardware",
                details="Remote mode — hardware managed by remote server",
            )
        )
        return

    from aria.helpers.memory import detect_system_ram
    from aria.helpers.nvidia import get_free_vram_per_gpu, get_total_vram_mb

    def _mb_to_gb(mb: int) -> str:
        return f"{mb // 1024} GB"

    platform_type = _detect_compute_platform()

    total_ram_mb, avail_ram_mb = detect_system_ram()
    if total_ram_mb > 0:
        checks.append(
            CheckResult(
                name="System RAM",
                passed=True,
                category="hardware",
                details=f"{_mb_to_gb(total_ram_mb)} total, {_mb_to_gb(avail_ram_mb)} available",
            )
        )

    if platform_type == "nvidia":
        total_vram = get_total_vram_mb()
        free_vram = get_free_vram_per_gpu()
        if total_vram > 0:
            total_free = sum(free_vram) if free_vram else total_vram
            checks.append(
                CheckResult(
                    name="GPU VRAM",
                    passed=True,
                    category="hardware",
                    details=f"{_mb_to_gb(total_free)} available (NVIDIA)",
                )
            )
    elif platform_type == "metal":
        if total_ram_mb > 0:
            checks.append(
                CheckResult(
                    name="Unified Memory",
                    passed=True,
                    category="hardware",
                    details=(f"{_mb_to_gb(total_ram_mb)} (Apple Silicon Metal)"),
                )
            )
    else:
        checks.append(
            CheckResult(
                name="Compute Platform",
                passed=True,
                category="hardware",
                details="CPU-only mode (no GPU acceleration)",
            )
        )

    from aria.config.models import Chat

    if Chat.model_path:
        from pathlib import Path

        from aria.helpers.memory import get_model_file_size as _get_model_size

        model_size_mb = _get_model_size(Path(Chat.model_path))
        if model_size_mb > 0:
            model_size_gb = model_size_mb / 1024
            checks.append(
                CheckResult(
                    name="Model weights",
                    passed=True,
                    category="hardware",
                    details=f"{model_size_gb:.1f} GB on disk ({Chat.model_path})",
                )
            )


def _check_kv_cache_memory(checks: list[CheckResult]) -> None:
    """Check if KV cache fits in VRAM or can be offloaded to RAM.

    When VRAM is insufficient for the full KV cache:
    - ``off`` mode: warn (informational only).
    - ``auto``/``ram`` mode: check if system RAM is sufficient.
      - RAM sufficient → pass with offload detail.
      - RAM insufficient → fail with clear remediation.

    Skipped entirely in remote mode.
    """
    from aria.config.api import Vllm as VllmConfig
    from aria.config.models import Chat
    from aria.server.vllm import VllmServerManager

    if VllmConfig.remote:
        return  # KV cache managed by remote server

    if not Chat.model_path:
        return  # Model not configured — other checks handle this

    budget = _kv_cache_budget()
    if budget is None:
        return

    if budget.skip_estimate:
        checks.append(
            CheckResult(
                name="KV cache memory",
                passed=True,
                category="hardware",
                details="Could not estimate (no config.json) — will use heuristic at launch",
            )
        )
        return

    if budget.vram_sufficient:
        checks.append(_vram_pass_result(budget))
        return

    backend = _resolve_kv_backend()
    mode = VllmConfig.kv_offload_mode

    if mode in (
        "auto",
        "ram",
    ) and not VllmServerManager._kv_offloading_backend_available(backend):
        checks.append(_kv_backend_missing_result(backend))
        return

    if mode == "off":
        checks.append(_vram_warn_result(budget))
        return

    checks.append(_kv_offload_result(budget))


@dataclass
class _KVBudget:
    skip_estimate: bool
    model_gb: float
    kv_gb: float
    overhead_gb: float
    needed_gb: float
    free_gb: float
    kv_cache_gb: float
    ctx_label: str
    dtype_label: str
    max_free_vram_mb: int
    avail_ram_mb: int
    ram_needed_mb: int
    clamped_context: int
    effective_context_size: int
    will_be_clamped: bool
    ram_sufficient: bool
    vram_sufficient: bool


def _kv_cache_budget() -> _KVBudget:
    from pathlib import Path

    from aria.config.api import Vllm as VllmConfig
    from aria.config.models import Chat
    from aria.helpers.memory import detect_system_ram, get_model_file_size
    from aria.helpers.nvidia import (
        _estimate_kv_cache_mb,
        estimate_per_gpu_memory_mb,
        get_free_vram_per_gpu,
        get_per_gpu_vram_mb,
    )
    from aria.server.vllm import VllmServerManager

    effective_context_size = VllmServerManager._resolve_max_model_len(
        Chat.model_path, VllmConfig.chat_context_size
    )

    kv_cache_mb = _estimate_kv_cache_mb(
        Chat.model_path,
        effective_context_size,
        VllmConfig.kv_cache_dtype,
    )
    if kv_cache_mb is None:
        return _KVBudget(
            skip_estimate=True,
            model_gb=0.0,
            kv_gb=0.0,
            overhead_gb=0.0,
            needed_gb=0.0,
            free_gb=0.0,
            kv_cache_gb=0.0,
            ctx_label="",
            dtype_label="",
            max_free_vram_mb=0,
            avail_ram_mb=0,
            ram_needed_mb=0,
            clamped_context=0,
            effective_context_size=0,
            will_be_clamped=False,
            ram_sufficient=False,
            vram_sufficient=False,
        )

    kv_cache_gb = kv_cache_mb / 1024
    model_size_mb = get_model_file_size(Path(Chat.model_path))
    per_gpu_vram_mb = get_per_gpu_vram_mb()
    free_vram_list = get_free_vram_per_gpu()
    max_free_vram_mb = min(free_vram_list) if free_vram_list else per_gpu_vram_mb
    overhead_mb = 1536
    tp = max(1, VllmConfig.tensor_parallel_size)

    per_gpu_model_mb, per_gpu_kv_mb, vram_needed_mb = estimate_per_gpu_memory_mb(
        model_weights_mb=model_size_mb,
        kv_cache_mb=kv_cache_mb,
        tensor_parallel_size=tp,
        overhead_mb=overhead_mb,
    )
    _, avail_ram_mb = detect_system_ram()

    gpu_mem = VllmConfig.gpu_memory_utilization
    if gpu_mem is None:
        gpu_mem = 0.90
    clamped_context = VllmServerManager._clamp_context_to_gpu_kv(
        model_path=Chat.model_path,
        requested_context=effective_context_size,
        gpu_memory_utilization=gpu_mem,
        kv_cache_dtype=VllmConfig.kv_cache_dtype,
        tensor_parallel_size=VllmConfig.tensor_parallel_size,
    )

    ram_headroom_mb = 2048
    ram_needed_mb = kv_cache_mb + ram_headroom_mb

    dtype_label = (
        VllmConfig.kv_cache_dtype if VllmConfig.kv_cache_dtype != "auto" else "fp16"
    )
    return _KVBudget(
        skip_estimate=False,
        model_gb=per_gpu_model_mb / 1024,
        kv_gb=per_gpu_kv_mb / 1024,
        overhead_gb=overhead_mb / 1024,
        needed_gb=vram_needed_mb / 1024,
        free_gb=max_free_vram_mb / 1024,
        kv_cache_gb=kv_cache_gb,
        ctx_label=_format_context_size(effective_context_size),
        dtype_label=dtype_label,
        max_free_vram_mb=max_free_vram_mb,
        avail_ram_mb=avail_ram_mb,
        ram_needed_mb=ram_needed_mb,
        clamped_context=clamped_context,
        effective_context_size=effective_context_size,
        will_be_clamped=clamped_context < effective_context_size,
        ram_sufficient=avail_ram_mb >= ram_needed_mb,
        vram_sufficient=max_free_vram_mb >= vram_needed_mb,
    )


def _resolve_kv_backend() -> str:
    from aria.config.api import Vllm as VllmConfig

    backend = getattr(VllmConfig, "kv_offloading_backend", "native")
    if not isinstance(backend, str) or not backend:
        backend = "native"
    return backend


def _vram_pass_result(b: _KVBudget) -> CheckResult:
    return CheckResult(
        name="VRAM budget",
        passed=True,
        category="hardware",
        details=(
            f"model {b.model_gb:.1f} GB + KV {b.kv_gb:.1f} GB "
            f"({b.ctx_label} ctx, {b.dtype_label}) + "
            f"overhead {b.overhead_gb:.1f} GB = "
            f"{b.needed_gb:.1f} GB needed / {b.free_gb:.1f} GB free"
        ),
    )


def _vram_warn_result(b: _KVBudget) -> CheckResult:
    return CheckResult(
        name="VRAM budget",
        passed=True,  # Warning only in 'off' mode
        category="hardware",
        details=(
            f"model {b.model_gb:.1f} GB + KV {b.kv_gb:.1f} GB "
            f"({b.ctx_label} ctx, {b.dtype_label}) + "
            f"overhead {b.overhead_gb:.1f} GB = "
            f"{b.needed_gb:.1f} GB needed > {b.free_gb:.1f} GB free. "
            f"Consider ARIA_VLLM_KV_OFFLOAD_MODE=auto"
        ),
    )


def _kv_backend_missing_result(backend: str) -> CheckResult:
    return CheckResult(
        name="KV cache offloading backend",
        passed=False,
        category="hardware",
        error=f"KV cache offloading backend '{backend}' is not available.",
        hint=(
            "Install the backend dependency or set "
            "ARIA_VLLM_KV_OFFLOADING_BACKEND=native in .env"
        ),
    )


def _kv_offload_pass(b: _KVBudget, clamped_detail: str) -> CheckResult:
    return CheckResult(
        name="KV cache memory",
        passed=True,
        category="hardware",
        details=clamped_detail,
    )


def _kv_offload_result(b: _KVBudget) -> CheckResult:
    if b.ram_sufficient and not b.will_be_clamped:
        return _kv_offload_pass(
            b,
            (
                f"KV cache offloaded to RAM ({b.kv_cache_gb:.1f} GiB). "
                f"Available RAM: {b.avail_ram_mb // 1024} GB. "
                f"Latency may increase vs GPU-only."
            ),
        )
    if b.ram_sufficient and b.will_be_clamped:
        req_k = _format_context_size(b.effective_context_size)
        clamped_k = _format_context_size(b.clamped_context)
        return _kv_offload_pass(
            b,
            (
                f"Context {req_k} → ~{clamped_k} "
                f"(GPU KV cache limit). "
                f"RAM offload active for concurrency."
            ),
        )
    return CheckResult(
        name="KV cache memory",
        passed=False,
        category="hardware",
        error=(
            f"KV cache needs {b.kv_cache_gb:.1f} GiB but only "
            f"{b.avail_ram_mb // 1024} GB RAM available "
            f"(need {b.ram_needed_mb // 1024} GB with headroom). "
            f"Fits neither in VRAM ({b.max_free_vram_mb} MiB "
            f"free) nor RAM."
        ),
        hint=(
            f"Reduce CHAT_CONTEXT_SIZE in .env (currently "
            f"{b.effective_context_size}), or add more "
            f"system RAM, or use fp8 KV cache "
            f"(ARIA_VLLM_KV_CACHE_DTYPE=fp8)"
        ),
    )
