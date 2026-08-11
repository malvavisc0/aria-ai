from pathlib import Path

from aria.config import get_optional_env
from aria.config.folders import Bin, Knowledge, Venvs


class Vllm:
    """Configuration for the vLLM inference engine.

    All settings are driven by environment variables with sensible defaults.
    Models are loaded directly from HuggingFace Hub (safetensors) — no GGUF
    files or llama.cpp binaries are required.

    ``gpu_memory_utilization`` defaults to ``None``, which triggers
    automatic calculation at server launch time based on detected VRAM,
    model weight size, and a 10 % headroom.  Set the
    ``ARIA_VLLM_GPU_MEMORY_UTILIZATION`` env var to a float (e.g.
    ``0.85``) to override the auto-calculation.
    """

    # --- Remote mode ---
    # When true, skip local vLLM process management and connect
    # directly to whatever CHAT_OPENAI_API points to.
    remote: bool = get_optional_env("ARIA_VLLM_REMOTE", "").lower() == "true"

    # --- Isolated venv pinning ---
    # Pinned vLLM release version (derived from the GitHub release tag,
    # e.g. ``v0.24.0`` → ``0.24.0``).  The prebuilt PyPI wheel is
    # installed into a separate venv at ``~/.aria/venvs/vllm`` so
    # Aria's own dependency tree stays clean.
    version: str = get_optional_env("ARIA_VLLM_VERSION", "0.26.0")

    @classmethod
    def get_venv_path(cls) -> Path:
        """Resolve the isolated vLLM venv directory.

        Honours the ``ARIA_VLLM_VENV`` override (e.g. pointing at a
        pre-existing system venv like ``/opt/vllm``) so a manually
        managed install can skip Aria's managed install path.
        """
        override = get_optional_env("ARIA_VLLM_VENV", "")
        if override:
            return Path(override).expanduser().resolve()
        return Venvs.vllm

    @classmethod
    def is_externally_managed_venv(cls) -> bool:
        """Whether the venv is user-provided via ``ARIA_VLLM_VENV``.

        When set, the venv belongs to the user (e.g. a pre-existing
        ``/opt/vllm``) and Aria must never create, recreate, or delete
        it.  Destructive managed operations (install/update/uninstall)
        refuse to touch an externally-managed venv to avoid data loss.
        """
        return bool(get_optional_env("ARIA_VLLM_VENV", ""))

    @classmethod
    def get_python_executable(cls) -> Path:
        """Return the interpreter inside the isolated vLLM venv.

        vLLM is Linux-only (macOS is guarded in the installer), so the
        interpreter always lives at ``<venv>/bin/python``.
        """
        return cls.get_venv_path() / "bin" / "python"

    @classmethod
    def get_site_packages(cls) -> Path | None:
        """Resolve the venv's ``site-packages`` directory, or None.

        The Python minor version under the venv is not known up-front,
        so this globs ``lib/python3.*/site-packages`` and returns the
        last match (highest installed minor version).
        """
        hits = sorted(cls.get_venv_path().glob("lib/python3.*/site-packages"))
        return hits[-1] if hits else None

    # --- vLLM engine settings ---
    # None = auto-calculate at launch; set a float to override.
    gpu_memory_utilization: float | None = (
        float(v)
        if (v := get_optional_env("ARIA_VLLM_GPU_MEMORY_UTILIZATION", ""))
        else None
    )
    quantization: str | None = get_optional_env("ARIA_VLLM_QUANT", "") or None
    tensor_parallel_size: int = int(get_optional_env("ARIA_VLLM_TP_SIZE", "1"))
    dtype: str = get_optional_env("ARIA_VLLM_DTYPE", "auto")
    kv_cache_dtype: str = get_optional_env("ARIA_VLLM_KV_CACHE_DTYPE", "auto")
    api_key: str = get_optional_env("ARIA_VLLM_API_KEY", "sk-aria")
    tool_call_parser: str = get_optional_env(
        "ARIA_VLLM_TOOL_CALL_PARSER", "qwen3_coder"
    )
    reasoning_parser: str = get_optional_env("ARIA_VLLM_REASONING_PARSER", "")
    chat_template_kwargs: str = get_optional_env("ARIA_VLLM_CHAT_TEMPLATE_KWARGS", "")
    vision_enabled: bool = (
        get_optional_env("ARIA_VLLM_VISION_ENABLED", "").lower() == "true"
    )
    data_parallel_size: int = int(get_optional_env("ARIA_VLLM_DATA_PARALLEL_SIZE", "1"))
    expert_parallel: bool = (
        get_optional_env("ARIA_VLLM_EXPERT_PARALLEL", "").lower() == "true"
    )
    mm_encoder_tp_mode: str = get_optional_env("ARIA_VLLM_MM_ENCODER_TP_MODE", "")
    mm_processor_cache_type: str = get_optional_env(
        "ARIA_VLLM_MM_PROCESSOR_CACHE_TYPE", ""
    )
    moe_backend: str = get_optional_env("ARIA_VLLM_MOE_BACKEND", "")
    linear_backend: str = get_optional_env("ARIA_VLLM_LINEAR_BACKEND", "")
    prefix_caching: bool = (
        get_optional_env("ARIA_VLLM_PREFIX_CACHING", "").lower() == "true"
    )

    # --- KV cache RAM offloading ---
    kv_offload_mode: str = get_optional_env("ARIA_VLLM_KV_OFFLOAD_MODE", "off")
    """KV cache offload strategy: 'off' (GPU-only), 'auto' (enable when VRAM
    is tight), 'ram' (force RAM offload).  Default: 'off'."""

    _kv_offloading_size_raw = get_optional_env("ARIA_VLLM_KV_OFFLOADING_SIZE_GB", "")
    kv_offloading_size_gb: float | None = (
        float(_kv_offloading_size_raw) if _kv_offloading_size_raw else None
    )
    """Explicit KV cache offload buffer size in GiB.  When None and mode is
    'auto' or 'ram', the size is calculated from model architecture."""

    kv_offloading_backend: str = get_optional_env(
        "ARIA_VLLM_KV_OFFLOADING_BACKEND", "native"
    )
    """Backend for KV cache offloading: 'native' (vLLM built-in) or
    'lmcache'.  Default: 'native'."""

    # Validate enum fields at class-load time
    _VALID_OFFLOAD_MODES = ("off", "auto", "ram")
    _VALID_OFFLOAD_BACKENDS = ("native", "lmcache")
    if kv_offload_mode not in _VALID_OFFLOAD_MODES:
        raise ValueError(
            f"ARIA_VLLM_KV_OFFLOAD_MODE must be one of {_VALID_OFFLOAD_MODES}, "
            f"got '{kv_offload_mode}'"
        )
    if kv_offloading_backend not in _VALID_OFFLOAD_BACKENDS:
        raise ValueError(
            f"ARIA_VLLM_KV_OFFLOADING_BACKEND must be one of "
            f"{_VALID_OFFLOAD_BACKENDS}, got '{kv_offloading_backend}'"
        )
    if kv_offloading_size_gb is not None and kv_offloading_size_gb <= 0:
        raise ValueError(
            f"ARIA_VLLM_KV_OFFLOADING_SIZE_GB must be > 0, "
            f"got '{kv_offloading_size_gb}'"
        )

    max_tokens: int = int(get_optional_env("ARIA_MAX_TOKENS", "8192"))

    # --- LLM sampling parameters ---
    temperature: float = float(get_optional_env("ARIA_VLLM_TEMPERATURE", "0.1"))
    top_p: float = float(get_optional_env("ARIA_VLLM_TOP_P", "0.95"))
    top_k: int = int(get_optional_env("ARIA_VLLM_TOP_K", "20"))
    min_p: float = float(get_optional_env("ARIA_VLLM_MIN_P", "0.0"))
    presence_penalty: float = float(
        get_optional_env("ARIA_VLLM_PRESENCE_PENALTY", "0.0")
    )
    repetition_penalty: float = float(
        get_optional_env("ARIA_VLLM_REPETITION_PENALTY", "1.0")
    )
    seed: int = int(get_optional_env("ARIA_VLLM_SEED", "42"))

    # Context sizes for each model type
    # Use int(v) if v is non-empty, otherwise fall back to default
    chat_context_size = (
        int(v) if (v := get_optional_env("CHAT_CONTEXT_SIZE", "")) else 65536
    )

    # Chat template file (Jinja2) for tool-calling format.
    # Resolved relative to the project root (Path.cwd())
    # Empty string = use model's built-in template.
    _chat_template_raw = get_optional_env("CHAT_TEMPLATE_FILE", "")
    chat_template_file: Path | None = (
        Path.cwd() / Path(_chat_template_raw) if _chat_template_raw else None
    )

    enforce_eager: bool = (
        get_optional_env("ARIA_VLLM_ENFORCE_EAGER", "").lower() == "true"
    )

    # Max concurrent sequences. vLLM defaults to 256, which is too many
    # for hybrid Mamba+attention models at large context sizes (each
    # sequence needs a Mamba cache block). Lower this if you see
    # "max_num_seqs exceeds available Mamba cache blocks" errors.
    max_num_seqs: int | None = (
        int(v) if (v := get_optional_env("ARIA_VLLM_MAX_NUM_SEQS", "")) else None
    )


