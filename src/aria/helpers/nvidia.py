import json
import re
import subprocess
from pathlib import Path

from loguru import logger
from pydantic import BaseModel


class GPUMetadata(BaseModel):
    """
    Pydantic model to store detailed information about a GPU.
    """

    index: int
    name: str
    uuid: str
    total_memory: int  # in MiB
    used_memory: int  # in MiB
    free_memory: int  # in MiB
    memory_utilization: float  # percentage
    power_limit: int  # in watts
    power_draw: int  # in watts
    temperature: int  # in Celsius
    fan_speed: int  # in percent
    driver_version: str
    display_active: bool
    compute_mode: str


def _parse_memory(values: list[str]) -> tuple[int, int, int] | None:
    try:
        total_mem = int(float(values[3])) if values[3] else 0
        used_mem = int(float(values[4])) if values[4] else 0
        free_mem = int(float(values[5])) if values[5] else 0
    except (ValueError, IndexError):
        return None
    return total_mem, used_mem, free_mem


def _parse_numeric(value: str, suffixes: list[str] | None = None) -> int:
    """Parse numeric value, optionally removing unit suffixes."""
    if not value:
        return 0
    try:
        cleaned = value
        if suffixes:
            for suffix in suffixes:
                cleaned = cleaned.replace(suffix, "")
        return int(float(cleaned))
    except (ValueError, AttributeError):
        return 0


def _parse_display_active(value: str) -> bool:
    return value.lower() in ("enabled", "yes", "true", "1")


def _parse_gpu_line(line: str) -> GPUMetadata | None:
    values = [v.strip() for v in line.split(",")]
    if len(values) < 13:
        return None
    memory = _parse_memory(values)
    if memory is None:
        return None
    total_mem, used_mem, free_mem = memory
    memory_util = round((used_mem / total_mem * 100), 2) if total_mem > 0 else 0.0
    return GPUMetadata(
        index=int(values[0]),
        name=values[1],
        uuid=values[2],
        total_memory=total_mem,
        used_memory=used_mem,
        free_memory=free_mem,
        memory_utilization=memory_util,
        power_limit=_parse_numeric(values[8], ["W", "w"]),
        power_draw=_parse_numeric(values[9], ["W", "w"]),
        temperature=_parse_numeric(values[10], ["C", "c"]),
        fan_speed=_parse_numeric(values[11], ["%"]),
        driver_version=values[7],
        display_active=_parse_display_active(values[12]),
        compute_mode=values[6],
    )


def _query_nvidia_smi() -> str:
    return subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,uuid,memory.total,memory.used,memory.free,"
            "compute_mode,driver_version,power.limit,power.draw,temperature.gpu,"
            "fan.speed,display_active",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def detect_gpus_with_details(log_errors: bool = False) -> list[GPUMetadata]:
    """
    Detect all installed NVIDIA GPUs with detailed information.

    Executes nvidia-smi query to gather comprehensive GPU information
    including memory, power, temperature, fan speed, and more.

    Args:
        log_errors: If True, log warnings when nvidia-smi fails.

    Returns:
        List[GPUMetadata]: A list of GPUMetadata objects, one for each detected GPU.
                          Returns empty list if nvidia-smi is unavailable or fails.

    Raises:
        None: All exceptions are caught and handled internally
    """
    try:
        stdout = _query_nvidia_smi()
    except Exception as exc:
        if log_errors:
            logger.warning(f"Failed to detect GPUs: {exc}")
        return []

    gpus = []
    for line in stdout.strip().split("\n"):
        if not line.strip():
            continue
        gpu = _parse_gpu_line(line)
        if gpu is not None:
            gpus.append(gpu)
    return gpus


