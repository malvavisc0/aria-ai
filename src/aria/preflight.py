"""Preflight checks for the Aria web UI.

Verifies that all required dependencies are in place before starting
the Chainlit web server:
  - Required environment variables are set
  - Data folder exists
  - vLLM is installed (Python package)
  - All required models are configured (chat, embeddings)
  - Model paths exist (local dirs or HF snapshots)

Example:
    ```python
    from aria.preflight import run_preflight_checks

    result = run_preflight_checks()
    if not result.passed:
        for failure in result.failures:
            print(f"Missing: {failure.error}")
            print(f"Fix: {failure.hint}")
    ```
"""

import os
from dataclasses import dataclass, field


@dataclass
class CheckResult:
    """Result of a single preflight check.

    Attributes:
        name: Short name of the check (e.g. "vLLM package").
        passed: True if the check passed, False otherwise.
        category: Group for display (environment, storage, binaries, models, hardware).
        error: Human-readable description of what is missing (if failed).
        hint: Remediation command or instruction for the user (if failed).
        details: Optional extra info to display on success (e.g. "24 GB available").
    """

    name: str
    passed: bool
    category: str = "general"
    error: str = ""
    hint: str = ""
    details: str = ""


@dataclass
class PreflightResult:
    """Result of running all preflight checks.

    Attributes:
        passed: True if all checks passed, False if any failed.
        checks: List of all CheckResult instances.
        failures: List of failed CheckResult instances.
    """

    passed: bool
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def failures(self) -> list[CheckResult]:
        """Return only the failed checks."""
        return [c for c in self.checks if not c.passed]

    def group_by_category(self) -> dict[str, list[CheckResult]]:
        """Group checks by category for display.

        Returns:
            Dict mapping category names to lists of checks.
        """
        grouped: dict[str, list[CheckResult]] = {}
        for check in self.checks:
            if check.category not in grouped:
                grouped[check.category] = []
            grouped[check.category].append(check)
        return grouped


# Required environment variables for the application to start
REQUIRED_ENV_VARS = [
    "ARIA_DB_FILENAME",
    "CHROMADB_PERSISTENT_PATH",
    "CHAT_MODEL",
    "CHAT_MODEL_PATH",
    "EMBED_MODEL_PATH",
    "CHAT_OPENAI_API",
    "MAX_ITERATIONS",
    "TOKEN_LIMIT_RATIO",
    "EMBEDDINGS_MODEL",
    "CHAINLIT_AUTH_SECRET",
]


def _check_env_vars(checks: list[CheckResult]) -> None:
    """Check that all required environment variables are set."""
    from aria.config.api import Vllm as VllmConfig

    required = list(REQUIRED_ENV_VARS)
    if VllmConfig.remote:
        # CHAT_MODEL_PATH is not required in remote mode —
        # the model is served by the remote endpoint.
        required = [v for v in required if v != "CHAT_MODEL_PATH"]

    passed = sum(1 for var in required if os.getenv(var))
    total = len(required)

    if passed == total:
        checks.append(
            CheckResult(
                name="Environment variables",
                passed=True,
                category="environment",
                details=f"All {total} variables configured",
            )
        )
    else:
        for var in REQUIRED_ENV_VARS:
            if os.getenv(var):
                continue
            checks.append(
                CheckResult(
                    name=f"env:{var}",
                    passed=False,
                    category="environment",
                    error=f"'{var}' is not set",
                    hint=f"Add '{var}' to your .env file",
                )
            )


def _check_data_folder(checks: list[CheckResult]) -> None:
    """Check that the data folder exists."""
    from aria.config.folders import Data

    data_path = Data.path
    if data_path.exists():
        checks.append(
            CheckResult(
                name="Data folder",
                passed=True,
                category="storage",
                details=f"exists at {data_path}",
            )
        )
    else:
        checks.append(
            CheckResult(
                name="Data folder",
                passed=False,
                category="storage",
                error=f"does not exist: {data_path}",
                hint=f"Create the directory: mkdir -p {data_path}",
            )
        )


