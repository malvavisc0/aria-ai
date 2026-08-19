"""Tests for the feature matrix and .env / config.toml writers.

Covers the four quadrants of the (chat_mode, has_gpu) matrix plus
re-run idempotence: user-set .env values are never overwritten, and the
config.toml accept/image block round-trips when vision is flipped.
"""

from __future__ import annotations

from importlib.resources import as_file, files
from pathlib import Path

from aria.bootstrap.detect import HardwareProfile
from aria.bootstrap.features import (
    CHAT_MODE_LOCAL,
    CHAT_MODE_REMOTE,
    FeatureChoices,
    apply_mode_to_env,
    small_gpu_warning,
    vision_enabled_for_config,
)


def _hw(vram: int) -> HardwareProfile:
    return HardwareProfile(
        has_nvidia_gpu=vram > 0,
        has_rocm=False,
        cuda_version="12.8" if vram > 0 else "",
        vram_mb=vram,
        platform="nvidia" if vram > 0 else "cpu",
    )


def _copy_template_env(tmp_path: Path) -> Path:
    """Copy the packaged .env.example into tmp_path/.env for a fresh write."""
    with as_file(files("aria").joinpath(".env.example")) as src:
        (tmp_path / ".env").write_text(src.read_text(), encoding="utf-8")
    return tmp_path / ".env"


def _read_env_value(env_path: Path, key: str) -> str:
    from aria.helpers.dotenv import parse_dotenv

    values, _ = parse_dotenv(env_path)
    return values.get(key, "")


# ---------------------------------------------------------------------------
# Quadrant: remote + no GPU
# ---------------------------------------------------------------------------


def test_remote_no_gpu_forces_voice_false_and_cpu_docling(
    monkeypatch, tmp_path: Path
) -> None:
    env = _copy_template_env(tmp_path)
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    choices = FeatureChoices(
        vision=False,
        voice=True,  # user wants voice, but no GPU → forced false
        remote_url="https://api.openai.com/v1",
        remote_api_key="sk-test",
        remote_model="gpt-4o",
    )
    changed = apply_mode_to_env(env, CHAT_MODE_REMOTE, _hw(0), choices)
    assert _read_env_value(env, "ARIA_VLLM_REMOTE") == "true"
    assert _read_env_value(env, "ARIA_VOICE_ENABLED") == "false"
    assert _read_env_value(env, "ARIA_DOCLING_DEVICE") == "cpu"
    assert _read_env_value(env, "CHAT_OPENAI_API") == "https://api.openai.com/v1"
    assert _read_env_value(env, "ARIA_VLLM_API_KEY") == "sk-test"
    assert _read_env_value(env, "CHAT_MODEL") == "gpt-4o"
    # Remote never touches tier-derived chat keys.
    assert "CHAT_MODEL_PATH" not in changed


# ---------------------------------------------------------------------------
# Quadrant: remote + GPU (GPU still used locally for docling/whisper)
# ---------------------------------------------------------------------------


def test_remote_with_gpu_keeps_auto_docling(monkeypatch, tmp_path: Path) -> None:
    env = _copy_template_env(tmp_path)
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    choices = FeatureChoices(
        vision=False,
        voice=False,
        remote_url="https://api/v1",
        remote_api_key="sk",
        remote_model="gpt-4o",
    )
    apply_mode_to_env(env, CHAT_MODE_REMOTE, _hw(24576), choices)
    assert _read_env_value(env, "ARIA_VLLM_REMOTE") == "true"
    # GPU present → docling auto (resolves to cuda), independent of chat mode.
    assert _read_env_value(env, "ARIA_DOCLING_DEVICE") == "auto"


# ---------------------------------------------------------------------------
# Quadrant: local + GPU (tier values written)
# ---------------------------------------------------------------------------


def test_local_with_gpu_writes_tier_values(monkeypatch, tmp_path: Path) -> None:
    env = _copy_template_env(tmp_path)
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    choices = FeatureChoices(vision=True, voice=True)
    changed = apply_mode_to_env(env, CHAT_MODE_LOCAL, _hw(24576), choices)
    assert _read_env_value(env, "ARIA_VLLM_REMOTE") == "false"
    assert _read_env_value(env, "CHAT_MODEL_PATH") == "cyankiwi/gemma-4-12B-it-AWQ-INT4"
    assert _read_env_value(env, "CHAT_MODEL") == "gemma-4-12B-it-AWQ-INT4"
    assert _read_env_value(env, "CHAT_CONTEXT_SIZE") == "262144"
    assert _read_env_value(env, "ARIA_VLLM_QUANT") == "awq"
    assert _read_env_value(env, "ARIA_DOCLING_DEVICE") == "auto"
    assert _read_env_value(env, "ARIA_VLLM_VISION_ENABLED") == "true"
    assert _read_env_value(env, "ARIA_VOICE_ENABLED") == "true"
    assert "CHAT_MODEL_PATH" in changed


# ---------------------------------------------------------------------------
# Quadrant: local + small GPU (4B tier, 65536 context, warning)
# ---------------------------------------------------------------------------


def test_local_small_gpu_uses_4b_tier_and_warns(monkeypatch, tmp_path: Path) -> None:
    env = _copy_template_env(tmp_path)
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    hw = _hw(8192)
    choices = FeatureChoices(vision=False, voice=False)
    apply_mode_to_env(env, CHAT_MODE_LOCAL, hw, choices)
    assert _read_env_value(env, "CHAT_MODEL_PATH") == "malvavisc0/Qwen3.8-4B-gptq-int4"
    assert _read_env_value(env, "CHAT_CONTEXT_SIZE") == "65536"
    assert _read_env_value(env, "ARIA_VLLM_QUANT") == "gptq"
    # Small-GPU advisory emitted when voice or docling CUDA is enabled.
    assert small_gpu_warning(hw, voice_enabled=False) is not None