class KnowledgeHub:
    """Configuration for the user documents knowledge hub (mini-RAG).

    Env-driven (see Lightpanda). The directory defaults to
    ``~/.aria/knowledge`` (under ``ARIA_HOME``).
    """

    enabled: bool = get_optional_env("ARIA_KNOWLEDGE_ENABLED", "").lower() == "true"
    dir: str = get_optional_env("ARIA_KNOWLEDGE_DIR", str(Knowledge.path))
    chunk_size: int = int(get_optional_env("ARIA_KNOWLEDGE_CHUNK_SIZE", "512"))
    chunk_overlap: int = int(get_optional_env("ARIA_KNOWLEDGE_CHUNK_OVERLAP", "64"))
    top_k: int = int(get_optional_env("ARIA_KNOWLEDGE_TOP_K", "4"))
    max_file_mb: int = int(get_optional_env("ARIA_KNOWLEDGE_MAX_FILE_MB", "50"))


class Lightpanda:
    """Configuration for Lightpanda browser binary (optional).

    Lightpanda is a lightweight headless browser that provides CDP
    (Chrome DevTools Protocol) for full browser automation via Playwright.

    Browser tools are disabled if the binary is not installed.
    Run 'aria lightpanda download' to install.
    """

    version: str = get_optional_env("LIGHTPANDA_VERSION", "nightly")
    port: int = int(get_optional_env("LIGHTPANDA_PORT", "9222"))

    @classmethod
    def get_bin_path(cls) -> Path:
        """Get the resolved binary directory path."""
        return Bin.path

    @classmethod
    def get_binary_path(cls) -> Path | None:
        """Get the binary path, or None if not installed.

        Lightpanda uses a single binary name across platforms.

        Returns:
            Path to the binary if it exists, None otherwise.
        """
        binary = cls.get_bin_path() / "lightpanda"
        return binary if binary.exists() else None

    @classmethod
    def is_available(cls) -> bool:
        """Check if Lightpanda is installed and ready.

        Returns:
            True if the binary exists, False otherwise.
        """
        return cls.get_binary_path() is not None
