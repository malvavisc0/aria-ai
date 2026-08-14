"""Model configuration for the Aria application.

Each model class exposes a ``model_path`` that can be either a HuggingFace
Hub repository ID (e.g. ``"TheBloke/Lucy-128k-GPTQ"``) or an absolute
local filesystem path to a downloaded snapshot directory.

Class attributes are evaluated lazily on first access so that importing
this module does NOT require environment variables to be set.  This makes
the module testable without env fixtures and avoids import-order landmines.

Environment Variables:
    CHAT_MODEL_PATH: HuggingFace repo ID or local path for the chat model.
    EMBED_MODEL_PATH: HuggingFace repo ID or local path for the embeddings model.
"""

import random
import urllib.parse
from pathlib import Path
from typing import Any

from aria.config import get_optional_env, get_required_env
from aria.config.api import Vllm as VllmConfig
from aria.config.folders import Models

_SENTINEL = object()


class _Lazy:
    """Descriptor that defers evaluation until first attribute access.

    This enables class-level attributes to be declared declaratively
    while avoiding import-time side effects (e.g. env-var lookups that
    raise ``ValueError`` when the variable is unset).
    """

    def __init__(self, factory: Any) -> None:
        self._factory = factory
        self._value: Any = _SENTINEL

    def __set_name__(self, owner: type, name: str) -> None:
        self._attr = name

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if self._value is _SENTINEL:
            self._value = self._factory()
        return self._value


def reset_lazy_config(*classes: type) -> None:
    """Clear memoized ``_Lazy`` values so they re-evaluate on next access.

    Call after reloading .env so env-derived config picks up new values.
    """
    for cls in classes:
        for attr in vars(cls).values():
            if isinstance(attr, _Lazy):
                attr._value = _SENTINEL


def _resolve_model_path(path: str) -> str:
    """Resolve a model path against ~/.aria/models/.

    All models must reside under ~/.aria/models/. For HuggingFace
    repo IDs (e.g. ``Stffens/bge-small-rrf-v4``), only the model name
    (last segment) is used as the local directory name.

    - Empty string → return as-is (not configured)
    - Absolute path → use as-is
    - Otherwise → resolve against ~/.aria/models/ using last segment
    """
    if not path:
        return path
    if Path(path).is_absolute():
        return path
    # For HF repo IDs like "org/model-name", use only "model-name"
    model_name = path.rsplit("/", maxsplit=1)[-1].lower()
    return str(Models.path / model_name)


class _PortCache:
    value: int | None = None


_port = _PortCache()


def _random_user_port() -> int:
    """Generate a random port in the user/dynamic range (49152–65535).

    Used as a last-resort fallback when the configured API URL has no
    explicit port (e.g. bare hostname without :PORT). The port is cached
    so that repeated calls return the same value, preventing the vLLM
    command and health check from using different ports.
    """
    if _port.value is None:
        _port.value = random.randint(49152, 65535)
    return _port.value


class Chat:
    """Chat model configuration (lazy — evaluated on first access)."""

    api_url = _Lazy(lambda: get_required_env("CHAT_OPENAI_API"))
    model = _Lazy(lambda: get_required_env("CHAT_MODEL"))
    max_iteration = _Lazy(lambda: int(get_required_env("MAX_ITERATIONS")))
    model_path = _Lazy(
        lambda: _resolve_model_path(get_optional_env("CHAT_MODEL_PATH", ""))
    )

    @classmethod
    def get_port(cls) -> int:
        return urllib.parse.urlparse(cls.api_url).port or _random_user_port()


class Embeddings:
    """Embeddings model configuration (lazy — evaluated on first access)."""

    model = _Lazy(lambda: get_required_env("EMBEDDINGS_MODEL"))
    context_size = _Lazy(
        lambda: int(get_optional_env("EMBEDDINGS_CONTEXT_SIZE", "2048"))
    )
    token_limit_ratio = _Lazy(
        lambda: float(get_optional_env("TOKEN_LIMIT_RATIO", "0.85"))
    )
    token_limit = _Lazy(
        lambda: int(Embeddings._effective_context_size() * Embeddings.token_limit_ratio)
    )

    @staticmethod
    def _effective_context_size() -> int:
        """Compute the effective context after GPU KV cache clamping.

        Uses the same logic as ``VllmServerManager._clamp_context_to_gpu_kv``
        so the memory system's token budget matches what the model actually
        supports.

        Warns when the clamped size collapses below a usable threshold —
        this happens when a large model leaves too little VRAM for the KV
        cache, silently shrinking the memory budget to near-zero.
        """
        requested = VllmConfig.chat_context_size
        model_path = _resolve_model_path(get_optional_env("CHAT_MODEL_PATH", ""))
        if not model_path or not Path(model_path).exists():
            return requested
        try:
            from aria.server.vllm import VllmServerManager

            ctx = VllmServerManager._resolve_max_model_len(model_path, requested)
            gpu_mem = VllmConfig.gpu_memory_utilization
            if gpu_mem is None:
                gpu_mem = 0.90
            effective = VllmServerManager._clamp_context_to_gpu_kv(
                model_path=model_path,
                requested_context=ctx,
                gpu_memory_utilization=gpu_mem,
                kv_cache_dtype=VllmConfig.kv_cache_dtype,
            )
            if effective < requested * 0.5:
                from loguru import logger

                logger.warning(
                    f"Context collapsed {requested:,} → {effective:,} tokens "
                    f"due to GPU KV cache limits. Memory budget will be very "
                    f"small (token_limit ≈ {int(effective * Embeddings.token_limit_ratio):,}). "
                    f"Consider a smaller model or raise TOKEN_LIMIT_RATIO "
                    f"to preserve memory budget at the cost of scratchpad."
                )
            return effective
        except Exception:
            return requested

    chat_history_token_ratio = _Lazy(
        lambda: float(get_optional_env("CHAT_HISTORY_TOKEN_RATIO", "0.50"))
    )
    model_path = _Lazy(
        lambda: _resolve_model_path(get_optional_env("EMBED_MODEL_PATH", ""))
    )