def test_small_gpu_warning_suppressed_at_threshold() -> None:
    # 12288 MB is the boundary; warn only below it.
    assert small_gpu_warning(_hw(12288), voice_enabled=True) is None
    assert small_gpu_warning(_hw(12287), voice_enabled=True) is not None


def test_small_gpu_warning_none_without_gpu() -> None:
    assert small_gpu_warning(_hw(0), voice_enabled=False) is None


# ---------------------------------------------------------------------------
# Re-run: user values never overwritten
# ---------------------------------------------------------------------------


def test_rerun_preserves_user_chat_model_path(monkeypatch, tmp_path: Path) -> None:
    env = _copy_template_env(tmp_path)
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    # First run writes the tier default.
    apply_mode_to_env(
        env, CHAT_MODE_LOCAL, _hw(24576), FeatureChoices(vision=True, voice=True)
    )
    # User customizes CHAT_MODEL_PATH by hand.
    from aria.helpers.dotenv import parse_dotenv, write_dotenv

    values, raw = parse_dotenv(env)
    values["CHAT_MODEL_PATH"] = "my-org/my-custom-model"
    write_dotenv(env, values, raw)
    # Second run must NOT overwrite the user's value.
    changed = apply_mode_to_env(
        env, CHAT_MODE_LOCAL, _hw(24576), FeatureChoices(vision=True, voice=True)
    )
    assert _read_env_value(env, "CHAT_MODEL_PATH") == "my-org/my-custom-model"
    assert "CHAT_MODEL_PATH" not in changed


def test_rerun_preserves_user_vision_choice(monkeypatch, tmp_path: Path) -> None:
    env = _copy_template_env(tmp_path)
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    # User explicitly set vision off.
    from aria.helpers.dotenv import parse_dotenv, write_dotenv

    values, raw = parse_dotenv(env)
    values["ARIA_VLLM_VISION_ENABLED"] = "false"
    write_dotenv(env, values, raw)
    # Re-run with a different stated choice must NOT overwrite the user's value.
    changed = apply_mode_to_env(
        env, CHAT_MODE_LOCAL, _hw(24576), FeatureChoices(vision=True, voice=True)
    )
    assert _read_env_value(env, "ARIA_VLLM_VISION_ENABLED") == "false"
    assert "ARIA_VLLM_VISION_ENABLED" not in changed


def test_rerun_preserves_user_voice_choice(monkeypatch, tmp_path: Path) -> None:
    env = _copy_template_env(tmp_path)
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    from aria.helpers.dotenv import parse_dotenv, write_dotenv

    values, raw = parse_dotenv(env)
    values["ARIA_VOICE_ENABLED"] = "true"
    write_dotenv(env, values, raw)
    changed = apply_mode_to_env(
        env, CHAT_MODE_LOCAL, _hw(24576), FeatureChoices(voice=False)
    )
    assert _read_env_value(env, "ARIA_VOICE_ENABLED") == "true"
    assert "ARIA_VOICE_ENABLED" not in changed


# ---------------------------------------------------------------------------
# config.toml accept/image round-trip via sync_chainlit_features
# ---------------------------------------------------------------------------


def _copy_template_chainlit(tmp_path: Path) -> Path:
    with as_file(files("aria").joinpath(".chainlit", "config.toml")) as src:
        dest = tmp_path / ".chainlit" / "config.toml"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(), encoding="utf-8")
    return dest


def _accept_image_count(text: str) -> int:
    import re

    block = re.search(
        r"\[features\.spontaneous_file_upload\](.*?)(?=\n\[|\Z)",
        text,
        re.DOTALL,
    )
    assert block is not None
    return len(re.findall(r'"image/', block.group(1)))


def test_config_vision_off_strips_images_then_restores(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    config = _copy_template_chainlit(tmp_path)
    from aria.server.manager import sync_chainlit_features

    sync_chainlit_features(tmp_path, vision_enabled=False)
    assert _accept_image_count(config.read_text()) == 0
    # Round-trip: re-enabling vision restores the image MIME block.
    sync_chainlit_features(tmp_path, vision_enabled=True)
    assert _accept_image_count(config.read_text()) == 6


def test_config_preserves_user_edits_elsewhere(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    config = _copy_template_chainlit(tmp_path)
    text = config.read_text()
    # Simulate a user customization in an unrelated section.
    text = text.replace('name = "Aria"', 'name = "My Assistant"')
    config.write_text(text, encoding="utf-8")
    from aria.server.manager import sync_chainlit_features

    sync_chainlit_features(tmp_path, vision_enabled=False)
    after = config.read_text()
    assert 'name = "My Assistant"' in after  # user edit survived
    assert _accept_image_count(after) == 0


# ---------------------------------------------------------------------------
# vision_enabled_for_config
# ---------------------------------------------------------------------------


def test_vision_enabled_for_config_local_requires_gpu() -> None:
    # Local mode: vision needs a local GPU even when the user opted in.
    assert (
        vision_enabled_for_config(
            _hw(24576), CHAT_MODE_LOCAL, FeatureChoices(vision=True)
        )
        is True
    )
    assert (
        vision_enabled_for_config(_hw(0), CHAT_MODE_LOCAL, FeatureChoices(vision=True))
        is False
    )


def test_vision_enabled_for_config_remote_is_user_choice() -> None:
    assert (
        vision_enabled_for_config(_hw(0), CHAT_MODE_REMOTE, FeatureChoices(vision=True))
        is True
    )
    assert (
        vision_enabled_for_config(
            _hw(0), CHAT_MODE_REMOTE, FeatureChoices(vision=False)
        )
        is False
    )
