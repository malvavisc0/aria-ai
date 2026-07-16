import re
import subprocess

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
        # Query for comprehensive GPU information
        result = subprocess.run(
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
        )

        gpus = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue

            # Split the CSV line and extract values
            values = [v.strip() for v in line.split(",")]

            # Validate we have enough values (13 expected)
            if len(values) < 13:
                continue

            # Parse memory values with validation
            try:
                total_mem = int(float(values[3])) if values[3] else 0
                used_mem = int(float(values[4])) if values[4] else 0
                free_mem = int(float(values[5])) if values[5] else 0
            except (ValueError, IndexError):
                continue

            # Calculate memory utilization percentage (rounded to 2 decimals)
            memory_util = (
                round((used_mem / total_mem * 100), 2) if total_mem > 0 else 0.0
            )

            # Helper function to safely parse numeric values with unit suffixes
            def parse_numeric(value: str, suffixes: list[str] | None = None) -> int:
                """Parse numeric value, optionally removing unit suffixes."""
                if not value:
                    return 0
                try:
                    # Remove common suffixes if provided
                    cleaned = value
                    if suffixes:
                        for suffix in suffixes:
                            cleaned = cleaned.replace(suffix, "")
                    return int(float(cleaned))
                except (ValueError, AttributeError):
                    return 0

            # Parse power values (may have 'W' suffix)
            power_limit = parse_numeric(values[8], ["W", "w"])
            power_draw = parse_numeric(values[9], ["W", "w"])

            # Parse temperature (may have 'C' suffix)
            temperature = parse_numeric(values[10], ["C", "c"])

            # Parse fan speed (may have '%' suffix)
            fan_speed = parse_numeric(values[11], ["%"])

            # Parse display active (case-insensitive boolean)
            display_active_str = values[12].lower()
            display_active = display_active_str in [
                "enabled",
                "yes",
                "true",
                "1",
            ]

            gpu = GPUMetadata(
                index=int(values[0]),
                name=values[1],
                uuid=values[2],
                total_memory=total_mem,
                used_memory=used_mem,
                free_memory=free_mem,
                memory_utilization=memory_util,
                power_limit=power_limit,
                power_draw=power_draw,
                temperature=temperature,
                fan_speed=fan_speed,
                driver_version=values[7],
                display_active=display_active,
                compute_mode=values[6],
            )
            gpus.append(gpu)

        return gpus

    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        ValueError,
        IndexError,
    ) as e:
        if log_errors:
            logger.warning(f"Failed to detect GPUs: {e}")
        return []


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