def detect_gpu_count() -> int:
    """
    Detect the number of available GPUs on the system.

    Executes `nvidia-smi -L` via subprocess to list all GPUs and counts the
    non-empty lines in the output. Returns 0 if nvidia-smi is not available
    or fails to execute.

    Returns:
        int: Number of GPUs detected (0 if nvidia-smi fails or is unavailable)

    Raises:
        None: All exceptions are caught and handled internally
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"], capture_output=True, text=True, check=True
        )
        # Filter empty lines to get accurate count
        lines = [
            line.strip() for line in result.stdout.strip().split("\n") if line.strip()
        ]
        return len(lines)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 0


def get_total_vram_mb() -> int:
    """
    Calculate the total VRAM across all available GPUs.

    Executes `nvidia-smi --query-gpu=memory.total` to query VRAM for each GPU,
    sums all values, and returns the total in MiB. Returns 0 if nvidia-smi
    is unavailable or parsing fails.

    Returns:
        int: Total VRAM across all GPUs in MiB (0 on failure)

    Raises:
        None: All exceptions are caught and handled internally
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        # Filter empty lines before processing
        vram_values = [
            vram.strip() for vram in result.stdout.strip().split("\n") if vram.strip()
        ]
        total_vram = sum(int(vram) for vram in vram_values)
        return total_vram
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return 0


def get_per_gpu_vram_mb() -> int:
    """Get VRAM of a single GPU (assumes homogeneous GPUs for TP).

    Queries per-GPU VRAM directly via a single ``nvidia-smi`` call.
    For single-GPU systems this is identical to ``get_total_vram_mb()``.
    For multi-GPU systems this returns the per-GPU VRAM, which is what
    vLLM's ``--gpu-memory-utilization`` actually applies to.

    Returns:
        Per-GPU VRAM in MiB, or 0 if nvidia-smi is unavailable.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        vram_values = [
            int(vram.strip())
            for vram in result.stdout.strip().split("\n")
            if vram.strip()
        ]
        if not vram_values:
            return 0
        # Return the minimum per-GPU VRAM (most constrained for TP)
        return min(vram_values)
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return 0


def check_gpu_memory_usage(gpu_index: int, usage_threshold: float) -> bool:
    """
    Check if a specific GPU's memory usage is below a specified threshold.

    Args:
        gpu_index: Index of the GPU to check (0-based indexing)
        usage_threshold: Memory usage threshold in percentage (0.0-100.0)

    Returns:
        bool: True if GPU memory usage is below threshold, False otherwise.
              Returns False for invalid inputs or when nvidia-smi fails.

    Raises:
        None: All exceptions are caught and handled internally
    """
    # Input validation
    if gpu_index < 0:
        return False
    if not (0.0 <= usage_threshold <= 100.0):
        return False

    try:
        # Query both memory.used and memory.total in a single call
        result = subprocess.run(
            [
                "nvidia-smi",
                f"--id={gpu_index}",
                "--query-gpu=memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Parse the output
        values = result.stdout.strip().split(",")
        if len(values) != 2:
            return False

        used_mb = int(values[0].strip())
        total_mb = int(values[1].strip())

        # Protect against division by zero
        if total_mb == 0:
            return False

        usage_percentage = (used_mb / total_mb) * 100
        return usage_percentage < usage_threshold

    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        ValueError,
        IndexError,
    ):
        return False


def get_free_vram_per_gpu() -> list[int]:
    """
    Get the free VRAM for each available GPU.

    Executes `nvidia-smi --query-gpu=memory.free` to query free memory for
    each GPU and returns a list of free VRAM values in MiB. Returns empty
    list if nvidia-smi is unavailable or parsing fails.

    Returns:
        List[int]: List of free VRAM values per GPU in MiB (empty list on failure)

    Raises:
        None: All exceptions are caught and handled internally
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        free_vram_values = [
            int(vram.strip())
            for vram in result.stdout.strip().split("\n")
            if vram.strip()
        ]
        return free_vram_values
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return []