def _check_binaries(checks: list[CheckResult]) -> None:
    """Check that vLLM is installed (skipped in remote mode)."""
    from aria.config.api import Vllm as VllmConfig

    if VllmConfig.remote:
        checks.append(
            CheckResult(
                name="vLLM",
                passed=True,
                category="binaries",
                details="Remote mode — local install not required",
            )
        )
        return

    from aria.scripts.vllm import get_vllm_version, is_vllm_installed

    if is_vllm_installed():
        version = get_vllm_version()
        checks.append(
            CheckResult(
                name="vLLM",
                passed=True,
                category="binaries",
                details=f"v{version}",
            )
        )
    else:
        checks.append(
            CheckResult(
                name="vLLM",
                passed=False,
                category="binaries",
                error="vLLM is not installed",
                hint="Run: aria vllm install",
            )
        )


def _check_lightpanda(checks: list[CheckResult]) -> None:
    """Check that Lightpanda is installed."""
    from aria.config.api import Lightpanda

    if Lightpanda.is_available():
        binary = Lightpanda.get_binary_path()
        checks.append(
            CheckResult(
                name="lightpanda",
                passed=True,
                category="binaries",
                details=f"Found at {binary}",
            )
        )
    else:
        checks.append(
            CheckResult(
                name="lightpanda",
                passed=False,
                category="binaries",
                error="Lightpanda is not installed",
                hint="Run: aria lightpanda download",
            )
        )


def _check_docling(checks: list[CheckResult]) -> None:
    """Report the docling worker state.

    The Granite-Docling worker is required: the documents tool and the
    knowledge hub both need it for PDF conversion. The hub's
    ``_pdf_chunks`` raises a skip with reason ``docling_not_installed``
    when PDFs are present and the worker is missing, so silent fallback
    cannot happen.
    """
    from pathlib import Path

    from aria.config.models import _resolve_model_path
    from aria.config.pdf import Pdf
    from aria.scripts.docling import detect_device, is_installed

    if not is_installed():
        checks.append(
            CheckResult(
                name="docling worker",
                passed=False,
                category="binaries",
                error="docling worker not installed",
                hint="Run: aria docling install",
            )
        )
        return

    device = Pdf.vlm_device
    if device == "auto":
        device = detect_device()

    model_path = Pdf.model_path or _resolve_model_path(Pdf.vlm_model_id)
    model_cached = bool(model_path) and Path(model_path).is_dir()
    state = f"installed (device={device}, model_cached={model_cached})"
    if not model_cached:
        state += " — model downloads on first PDF conversion"
    checks.append(
        CheckResult(
            name="docling worker",
            passed=True,
            category="binaries",
            details=state,
        )
    )


