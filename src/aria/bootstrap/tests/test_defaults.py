"""Tests for [`resolve_defaults`](../defaults.py) — tier boundaries."""

import pytest

from aria.bootstrap.defaults import _load_tiers, resolve_defaults
from aria.bootstrap.detect import HardwareProfile


def _hw(vram: int) -> HardwareProfile:
    return HardwareProfile(
        has_nvidia_gpu=vram > 0,
        has_rocm=False,
        cuda_version="12.8" if vram > 0 else "",
        vram_mb=vram,
        platform="nvidia" if vram > 0 else "cpu",
    )


@pytest.mark.parametrize(
    ("vram", "model", "quant", "ctx", "voice"),
    [
        (24576, "cyankiwi/gemma-4-12B-it-AWQ-INT4", "awq", 262144, True),
        (49152, "cyankiwi/gemma-4-12B-it-AWQ-INT4", "awq", 262144, True),
        (16384, "malvavisc0/Qwen3.8-9B-gptq-int4", "gptq", 204800, True),
        (16383, "malvavisc0/Qwen3.8-4B-gptq-int4", "gptq", 131072, True),
        (12288, "malvavisc0/Qwen3.8-4B-gptq-int4", "gptq", 131072, True),
        (12287, "malvavisc0/Qwen3.8-4B-gptq-int4", "gptq", 65536, True),
        (1, "malvavisc0/Qwen3.8-4B-gptq-int4", "gptq", 65536, True),
        (8192, "malvavisc0/Qwen3.8-4B-gptq-int4", "gptq", 65536, True),
        (0, None, None, None, False),
    ],
)
def test_tier_resolution(vram, model, quant, ctx, voice) -> None:
    tier = resolve_defaults(_hw(vram))
    assert tier.chat_model == model
    assert tier.quant == quant
    assert tier.context_size == ctx
    assert tier.voice_allowed is voice


def test_served_model_name_derived_from_repo_id() -> None:
    tier = resolve_defaults(_hw(16384))
    assert tier.served_model_name == "Qwen3.8-9B-gptq-int4"


def test_no_gpu_tier_has_null_model_and_no_voice() -> None:
    tier = resolve_defaults(_hw(0))
    assert tier.chat_model is None
    assert tier.context_size is None
    assert tier.voice_allowed is False
    assert tier.served_model_name is None


def test_tiers_sorted_non_overlapping() -> None:
    """models.json tiers must be descending and non-overlapping."""
    tiers = _load_tiers()
    floors = [t["min_vram_mb"] for t in tiers]
    assert floors == sorted(floors, reverse=True)
    # The last tier is the no-GPU catch-all (min_vram_mb == 0).
    assert floors[-1] == 0


def test_context_size_decided_values() -> None:
    """The four decided context sizes appear verbatim in the tiers."""
    tiers = _load_tiers()
    ctx_values = {t["context_size"] for t in tiers}
    assert {65536, 131072, 204800, 262144, None} == ctx_values


def test_invalid_chat_mode_raises() -> None:
    with pytest.raises(ValueError, match="unknown chat_mode"):
        from aria.bootstrap.features import apply_mode_to_env

        apply_mode_to_env(
            __import__("pathlib").Path("/tmp/.env"),
            "bogus",
            _hw(0),
            __import__(
                "aria.bootstrap.features", fromlist=["FeatureChoices"]
            ).FeatureChoices(),
        )