def detect_nvlink() -> tuple[bool, str | None]:
    """
    Detect NVLink connectivity and bonding status between GPUs.

    Executes `nvidia-smi topo -m` to check GPU topology and searches for
    NVLink indicators (NV1-NV9 pattern) and bonded connections.

    Returns:
        Tuple[bool, Optional[str]]: A tuple containing:
            - bool: True if NVLink is detected, False otherwise
            - Optional[str]: "Bonded" if bonded connection found, None otherwise

    Raises:
        None: All exceptions are caught and handled internally
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "topo", "-m"],
            capture_output=True,
            text=True,
            check=True,
        )

        # Search for NVLink patterns in the output
        nvlink_pattern = re.compile(r"NV\d")
        bond_pattern = re.compile(r"Bonded")

        has_nvlink = bool(nvlink_pattern.search(result.stdout))
        bond_type = "Bonded" if bond_pattern.search(result.stdout) else None

        return (has_nvlink, bond_type)

    except (subprocess.CalledProcessError, FileNotFoundError):
        return (False, None)


def check_nvidia_smi_available() -> bool:
    """
    Check if nvidia-smi is available and executable on the system.

    Executes `nvidia-smi --version` to verify availability. Returns True if
    nvidia-smi is found and executable, False otherwise.

    Returns:
        bool: True if nvidia-smi is available, False otherwise

    Raises:
        None: All exceptions are caught and handled internally
    """
    try:
        subprocess.run(
            ["nvidia-smi", "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_cuda_version() -> str:
    """Get the CUDA version from nvidia-smi.

    Parses the CUDA version from ``nvidia-smi --version`` output.

    Returns:
        CUDA version string (e.g. ``"13.2"``, ``"12.4"``), or ``""``
        if unavailable.

    Example:
        ```python
        cuda = get_cuda_version()
        # "13.2"
        ```
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        match = re.search(r"CUDA Version\s*:\s*(\d+\.\d+)", result.stdout)
        return match.group(1) if match else ""
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def get_nvidia_smi_version() -> str:
    """
    Get the version of nvidia-smi installed on the system.

    Executes `nvidia-smi --version` and parses the version number using
    regex pattern matching. Returns empty string if version cannot be retrieved.

    Returns:
        str: The nvidia-smi version string (e.g., "535.104.05")
             Returns empty string if version cannot be retrieved

    Raises:
        None: All exceptions are caught and handled internally
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        # Use regex for more robust version parsing
        # Handles both "NVIDIA-SMI 535.104.05" and "NVIDIA-SMI version  : 590.48.01"
        match = re.search(
            r"NVIDIA-SMI\s+(?:version\s*:\s*)?(\d+\.\d+(?:\.\d+)?)",
            result.stdout,
        )
        return match.group(1) if match else ""
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


_SAFETY_MARGIN = 0.10
_MIN_CONTEXT = 1024
_ABSOLUTE_MIN_GB = 1.5

_EMBEDDING_TIERS = [
    (2, 256),
    (3, 384),
    (4, 512),
    (6, 768),
    (8, 1024),
    (12, 1536),
    (16, 2048),
    (24, 3072),
    (32, 4096),
]

_LLM_TIERS = [
    (4, 2048),
    (6, 4096),
    (8, 8192),
    (10, 12288),
    (12, 16384),
    (14, 24576),
    (16, 32768),
    (20, 49152),
    (24, 65536),
    (28, 131072),
    (32, 262144),
    (40, 393216),
    (48, 524288),
    (64, 786432),
    (96, 1048576),
    (128, 1572864),
]


def _validate_context_inputs(free_vram_mb: int, model_size_mb: int) -> bool:
    if not isinstance(free_vram_mb, int) or not isinstance(model_size_mb, int):
        return False
    if free_vram_mb <= 0 or model_size_mb < 0:
        return False
    return not (model_size_mb > 0 and free_vram_mb < model_size_mb)


def _pick_tier(safe_memory_gb: float, tiers: list[tuple[int, int]]) -> int:
    for threshold_gb, tokens in tiers:
        if safe_memory_gb <= threshold_gb:
            return tokens
    return tiers[-1][1]


def calculate_max_safe_context(
    free_vram_mb: int, model_size_mb: int = 0, is_embedding_model: bool = False
) -> int:
    """Calculate the maximum safe context size (in tokens) for a model.

    See module docstring examples.  Pulled out of one function to keep
    complexity manageable.
    """
    if not _validate_context_inputs(free_vram_mb, model_size_mb):
        return 0

    tiers = _EMBEDDING_TIERS if is_embedding_model else _LLM_TIERS
    safe_memory_gb = (free_vram_mb - model_size_mb) * (1 - _SAFETY_MARGIN) / 1024
    if safe_memory_gb < _ABSOLUTE_MIN_GB:
        return 0

    return max(_MIN_CONTEXT, _pick_tier(safe_memory_gb, tiers))


# 4-bit KV cache types: 0.5 bytes per element
_KV_BYTES_4BIT = {
    "nvfp4",
    "int4_per_token_head",
    "turboquant_k8v4",
    "turboquant_4bit_nc",
    "turboquant_k3v4_nc",
    "turboquant_3bit_nc",
}


def _cfg_lookup(cfg: dict, text_cfg: dict, *keys: str) -> int | None:
    """Return the first truthy value for any of ``keys`` in cfg then text_cfg."""
    for source in (cfg, text_cfg):
        for key in keys:
            value = source.get(key)
            if value:
                return value
    return None


def _kv_arch_params(cfg: dict) -> tuple[int, int, int] | None:
    """Extract KV cache architecture parameters from config.

    Returns:
        Tuple of (num_layers, num_kv_heads, head_dim) or None if missing.
    """
    text_cfg = cfg.get("text_config") or {}

    num_layers = _cfg_lookup(cfg, text_cfg, "num_hidden_layers")
    num_kv_heads = _cfg_lookup(
        cfg, text_cfg, "num_key_value_heads", "num_attention_heads"
    )
    head_dim = _cfg_lookup(cfg, text_cfg, "head_dim")

    if not head_dim:
        hidden_size = _cfg_lookup(cfg, text_cfg, "hidden_size")
        num_heads = _cfg_lookup(cfg, text_cfg, "num_attention_heads")
        if hidden_size and num_heads:
            head_dim = hidden_size // num_heads

    if not (num_layers and num_kv_heads and head_dim):
        return None

    return int(num_layers), int(num_kv_heads), int(head_dim)


def _count_attn_layers(layer_types: list | None) -> int | None:
    """Count attention layers in hybrid Mamba+attention models.

    Returns:
        Number of full_attention layers, or None if layer_types is absent.
    """
    if not layer_types or not isinstance(layer_types, list):
        return None
    return sum(
        1 for lt in layer_types if isinstance(lt, str) and "full_attention" in lt
    )


def _kv_bytes_per_elem(kv_cache_dtype: str) -> float:
    """Bytes per KV cache element for the given dtype."""
    if kv_cache_dtype in _KV_BYTES_4BIT:
        return 0.5
    if kv_cache_dtype.startswith("fp8"):
        return 1.0
    return 2.0  # default: fp16/bf16


def _fallback_kv_estimate(
    model_size_mb: int, context_size: int, kv_cache_dtype: str
) -> int:
    """Estimate KV cache from model weight size when config.json is unavailable.

    Heuristic: kv_cache ≈ model_weights × (ctx / 32k) × dtype_factor
    where dtype_factor is the KV dtype size relative to fp16.
    """
    dtype_factor = _kv_bytes_per_elem(kv_cache_dtype) / 2.0
    return int(model_size_mb * (context_size / 32768) * dtype_factor)


def _resolve_model_size_mb(model_path: str, default_size_mb: int) -> int:
    """Read model weight size from disk, falling back to ``default_size_mb``.

    Logs an info message when the path is missing or unreadable.
    Returns ``default_size_mb`` in that case.
    """
    from pathlib import Path

    from aria.helpers.memory import get_model_file_size

    model_size_mb = 0
    if model_path:
        model_size_mb = get_model_file_size(Path(model_path))

    if model_size_mb <= 0:
        logger.info(
            "Model path '{path}' not found on disk; using default "
            "weight estimate of {default} MiB.",
            path=model_path or "(empty)",
            default=default_size_mb,
        )
        return default_size_mb
    return model_size_mb


def _clamp_to_free_vram(
    utilization: float,
    total_vram_mb: int,
    free_vram_mb: int,
    min_util: float,
) -> float:
    """Clamp utilization so vLLM does not OOM when other CUDA processes use VRAM.

    ``--gpu-memory-utilization`` is applied to total VRAM, not free. If
    utilization × total > free, vLLM OOMs. Returns a clamped value (or the
    original if no other processes are detected).
    """
    if free_vram_mb <= 0:
        return utilization

    cuda_margin_mb = 256
    max_safe_util = max(min_util, (free_vram_mb - cuda_margin_mb) / total_vram_mb)
    if utilization <= max_safe_util:
        return utilization

    clamped = round(max_safe_util, 2)
    logger.info(
        "Clamping gpu_memory_utilization from {orig:.2f} to "
        "{clamped:.2f} — other CUDA processes using "
        "{used_mb} MiB VRAM (free: {free} MiB, total: {total} MiB)",
        orig=utilization,
        clamped=clamped,
        used_mb=total_vram_mb - free_vram_mb,
        free=free_vram_mb,
        total=total_vram_mb,
    )
    return clamped


def _estimate_kv_cache_mb(
    model_path: str,
    context_size: int,
    kv_cache_dtype: str,
) -> int | None:
    """Estimate KV cache size from model architecture (config.json).

    Reads ``num_hidden_layers``, ``num_key_value_heads`` (or
    ``num_attention_heads`` for MHA), and ``head_dim`` (or derives it from
    ``hidden_size / num_attention_heads``) to compute the exact KV cache
    footprint.

    Formula::

        bytes_per_elem = 1 if fp8, else 2 (fp16)
        kv_per_token   = 2 × num_layers × num_kv_heads × head_dim × bytes
        total_bytes    = kv_per_token × context_size

    Returns:
        KV cache size in MiB, or None if config.json is unavailable.
    """
    config_path = Path(model_path) / "config.json" if model_path else None
    if not config_path or not config_path.is_file():
        return None

    try:
        with open(config_path) as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    # Extract architecture parameters
    params = _kv_arch_params(cfg)
    if params is None:
        return None
    num_layers, num_kv_heads, head_dim = params

    # Account for hybrid Mamba+attention models
    text_cfg = cfg.get("text_config") or {}
    attn_layers = _count_attn_layers(
        text_cfg.get("layer_types") or cfg.get("layer_types")
    )
    if attn_layers:
        num_layers = attn_layers

    # O(1) lookup for bytes per element
    bytes_per_elem = _kv_bytes_per_elem(kv_cache_dtype)

    # 2 tensors (K + V) per layer
    kv_per_token = 2 * num_layers * num_kv_heads * head_dim * bytes_per_elem
    total_bytes = kv_per_token * context_size
    kv_mb = int(total_bytes // (1024 * 1024))

    logger.debug(
        "KV cache from config.json: layers={} (attn-only), kv_heads={}, head_dim={}, "
        "dtype={}, ctx={} → {} MiB",
        num_layers,
        num_kv_heads,
        head_dim,
        kv_cache_dtype,
        context_size,
        kv_mb,
    )
    return kv_mb


def estimate_per_gpu_memory_mb(
    model_weights_mb: int | float,
    kv_cache_mb: int | float,
    tensor_parallel_size: int = 1,
    overhead_mb: int = 1536,
) -> tuple[float, float, float]:
    """Estimate per-GPU memory for sharded model weights and KV cache.

    When ``tensor_parallel_size > 1``, model weights and KV cache are
    sharded evenly across GPUs.  vLLM overhead (CUDA graphs, scratch
    buffers, headroom) is per-GPU and not sharded.

    Args:
        model_weights_mb: Total model weight size in MiB.
        kv_cache_mb: Total KV cache size in MiB.
        tensor_parallel_size: Number of GPUs for tensor parallelism.
        overhead_mb: Per-GPU fixed overhead (CUDA graphs + headroom).

    Returns:
        Tuple of ``(per_gpu_weights_mb, per_gpu_kv_mb, per_gpu_total_mb)``
        where ``per_gpu_total_mb`` includes the overhead.
    """
    tp = max(1, tensor_parallel_size)
    per_gpu_weights = model_weights_mb / tp
    per_gpu_kv = kv_cache_mb / tp
    per_gpu_total = per_gpu_weights + per_gpu_kv + overhead_mb
    return per_gpu_weights, per_gpu_kv, per_gpu_total


def calculate_gpu_memory_utilization(
    total_vram_mb: int,
    model_path: str = "",
    context_size: int = 65536,
    kv_cache_dtype: str = "auto",
    safety_factor: float = 1.20,
    headroom_mb: int = 1024,
    vllm_overhead_mb: int | None = None,
    free_vram_mb: int = 0,
    tensor_parallel_size: int = 1,
    enforce_eager: bool = False,
) -> float:
    """Calculate the optimal ``gpu_memory_utilization`` fraction for vLLM.

    Estimates **actual memory needs** from model weight size on disk and
    architecture-aware KV cache computation (read from the model's
    ``config.json``).  Falls back to a conservative heuristic when the
    config is unavailable.

    ``total_vram_mb`` should be the **per-GPU** VRAM (not the sum across
    all GPUs).  vLLM applies ``--gpu-memory-utilization`` to each GPU
    individually.  When ``tensor_parallel_size > 1``, model weights and
    KV cache are sharded across GPUs, so the per-GPU memory need is
    divided accordingly.

    The formula is::

        per_gpu_weights = model_weights / tp
        per_gpu_kv      = kv_cache / tp
        needed          = (per_gpu_weights + per_gpu_kv + overhead + headroom) × safety
        utilization     = needed / per_gpu_vram

    This means a small quantized model on a large GPU gets a low utilization
    (leaving headroom), instead of always reserving ~90%.

    Args:
        total_vram_mb: Per-GPU VRAM in MiB (from ``get_per_gpu_vram_mb()``).
        model_path: Local path to the model directory.  Used to read
            ``config.json`` for architecture info and measure weight size.
        context_size: Target maximum sequence length (from
            ``CHAT_CONTEXT_SIZE``).  Directly scales KV cache estimate.
        kv_cache_dtype: KV cache data type (``"auto"``, ``"fp8"``, etc.).
            ``"fp8"`` halves the KV cache memory footprint.
        safety_factor: Multiplier for the total memory estimate to account
            for activation memory, fragmentation, and batch processing.
            Default ``1.20`` (20% safety margin).
        headroom_mb: Fixed VRAM reserved for the OS, display, and thermal
            headroom.  Default 1024 MiB (1 GiB).
        vllm_overhead_mb: Fixed overhead for vLLM activation/scratch
            buffers and CUDA context (CUDA graph memory is profiled
            separately by vLLM v0.21+).  Defaults to 1536 MiB
            (non-eager) or 768 MiB (enforce_eager).
        free_vram_mb: Per-GPU free VRAM (not summed across GPUs).
        tensor_parallel_size: Number of GPUs for tensor parallelism.
            Model weights and KV cache are divided by this value to get
            per-GPU memory.  Default 1 (single GPU).

    Returns:
        Float in [0.50, 0.95] suitable for ``--gpu-memory-utilization``.
        Returns ``0.85`` as a safe fallback when inputs are insufficient.

    Example::

        >>> # 8 GB GPU, 9B INT4 model, 128k context, fp8 KV
        >>> calculate_gpu_memory_utilization(8192, "/models/9b-int4", 131072, "fp8")
        0.95

        >>> # 32 GB GPU, 9B INT4 model (~5 GiB weights), 128k ctx, fp8 KV
        >>> # KV = 2×40×8×128×131072×1 = 10 GiB, total ~17 GiB → util≈0.62
        >>> calculate_gpu_memory_utilization(33400, "/models/9b-int4", 131072, "fp8")
        0.62
    """
    MIN_UTILIZATION = 0.50
    MAX_UTILIZATION = 0.95
    FALLBACK = 0.85
    DEFAULT_MODEL_SIZE_MB = 4096  # Assume ~4 GiB if model path is unknown

    if vllm_overhead_mb is None:
        vllm_overhead_mb = 768 if enforce_eager else 1536

    if total_vram_mb <= 0:
        logger.warning(
            "Cannot auto-calculate gpu_memory_utilization: "
            "VRAM detection returned 0. Using fallback={}.",
            FALLBACK,
        )
        return FALLBACK

    model_size_mb = _resolve_model_size_mb(model_path, DEFAULT_MODEL_SIZE_MB)
    kv_cache_mb = _estimate_kv_cache_mb(model_path, context_size, kv_cache_dtype)
    kv_source = "config.json"
    if kv_cache_mb is None:
        kv_cache_mb = _fallback_kv_estimate(model_size_mb, context_size, kv_cache_dtype)
        kv_source = "heuristic (no config.json)"

    per_gpu_weights_mb, per_gpu_kv_mb, raw_needed_mb = estimate_per_gpu_memory_mb(
        model_weights_mb=model_size_mb,
        kv_cache_mb=kv_cache_mb,
        tensor_parallel_size=tensor_parallel_size,
        overhead_mb=vllm_overhead_mb + headroom_mb,
    )
    tp = max(1, tensor_parallel_size)
    needed_mb = int(raw_needed_mb * safety_factor)
    utilization = needed_mb / total_vram_mb
    utilization = max(
        MIN_UTILIZATION,
        min(MAX_UTILIZATION, round(utilization, 2)),
    )
    utilization = _clamp_to_free_vram(
        utilization, total_vram_mb, free_vram_mb, MIN_UTILIZATION
    )

    logger.info(
        "Auto-calculated gpu_memory_utilization={util:.2f}\n"
        "  VRAM per GPU:      {vram:>8,} MiB\n"
        "  Tensor parallel:   {tp:>8}\n"
        "  Model weights:     {model:>8,} MiB  ({per_gpu_model:>8,.0f} MiB/GPU)\n"
        "  KV cache estimate: {kv:>8,} MiB  ({per_gpu_kv:>8,.0f} MiB/GPU)  "
        "(ctx={ctx:,}, dtype={kv_dtype}, source={src})\n"
        "  vLLM overhead:     {over:>8,} MiB\n"
        "  Headroom:          {head:>8,} MiB\n"
        "  Raw needed/GPU:    {raw:>8,.0f} MiB\n"
        "  With safety (×{sf}): {needed:>8,.0f} MiB\n"
        "  → vLLM will use    {used:>8,} MiB ({pct:.0f}% of VRAM/GPU)",
        util=utilization,
        vram=total_vram_mb,
        tp=tp,
        model=model_size_mb,
        per_gpu_model=per_gpu_weights_mb,
        kv=kv_cache_mb,
        per_gpu_kv=per_gpu_kv_mb,
        ctx=context_size,
        kv_dtype=kv_cache_dtype,
        src=kv_source,
        over=vllm_overhead_mb,
        head=headroom_mb,
        raw=raw_needed_mb,
        sf=safety_factor,
        needed=needed_mb,
        used=int(total_vram_mb * utilization),
        pct=utilization * 100,
    )

    return utilization