def _check_voice(checks: list[CheckResult]) -> None:
    """Check that voice components (whisper.cpp STT + kokoro TTS) are installed.

    Both are required: the voice pipeline degrades to STT-only if TTS is
    missing, but STT alone still depends on the whisper binary. A missing
    whisper binary or kokoro tool/model is a hard preflight failure.

    Skipped entirely when voice is disabled via ``ARIA_VOICE_ENABLED=false``.
    """
    from aria.config.api import Voice

    if not Voice.enabled:
        checks.append(
            CheckResult(
                name="voice",
                passed=True,
                category="binaries",
                details="Disabled via ARIA_VOICE_ENABLED=false",
            )
        )
        return

    # Informational: tell the user if their hardware supports the CUDA build.
    from aria.scripts.voice import _detect_whisper_target

    try:
        target = _detect_whisper_target()
        if target == "cuda":
            checks.append(
                CheckResult(
                    name="whisper.cpp GPU",
                    passed=True,
                    category="binaries",
                    details="NVIDIA GPU detected — CUDA build available",
                )
            )
    except RuntimeError:
        pass  # non-Linux; skip

    whisper = Voice.get_whisper_binary_path()
    if whisper is not None:
        checks.append(
            CheckResult(
                name="whisper.cpp (STT)",
                passed=True,
                category="binaries",
                details=f"Found at {whisper}",
            )
        )
    else:
        checks.append(
            CheckResult(
                name="whisper.cpp (STT)",
                passed=False,
                category="binaries",
                error="whisper.cpp binary not installed",
                hint="Run: aria voice download",
            )
        )

    if Voice.is_kokoro_available():
        checks.append(
            CheckResult(
                name="kokoro TTS",
                passed=True,
                category="binaries",
                details=f"Model at {Voice.get_kokoro_model_path()}",
            )
        )
    else:
        checks.append(
            CheckResult(
                name="kokoro TTS",
                passed=False,
                category="binaries",
                error="kokoro TTS model not installed",
                hint="Run: aria voice download",
            )
        )

    if Voice.get_kokoro_python() is None:
        checks.append(
            CheckResult(
                name="kokoro-tts tool",
                passed=False,
                category="binaries",
                error="kokoro-tts Python tool not installed",
                hint="Run: aria voice download",
            )
        )
    else:
        checks.append(
            CheckResult(
                name="kokoro-tts tool",
                passed=True,
                category="binaries",
                details="uv tool env ready",
            )
        )


def _check_model_exists(model_path: str) -> bool:
    """Check if a model directory exists under ~/.aria/models/.

    All models must reside under ~/.aria/models/. Only local
    directory existence is checked — HF cache is not used.

    Args:
        model_path: Resolved absolute path to the model directory.

    Returns:
        True if the model directory exists locally.
    """
    from pathlib import Path

    if not model_path:
        return False
    path = Path(model_path)
    return path.is_absolute() and path.exists() and path.is_dir()


def _check_models(checks: list[CheckResult]) -> None:
    """Check that all required models are configured and downloaded.

    In remote mode, only the embeddings model is checked locally —
    the chat model is served by the remote endpoint.
    """
    from aria.config.api import Vllm as VllmConfig
    from aria.config.models import Chat, Embeddings

    if VllmConfig.remote:
        model_checks = [
            ("embeddings", Embeddings.model_path, True),
        ]
    else:
        model_checks = [
            ("chat", Chat.model_path, True),  # required
            ("embeddings", Embeddings.model_path, True),  # required
        ]

    for alias, model_path, required in model_checks:
        display_name = f"{alias} model"
        if not model_path:
            if required:
                checks.append(
                    CheckResult(
                        name=display_name,
                        passed=False,
                        category="models",
                        error="not configured (env var not set)",
                        hint=(
                            "Set the corresponding env var in your .env file "
                            f"(e.g. {alias.upper()}_MODEL_PATH)"
                        ),
                    )
                )
            else:
                checks.append(
                    CheckResult(
                        name=display_name,
                        passed=True,
                        category="models",
                        details="not configured (optional)",
                    )
                )
            continue

        if _check_model_exists(model_path):
            checks.append(
                CheckResult(
                    name=display_name,
                    passed=True,
                    category="models",
                    details=model_path,
                )
            )
        else:
            checks.append(
                CheckResult(
                    name=display_name,
                    passed=False,
                    category="models",
                    error=f"not downloaded ({model_path})",
                    hint=f"Run: aria models download --model {alias}",
                )
            )


