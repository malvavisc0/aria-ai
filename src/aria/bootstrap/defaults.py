"""VRAM-tiered model defaults for ``aria init``.

Loads the packaged ``models.json`` and resolves the first matching tier
(``min_vram_mb`` inclusive, checked top-down) for a detected
``HardwareProfile``. Tier values are decided constants (not derived from
``calculate_max_safe_context``); init writes them explicitly to ``.env``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import as_file, files
from typing import Any

from aria.bootstrap.detect import HardwareProfile

_TIER_SCHEMA_KEYS = (
    "min_vram_mb",
    "chat_model",
    "quant",
    "context_size",
    "voice_allowed",
)


@dataclass(frozen=True)
class TierDefaults:
    """Resolved tier defaults for the given hardware.

    Attributes:
        chat_model: HuggingFace repo id for the chat model, or ``None``
            when no GPU is present (remote required).
        quant: vLLM quantization flag (``"gptq"`` / ``"awq"``) or ``None``.
        context_size: Decided ``CHAT_CONTEXT_SIZE`` value, or ``None``.
        voice_allowed: Whether voice should be offered at all. ``False`` for
            the no-GPU tier (CPU voice is too slow — decided).
    """

    chat_model: str | None
    quant: str | None
    context_size: int | None
    voice_allowed: bool

    @property
    def served_model_name(self) -> str | None:
        """The ``CHAT_MODEL`` value derived from the tier repo id.

        ``CHAT_MODEL`` is the served-model name (``server/vllm.py`` passes
        it as ``served_model_name=Chat.model``) and is required by
        ``config/models.py``. Derived from the tier repo id's last segment
        (e.g. ``Qwen3.8-4B-gptq-int4``) unless the user already set one.
        """
        if not self.chat_model:
            return None
        return self.chat_model.rsplit("/", 1)[-1]


def _load_tiers() -> list[dict[str, Any]]:
    """Load and validate the packaged tier definitions from ``models.json``.

    Tiers are returned in the file's declared order (top-down, first
    matching ``min_vram_mb`` wins). Validates the schema and the
    non-overlapping descending order so a corrupted file fails fast.
    """
    ref = files("aria.bootstrap").joinpath("models.json")
    with as_file(ref) as path:
        data = json.loads(path.read_text(encoding="utf-8"))

    raw_tiers = data.get("tiers")
    if not isinstance(raw_tiers, list) or not raw_tiers:
        raise ValueError("bootstrap/models.json: missing or empty 'tiers'")

    tiers: list[dict[str, Any]] = []
    for entry in raw_tiers:
        if not isinstance(entry, dict):
            raise ValueError("bootstrap/models.json: tier entries must be objects")
        missing = [k for k in _TIER_SCHEMA_KEYS if k not in entry]
        if missing:
            raise ValueError(f"bootstrap/models.json: tier missing keys {missing}")
        tiers.append(entry)

    # Tiers must be sorted descending by min_vram_mb and non-overlapping.
    floors = [t["min_vram_mb"] for t in tiers]
    if floors != sorted(floors, reverse=True):
        raise ValueError(
            "bootstrap/models.json: tiers must be sorted descending by min_vram_mb"
        )
    return tiers


def resolve_defaults(hardware: HardwareProfile) -> TierDefaults:
    """Pick the first matching tier (``min_vram_mb`` inclusive, top-down)."""
    tiers = _load_tiers()
    vram = hardware.vram_mb
    for tier in tiers:
        if vram >= tier["min_vram_mb"]:
            return TierDefaults(
                chat_model=tier["chat_model"],
                quant=tier["quant"],
                context_size=tier["context_size"],
                voice_allowed=tier["voice_allowed"],
            )
    # Defensive: the no-GPU tier has min_vram_mb=0 so this is unreachable
    # unless models.json is malformed. Fail fast rather than silently pick.
    raise ValueError("bootstrap/models.json: no matching tier for vram=0")
