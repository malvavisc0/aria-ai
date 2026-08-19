"""Feature gating for ``aria init`` — the single decision table.

Chat mode and GPU are independent axes (see the plan's feature matrix).
``FeatureChoices`` carries the user's opt-ins (vision/voice); the matrix
keyed on ``(chat_mode, has_gpu)`` decides the rest. The ``.env`` writer
never overwrites a user-set value — init is re-runnable.

``config.toml`` accept/image stripping lives in
``aria.server.manager.sync_chainlit_features`` (regex-rewrite in place,
never re-copy the file) so both the CLI and GUI front-ends share one
writer. This module only computes the ``vision_enabled`` flag the
config.toml writer consumes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aria.bootstrap.defaults import TierDefaults, resolve_defaults
from aria.bootstrap.detect import HardwareProfile
from aria.helpers.dotenv import parse_dotenv, write_dotenv

CHAT_MODE_LOCAL = "local"
CHAT_MODE_REMOTE = "remote"

# Stock template default values — re-running init may overwrite these (the
# user hasn't customized them), but never a value the user set explicitly.
_STOCK_CHAT_CONTEXT_SIZE = "32768"
_STOCK_CHAT_MODEL = "Ministral-3-14B-Instruct-2512"
_STOCK_CHAT_MODEL_PATH = "RedHatAI/Ministral-3-14B-Instruct-2512-NVFP4"
_STOCK_ARIA_VLLM_QUANT = ""


@dataclass
class FeatureChoices:
    """User opt-ins collected by the ``aria init`` flow (or env-derived).

    Attributes:
        vision: User choice for ``ARIA_VLLM_VISION_ENABLED``. ``None`` means
            "not asked / default off". Forced ``false`` only when neither a
            local GPU nor a multimodal remote endpoint can serve it (the
            caller decides; this struct records the user's stated choice).
        voice: User choice for ``ARIA_VOICE_ENABLED``. Forced ``false`` with
            no GPU regardless of the user's choice (decided: CPU voice too
            slow); the interactive prompt is skipped in that case.
        remote_url / remote_api_key / remote_model: Remote endpoint fields
            written in remote mode (empty in local mode).
    """

    vision: bool | None = None
    voice: bool | None = None
    remote_url: str = ""
    remote_api_key: str = ""
    remote_model: str = ""


def _is_stock_or_unset(value: str, stock: str) -> bool:
    """True when *value* is unset or still the stock template default.

    These are the only values init is allowed to overwrite — a
    user-customized value always wins (init is re-runnable).
    """
    if not value:
        return True
    return value.strip() == stock


def _resolve_vision_value(current: str, choices: FeatureChoices) -> str | None:
    """Resolve the ``ARIA_VLLM_VISION_ENABLED`` value, or None to skip.

    Never overwrites a user-set value; only writes the user's stated choice
    when the current value is unset.
    """
    if current.strip().lower() in ("true", "false"):
        return None  # user already decided
    if choices.vision is None:
        return None
    return "true" if choices.vision else "false"


def _resolve_voice_value(
    current: str, hardware: HardwareProfile, choices: FeatureChoices
) -> str | None:
    """Resolve the ``ARIA_VOICE_ENABLED`` value, or None to skip.

    Forced ``false`` with no NVIDIA GPU (decided: CPU voice too slow) —
    even if the user opted in, the value is pinned to ``false``. With a
    GPU, the user's choice is written only when the value is unset.
    """
    if not hardware.has_nvidia_gpu:
        return "false"  # decided: no CPU voice
    if current.strip().lower() in ("true", "false"):
        return None  # user already decided
    if choices.voice is None:
        return None
    return "true" if choices.voice else "false"


def _apply_remote_env(values: dict[str, str], choices: FeatureChoices, set_fn) -> None:
    """Write the remote-mode endpoint fields."""
    if choices.remote_url:
        set_fn("CHAT_OPENAI_API", choices.remote_url)
    if choices.remote_api_key:
        set_fn("ARIA_VLLM_API_KEY", choices.remote_api_key)
    if choices.remote_model:
        set_fn("CHAT_MODEL", choices.remote_model)


def _apply_local_tier_env(
    values: dict[str, str], hardware: HardwareProfile, tier: TierDefaults | None, set_fn
) -> None:
    """Write the tier-derived chat defaults when the user hasn't customized them."""
    resolved = tier or resolve_defaults(hardware)
    if resolved.chat_model and _is_stock_or_unset(
        values.get("CHAT_MODEL_PATH", ""), _STOCK_CHAT_MODEL_PATH
    ):
        set_fn("CHAT_MODEL_PATH", resolved.chat_model)
    if resolved.served_model_name and _is_stock_or_unset(
        values.get("CHAT_MODEL", ""), _STOCK_CHAT_MODEL
    ):
        set_fn("CHAT_MODEL", resolved.served_model_name)
    if resolved.context_size is not None and _is_stock_or_unset(
        values.get("CHAT_CONTEXT_SIZE", ""), _STOCK_CHAT_CONTEXT_SIZE
    ):
        set_fn("CHAT_CONTEXT_SIZE", str(resolved.context_size))
    if resolved.quant and _is_stock_or_unset(
        values.get("ARIA_VLLM_QUANT", ""), _STOCK_ARIA_VLLM_QUANT
    ):
        set_fn("ARIA_VLLM_QUANT", resolved.quant)