def _check_token_limit(checks: list[CheckResult]) -> None:
    """Check that TOKEN_LIMIT_RATIO is within safe bounds.

    The memory token limit (TOKEN_LIMIT_RATIO × effective_context) must
    leave room for system prompt, tool definitions, user input, and model
    response generation.

    Uses the **effective** context (after GPU KV cache clamping) rather
    than the raw requested CHAT_CONTEXT_SIZE, since the model will
    actually support the clamped value.
    """
    from aria.config.api import Vllm as VllmConfig
    from aria.config.models import Chat
    from aria.config.models import Embeddings as EmbeddingsConfig

    ratio = EmbeddingsConfig.token_limit_ratio
    requested_ctx = VllmConfig.chat_context_size

    # Compute effective context (same clamping as _check_kv_cache_memory)
    effective_ctx = requested_ctx
    ctx_was_clamped = False
    model_max_ctx = None
    if Chat.model_path:
        from aria.server.vllm import VllmServerManager

        model_max_ctx = VllmServerManager._get_model_max_context(Chat.model_path)
        effective_ctx = VllmServerManager._resolve_max_model_len(
            Chat.model_path, requested_ctx
        )
        gpu_mem = VllmConfig.gpu_memory_utilization
        if gpu_mem is None:
            gpu_mem = 0.90  # Conservative estimate for preflight
        clamped = VllmServerManager._clamp_context_to_gpu_kv(
            model_path=Chat.model_path,
            requested_context=effective_ctx,
            gpu_memory_utilization=gpu_mem,
            kv_cache_dtype=VllmConfig.kv_cache_dtype,
            tensor_parallel_size=VllmConfig.tensor_parallel_size,
        )
        if clamped < effective_ctx:
            effective_ctx = clamped
            ctx_was_clamped = True

    token_limit = int(effective_ctx * ratio)

    # Reserve 10% of context for system prompt, tools, and response
    max_safe_ratio = 0.90

    # Build context chain description
    ctx_parts = [f"effective {_format_context_size(effective_ctx)}"]
    if model_max_ctx is not None and model_max_ctx != effective_ctx:
        ctx_parts.append(f"model max {_format_context_size(model_max_ctx)}")
    if requested_ctx != effective_ctx:
        ctx_parts.append(f"configured {_format_context_size(requested_ctx)}")
    if ctx_was_clamped:
        ctx_parts.append("GPU KV clamped")
    ctx_detail = ", ".join(ctx_parts)

    if ratio > max_safe_ratio:
        checks.append(
            CheckResult(
                name="Token limit",
                passed=False,
                category="environment",
                error=(
                    f"TOKEN_LIMIT_RATIO ({ratio:.0%}) exceeds safe limit "
                    f"({max_safe_ratio:.0%}) of {effective_ctx:,} context. "
                    f"Max safe token limit: {int(effective_ctx * max_safe_ratio):,}"
                ),
                hint=(
                    "Reduce TOKEN_LIMIT_RATIO in your .env file to leave room "
                    "for system prompts and model responses"
                ),
            )
        )
    else:
        limit_k = _format_context_size(token_limit)
        ctx_k = _format_context_size(effective_ctx)
        checks.append(
            CheckResult(
                name="Token limit",
                passed=True,
                category="environment",
                details=(
                    f"{limit_k} for memory ({ratio:.0%} of {ctx_k} context)"
                    f" [{ctx_detail}]"
                ),
            )
        )


def run_preflight_checks() -> PreflightResult:
    """Run all preflight checks required before starting the web UI.

    Checks performed (all run before returning so every failure is reported):
        1. All required environment variables are set
        2. Data folder exists
        3. vLLM is installed
        4. Lightpanda is installed
        5. Docling worker is installed
        6. Voice components (whisper.cpp STT + kokoro TTS) are installed
           (skipped when ARIA_VOICE_ENABLED=false)
        7. Chat model is configured and downloaded
        8. Embeddings model is configured and downloaded
        9. Token limit is within context bounds
       10. Memory requirements fit available hardware
       11. LLM server connectivity (informational)
       12. Knowledge database access
       13. Tool loading

    Returns:
        PreflightResult with pass/fail status and all check details.
    """
    checks: list[CheckResult] = []

    _check_env_vars(checks)
    _check_data_folder(checks)
    _check_binaries(checks)
    _check_lightpanda(checks)
    _check_docling(checks)
    _check_voice(checks)
    _check_models(checks)
    _check_token_limit(checks)
    _check_memory_requirements(checks)
    _check_kv_cache_memory(checks)
    _check_llm_server(checks)
    _check_memory_db(checks)
    _check_tool_loading(checks)

    return PreflightResult(
        passed=all(c.passed for c in checks),
        checks=checks,
    )