def calculate_max_safe_context(
    free_vram_mb: int, model_size_mb: int = 0, is_embedding_model: bool = False
) -> int:
    """
    Calculate the maximum safe context size (in tokens) for a language model or embedding
    model based on available VRAM, accounting for the model's memory requirements and
    applying a safety margin.

    The function uses tiered thresholds that provide appropriate context sizes for different
    VRAM capacities, with more conservative values for embedding models. It validates inputs
    to prevent errors and ensures at least a minimum context size is always available when
    possible. The function distinguishes between regular language models and embedding models
    through a boolean flag, providing optimized context sizes for each type of model.

    Process:
    1. Validates input parameters (type and value checks)
    2. Subtracts model size from free VRAM to get available memory
    3. Applies a 10% safety margin to available memory
    4. Checks if safe memory meets minimum tier threshold
    5. Selects appropriate tier based on safe memory
    6. Returns context size (enforcing minimum of 1024 tokens)

    Args:
        free_vram_mb: Currently free VRAM in megabytes (from get_free_vram_per_gpu)
        model_size_mb: Size of the model being loaded in megabytes (including embeddings)
        is_embedding_model: Whether this is an embedding model (default: False)

    Returns:
        Maximum safe context size in tokens (0 if VRAM is insufficient)

    Examples:
        >>> # LLM with 16GB free VRAM, no model loaded
        >>> calculate_max_safe_context(16384, 0, False)
        32768

        >>> # Embedding model with 8GB free VRAM
        >>> calculate_max_safe_context(8192, 0, True)
        1024

        >>> # LLM with 10GB free, 2GB model
        >>> calculate_max_safe_context(10240, 2048, False)
        16384
    """
    # Constants
    SAFETY_MARGIN = 0.10  # 10% safety margin for other operations
    MIN_CONTEXT = 1024  # Minimum context size in tokens

    # Embedding-specific thresholds (more conservative, more granular)
    # Format: (memory_threshold_gb, context_tokens)
    EMBEDDING_TIERS = [
        (2, 256),  # 2GB → 256 tokens
        (3, 384),  # 3GB → 384 tokens
        (4, 512),  # 4GB → 512 tokens
        (6, 768),  # 6GB → 768 tokens
        (8, 1024),  # 8GB → 1024 tokens
        (12, 1536),  # 12GB → 1536 tokens
        (16, 2048),  # 16GB → 2048 tokens
        (24, 3072),  # 24GB → 3072 tokens
        (32, 4096),  # 32GB+ → 4096 tokens (max for embeddings)
    ]

    # Regular LLM tiers (more granular)
    # Format: (memory_threshold_gb, context_tokens)
    LLM_TIERS = [
        (4, 2048),  # 4GB → 2,048 tokens
        (6, 4096),  # 6GB → 4,096 tokens
        (8, 8192),  # 8GB → 8,192 tokens
        (10, 12288),  # 10GB → 12,288 tokens
        (12, 16384),  # 12GB → 16,384 tokens
        (14, 24576),  # 14GB → 24,576 tokens
        (16, 32768),  # 16GB → 32,768 tokens
        (20, 49152),  # 20GB → 49,152 tokens
        (24, 65536),  # 24GB → 65,536 tokens
        (28, 131072),  # 28GB → 131,072 tokens
        (32, 262144),  # 32GB → 262,144 tokens
        (40, 393216),  # 40GB → 393,216 tokens
        (48, 524288),  # 48GB → 524,288 tokens
        (64, 786432),  # 64GB → 786,432 tokens
        (96, 1048576),  # 96GB → 1,048,576 tokens
        (128, 1572864),  # 128GB → 1,572,864 tokens (max for LLMs)
    ]

    # Select appropriate tier list based on model type
    tiers = EMBEDDING_TIERS if is_embedding_model else LLM_TIERS

    # Absolute minimum memory threshold (below this, return 0)
    # This is lower than the first tier to allow the tier selection to work
    ABSOLUTE_MIN_GB = 1.5

    # Comprehensive input validation
    if not isinstance(free_vram_mb, int) or not isinstance(model_size_mb, int):
        return 0
    if free_vram_mb <= 0 or model_size_mb < 0:
        return 0
    if model_size_mb > 0 and free_vram_mb < model_size_mb:
        return 0

    # Calculate memory available after loading model
    available_after_model = free_vram_mb - model_size_mb

    # Apply safety margin
    safe_memory_mb = available_after_model * (1 - SAFETY_MARGIN)
    safe_memory_gb = safe_memory_mb / 1024

    # Check if we have enough for absolute minimum threshold
    if safe_memory_gb < ABSOLUTE_MIN_GB:
        return 0

    # Find the appropriate tier based on safe memory
    # Select the first tier where safe_memory_gb <= threshold
    context_size = MIN_CONTEXT
    for threshold_gb, tokens in tiers:
        if safe_memory_gb <= threshold_gb:
            context_size = tokens
            break
    else:
        # If no tier matched (memory exceeds all thresholds), use maximum tier
        context_size = tiers[-1][1]

    # Ensure we return at least the minimum context
    return max(MIN_CONTEXT, context_size)


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
    import json
    from pathlib import Path

    config_path = Path(model_path) / "config.json" if model_path else None
    if not config_path or not config_path.is_file():
        return None

    try:
        with open(config_path) as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    # Architecture parameters may live at the top level (e.g. Llama, Mistral-7B)
    # or nested inside "text_config" for multimodal / vision models (e.g.
    # Mistral3 / Pixtral, LLaVA).  Check both locations.
    text_cfg = cfg.get("text_config") or {}

    num_layers = cfg.get("num_hidden_layers") or text_cfg.get("num_hidden_layers")
    num_kv_heads = (
        cfg.get("num_key_value_heads")
        or cfg.get("num_attention_heads")
        or text_cfg.get("num_key_value_heads")
        or text_cfg.get("num_attention_heads")
    )
    head_dim = cfg.get("head_dim") or text_cfg.get("head_dim")

    if not head_dim:
        hidden_size = cfg.get("hidden_size") or text_cfg.get("hidden_size")
        num_heads = cfg.get("num_attention_heads") or text_cfg.get(
            "num_attention_heads"
        )
        if hidden_size and num_heads:
            head_dim = hidden_size // num_heads

    if not all((num_layers, num_kv_heads, head_dim)):
        return None

    # Type narrowing for static analysis (all() check above guarantees these)
    assert num_layers is not None
    assert num_kv_heads is not None
    assert head_dim is not None

    # 4-bit (nvfp4, int4) = 0.5 bytes/elem; 8-bit (fp8*) = 1 byte; else 16-bit = 2
    if kv_cache_dtype in (
        "nvfp4",
        "int4_per_token_head",
        "turboquant_k8v4",
        "turboquant_4bit_nc",
        "turboquant_k3v4_nc",
        "turboquant_3bit_nc",
    ):
        bytes_per_elem = 0.5
    elif kv_cache_dtype.startswith("fp8"):
        bytes_per_elem = 1
    else:
        bytes_per_elem = 2
    # 2 tensors (K + V) per layer
    kv_per_token = 2 * num_layers * num_kv_heads * head_dim * bytes_per_elem
    total_bytes = kv_per_token * context_size
    kv_mb = int(total_bytes // (1024 * 1024))

    logger.debug(
        "KV cache from config.json: layers={}, kv_heads={}, head_dim={}, "
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
    vllm_overhead_mb: int = 512,
    free_vram_mb: int = 0,
    tensor_parallel_size: int = 1,
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
        vllm_overhead_mb: Fixed overhead for vLLM CUDA kernels, buffers,
            and scratch memory.  Default 512 MiB.
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
    from pathlib import Path

    from aria.helpers.memory import get_model_file_size

    MIN_UTILIZATION = 0.50
    MAX_UTILIZATION = 0.90
    FALLBACK = 0.85
    DEFAULT_MODEL_SIZE_MB = 4096  # Assume ~4 GiB if model path is unknown

    # Guard: if VRAM detection failed, return a safe fallback
    if total_vram_mb <= 0:
        logger.warning(
            "Cannot auto-calculate gpu_memory_utilization: "
            "VRAM detection returned 0. Using fallback={}.",
            FALLBACK,
        )
        return FALLBACK

    # --- Step 1: Estimate model weight size from disk ---
    model_size_mb = 0
    if model_path:
        model_size_mb = get_model_file_size(Path(model_path))

    if model_size_mb <= 0:
        logger.info(
            "Model path '{path}' not found on disk; using default "
            "weight estimate of {default} MiB.",
            path=model_path or "(empty)",
            default=DEFAULT_MODEL_SIZE_MB,
        )
        model_size_mb = DEFAULT_MODEL_SIZE_MB

    # --- Step 2: Estimate KV cache size (architecture-aware) ---
    kv_cache_mb = _estimate_kv_cache_mb(model_path, context_size, kv_cache_dtype)

    kv_source = "config.json"
    if kv_cache_mb is None:
        # Fallback: estimate when config.json is unavailable.
        # Approximation: kv_cache ≈ model_weights × (ctx/32k) × dtype_factor
        # This assumes KV cache at 32k baseline is roughly proportional to
        # model weight size — conservative for GQA models, adequate for MHA.
        kv_source = "heuristic (no config.json)"
        if kv_cache_dtype in (
            "nvfp4",
            "int4_per_token_head",
            "turboquant_k8v4",
            "turboquant_4bit_nc",
            "turboquant_k3v4_nc",
            "turboquant_3bit_nc",
        ):
            kv_dtype_factor = 0.25
        elif kv_cache_dtype.startswith("fp8"):
            kv_dtype_factor = 0.5
        else:
            kv_dtype_factor = 1.0
        context_factor = context_size / 32768
        kv_cache_mb = int(model_size_mb * context_factor * kv_dtype_factor)

    # --- Step 3: Compute per-GPU memory needed (shard by TP) ---
    per_gpu_weights_mb, per_gpu_kv_mb, raw_needed_mb = estimate_per_gpu_memory_mb(
        model_weights_mb=model_size_mb,
        kv_cache_mb=kv_cache_mb,
        tensor_parallel_size=tensor_parallel_size,
        overhead_mb=vllm_overhead_mb + headroom_mb,
    )
    tp = max(1, tensor_parallel_size)
    needed_mb = int(raw_needed_mb * safety_factor)

    # --- Step 4: Calculate utilization ---
    utilization = needed_mb / total_vram_mb

    # Clamp to safe bounds
    utilization = max(MIN_UTILIZATION, min(MAX_UTILIZATION, round(utilization, 2)))

    # --- Step 4b: Account for other CUDA processes ---
    # When other processes consume VRAM, vLLM's --gpu-memory-utilization
    # is applied to TOTAL VRAM, not free VRAM.  If utilization × total > free,
    # vLLM will OOM during warmup.  Clamp to what's actually available.
    if free_vram_mb > 0:
        # Leave a small margin for CUDA context overhead
        cuda_margin_mb = 256
        max_safe_util = max(
            MIN_UTILIZATION,
            (free_vram_mb - cuda_margin_mb) / total_vram_mb,
        )
        if utilization > max_safe_util:
            logger.info(
                "Clamping gpu_memory_utilization from {orig:.2f} to "
                "{clamped:.2f} — other CUDA processes using "
                "{used_mb} MiB VRAM (free: {free} MiB, total: {total} MiB)",
                orig=utilization,
                clamped=round(max_safe_util, 2),
                used_mb=total_vram_mb - free_vram_mb,
                free=free_vram_mb,
                total=total_vram_mb,
            )
            utilization = round(max_safe_util, 2)

    # --- Step 5: Log the reasoning ---
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