def apply_mode_to_env(
    env_path: Path,
    chat_mode: str,
    hardware: HardwareProfile,
    choices: FeatureChoices,
    tier: TierDefaults | None = None,
) -> list[str]:
    """Apply the feature matrix to ``.env`` and return the changed keys.

    Never overwrites a user-set value: tier-derived defaults
    (``CHAT_MODEL_PATH`` / ``CHAT_MODEL`` / ``CHAT_CONTEXT_SIZE`` /
    ``ARIA_VLLM_QUANT``) are written only when the current value is the
    stock template default or unset. Docling device is mode-independent
    (``auto`` → cuda when a GPU is present, else ``cpu``). Voice is forced
    ``false`` without a GPU. Returns the list of changed keys for the
    summary report.

    Args:
        env_path: Path to the ``.env`` file (must exist).
        chat_mode: ``"local"`` or ``"remote"``.
        hardware: Detected hardware profile.
        choices: User opt-ins (vision/voice/remote endpoint).
        tier: Resolved tier defaults; auto-resolved from *hardware* when
            omitted (required for local mode).

    Raises:
        ValueError: when *chat_mode* is unknown.
    """
    if chat_mode not in (CHAT_MODE_LOCAL, CHAT_MODE_REMOTE):
        raise ValueError(f"unknown chat_mode: {chat_mode!r}")

    values, raw_lines = parse_dotenv(env_path)
    changed: list[str] = []

    def _set(key: str, new_value: str) -> None:
        old = values.get(key, "")
        if old.strip() == new_value.strip():
            return
        values[key] = new_value
        changed.append(key)

    # --- Chat mode switch (always written so the file reflects the choice) ---
    _set("ARIA_VLLM_REMOTE", "true" if chat_mode == CHAT_MODE_REMOTE else "false")

    if chat_mode == CHAT_MODE_REMOTE:
        _apply_remote_env(values, choices, _set)
    else:
        _apply_local_tier_env(values, hardware, tier, _set)

    # --- Docling device: independent of chat mode ---
    _set("ARIA_DOCLING_DEVICE", "auto" if hardware.has_nvidia_gpu else "cpu")

    # --- Vision: user choice, never overwrite an explicit value ---
    vision_value = _resolve_vision_value(
        values.get("ARIA_VLLM_VISION_ENABLED", ""), choices
    )
    if vision_value is not None:
        _set("ARIA_VLLM_VISION_ENABLED", vision_value)

    # --- Voice: forced false without a GPU, else user choice ---
    voice_value = _resolve_voice_value(
        values.get("ARIA_VOICE_ENABLED", ""), hardware, choices
    )
    if voice_value is not None:
        _set("ARIA_VOICE_ENABLED", voice_value)

    write_dotenv(env_path, values, raw_lines)
    return changed


def vision_enabled_for_config(
    hardware: HardwareProfile, chat_mode: str, choices: FeatureChoices
) -> bool:
    """Decide whether ``image/*`` MIME types should be kept in config.toml.

    Image uploads are only useful when vision is on. The user's explicit
    ``.env`` choice (handled by ``apply_mode_to_env``) is the source of
    truth at server start; this helper computes the post-init flag the
    config.toml writer consumes so the deployed file matches immediately.

    In local mode, vision needs a local GPU to serve a VLM. In remote mode,
    vision is the user's explicit choice (a remote endpoint may or may not
    be multimodal — init never infers it).
    """
    if not choices.vision:
        return False
    if chat_mode == CHAT_MODE_LOCAL:
        return hardware.has_nvidia_gpu
    return True


def small_gpu_warning(hardware: HardwareProfile, voice_enabled: bool) -> str | None:
    """Return the VRAM-contention advisory text, or None when not applicable.

    Decided: warn only (no serialization). Emitted when total VRAM < 12 GB
    and voice or docling CUDA is enabled — the shared VRAM budget can OOM
    when both run concurrently on small cards.
    """
    if not hardware.has_nvidia_gpu or hardware.vram_mb >= 12288:
        return None
    docling_cuda = hardware.has_nvidia_gpu  # auto → cuda
    if not (voice_enabled or docling_cuda):
        return None
    gb = hardware.vram_mb / 1024
    return (
        f"Small GPU detected ({gb:.0f} GB VRAM). Local chat + CUDA docling"
        + (" + CUDA whisper" if voice_enabled else "")
        + " share the VRAM budget and may OOM when used concurrently. "
        "Context size was tuned for this card; see `aria config optimize` "
        "for KV-offload tuning."
    )