def _detect_compute_platform() -> str:
    """Detect the compute platform: nvidia, metal, or cpu.

    Priority: NVIDIA > Metal > CPU.
    """
    import platform

    # Check for NVIDIA GPU
    try:
        from aria.helpers.nvidia import get_total_vram_mb

        if get_total_vram_mb() > 0:
            return "nvidia"
    except Exception:
        pass

    # Check for Apple Silicon (Metal)
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

    # Fallback to CPU
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

    # Detect platform
    platform_type = _detect_compute_platform()

    # Check system RAM (all platforms)
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

    # Platform-specific checks
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

    # Show model weight size so users understand VRAM requirements
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


def _format_context_size(tokens: int) -> str:
    """Format a token count using binary K/M units (e.g. 1048576 -> "1M").

    Uses 1024-based (KiB/MiB-style) division so that common power-of-two
    context sizes like 1048576 render as "1M" instead of the misleading
    "1048K" produced by decimal (// 1000) division.
    """
    if tokens % (1024 * 1024) == 0:
        return f"{tokens // (1024 * 1024)}M"
    if tokens % 1024 == 0:
        return f"{tokens // 1024}K"
    return str(tokens)


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


def _check_llm_server(checks: list[CheckResult]) -> None:
    """Check that the LLM server is reachable (non-blocking).

    The LLM server starts *after* preflight, so this check always passes.
    It reports connectivity status as details/warning for informational purposes.
    """
    try:
        import httpx

        from aria.config.api import Vllm as VllmConfig
        from aria.config.models import Chat as ChatConfig

        headers = {}
        if VllmConfig.remote and VllmConfig.api_key:
            headers["Authorization"] = f"Bearer {VllmConfig.api_key}"
        r = httpx.get(f"{ChatConfig.api_url}/models", timeout=3, headers=headers)
        models = r.json().get("data", [])
        checks.append(
            CheckResult(
                name="LLM server",
                passed=True,
                category="connectivity",
                details=(f"{ChatConfig.api_url} ({len(models)} model(s))"),
            )
        )
    except Exception:
        # Non-blocking: server starts after preflight
        checks.append(
            CheckResult(
                name="LLM server",
                passed=True,
                category="connectivity",
                details="Not running yet (will start with server)",
            )
        )


def _check_memory_db(checks: list[CheckResult]) -> None:
    """Check that the memory database is accessible."""
    try:
        from aria.tools.memory.database import MemoryDatabase

        MemoryDatabase()
        checks.append(
            CheckResult(
                name="Memory DB",
                passed=True,
                category="storage",
                details="SQLite accessible",
            )
        )
    except Exception as e:
        checks.append(
            CheckResult(
                name="Memory DB",
                passed=False,
                category="storage",
                error=str(e),
                hint="Check ARIA_HOME and ARIA_DB_FILENAME in .env",
            )
        )


def _check_tool_loading(checks: list[CheckResult]) -> None:
    """Check that core + file tools load correctly."""
    try:
        from aria.tools.registry import CORE, FILES, get_tools

        tools = get_tools([CORE, FILES])
        checks.append(
            CheckResult(
                name="Tool loading",
                passed=True,
                category="tools",
                details=f"{len(tools)} tools loaded",
            )
        )
    except Exception as e:
        checks.append(
            CheckResult(
                name="Tool loading",
                passed=False,
                category="tools",
                error=str(e),
                hint="Check tool dependencies are installed",
            )
        )
