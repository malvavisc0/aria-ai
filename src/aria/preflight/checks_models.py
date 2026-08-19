"""Model and token-limit preflight checks."""

from aria.preflight.results import CheckResult


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
                    hint=f"Run: aria init  (or aria models download --model {alias})",
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

    # Same effective-context clamping as _check_kv_cache_memory
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
