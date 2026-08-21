"""Tests for the wizard's finalize step — CLI/GUI parity (S9).

``_finalize_init`` must route through the same single ``.env`` writer as
``aria init`` (``apply_mode_to_env``): tier values, docling device,
vision/voice choices, and remote endpoint fields (carried on
``feature_choices()``), plus the config.toml sync and the marker.
"""

from __future__ import annotations

import json
from importlib.resources import as_file, files
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aria.bootstrap.features import FeatureChoices
from aria.gui.wizard.flow import _finalize_init, apply_features


def _hw(vram: int):
    from aria.bootstrap.detect import HardwareProfile

    return HardwareProfile(
        has_nvidia_gpu=vram > 0,
        has_rocm=False,
        cuda_version="12.8" if vram > 0 else "",
        vram_mb=vram,
        platform="nvidia" if vram > 0 else "cpu",
    )


def _page(mode: str, choices: FeatureChoices):
    """Duck-typed connection page — finalize only reads these two."""
    return SimpleNamespace(
        get_connection_mode=lambda: mode,
        feature_choices=lambda: choices,
    )


def _seed_aria_home(tmp_path: Path) -> None:
    with as_file(files("aria").joinpath(".env.example")) as src:
        (tmp_path / ".env").write_text(src.read_text(), encoding="utf-8")
    (tmp_path / ".chainlit").mkdir(parents=True, exist_ok=True)
    with as_file(files("aria").joinpath(".chainlit", "config.toml")) as src:
        (tmp_path / ".chainlit" / "config.toml").write_text(
            src.read_text(), encoding="utf-8"
        )


def _read_env(tmp_path: Path, key: str) -> str:
    from aria.helpers.dotenv import parse_dotenv

    values, _ = parse_dotenv(tmp_path / ".env")
    return values.get(key, "")


def _accept_image_count(tmp_path: Path) -> int:
    import re

    text = (tmp_path / ".chainlit" / "config.toml").read_text()
    block = re.search(
        r"\[features\.spontaneous_file_upload\](.*?)(?=\n\[|\Z)", text, re.DOTALL
    )
    assert block is not None
    return len(re.findall(r'"image/', block.group(1)))


def test_finalize_local_writes_tier_values(monkeypatch, tmp_path: Path) -> None:
    """Local mode on a small GPU: the 4B tier, context, quant, and docling
    device reach .env through the shared writer (the deps-page downloader
    then resolves the tier repo id — S8)."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _seed_aria_home(tmp_path)

    with patch("aria.bootstrap.detect.detect_hardware", return_value=_hw(8192)):
        _finalize_init(_page("local", FeatureChoices(vision=False, voice=True)))

    assert _read_env(tmp_path, "ARIA_VLLM_REMOTE") == "false"
    assert _read_env(tmp_path, "CHAT_MODEL_PATH") == "malvavisc0/Qwen3.8-4B-gptq-int4"
    assert _read_env(tmp_path, "CHAT_MODEL") == "Qwen3.8-4B-gptq-int4"
    assert _read_env(tmp_path, "CHAT_CONTEXT_SIZE") == "65536"
    assert _read_env(tmp_path, "ARIA_VLLM_QUANT") == "gptq"
    assert _read_env(tmp_path, "ARIA_DOCLING_DEVICE") == "auto"
    data = json.loads((tmp_path / ".init-completed.json").read_text())
    assert data["chat_mode"] == "local"
    assert data["tier"]["chat_model"] == "malvavisc0/Qwen3.8-4B-gptq-int4"


def test_finalize_persists_voice_checkbox_state(monkeypatch, tmp_path: Path) -> None:
    """Ticked voice + GPU → ARIA_VOICE_ENABLED=true; unticked → false."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _seed_aria_home(tmp_path)

    with patch("aria.bootstrap.detect.detect_hardware", return_value=_hw(24576)):
        _finalize_init(_page("local", FeatureChoices(vision=False, voice=True)))
    assert _read_env(tmp_path, "ARIA_VOICE_ENABLED") == "true"

    _seed_aria_home(tmp_path)
    with patch("aria.bootstrap.detect.detect_hardware", return_value=_hw(24576)):
        _finalize_init(_page("local", FeatureChoices(vision=False, voice=False)))
    assert _read_env(tmp_path, "ARIA_VOICE_ENABLED") == "false"


def test_finalize_persists_vision_checkbox_state(monkeypatch, tmp_path: Path) -> None:
    """Vision checkbox state persists to .env and drives the image-MIME sync."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _seed_aria_home(tmp_path)

    with patch("aria.bootstrap.detect.detect_hardware", return_value=_hw(24576)):
        _finalize_init(_page("local", FeatureChoices(vision=True, voice=False)))
    assert _read_env(tmp_path, "ARIA_VLLM_VISION_ENABLED") == "true"
    assert _accept_image_count(tmp_path) == 6

    _seed_aria_home(tmp_path)
    with patch("aria.bootstrap.detect.detect_hardware", return_value=_hw(24576)):
        _finalize_init(_page("local", FeatureChoices(vision=False, voice=False)))
    assert _read_env(tmp_path, "ARIA_VLLM_VISION_ENABLED") == "false"
    assert _accept_image_count(tmp_path) == 0


def test_finalize_remote_writes_endpoint_fields(monkeypatch, tmp_path: Path) -> None:
    """Remote mode: the mode switch + endpoint fields flow through
    feature_choices (one writer, same as the CLI flags path)."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _seed_aria_home(tmp_path)
    choices = FeatureChoices(
        vision=False,
        voice=False,
        remote_url="https://remote.example/v1",
        remote_api_key="sk-wizard",
        remote_model="gpt-4o",
    )

    with patch("aria.bootstrap.detect.detect_hardware", return_value=_hw(0)):
        _finalize_init(_page("remote", choices))

    assert _read_env(tmp_path, "ARIA_VLLM_REMOTE") == "true"
    assert _read_env(tmp_path, "CHAT_OPENAI_API") == "https://remote.example/v1"
    assert _read_env(tmp_path, "ARIA_VLLM_API_KEY") == "sk-wizard"
    assert _read_env(tmp_path, "CHAT_MODEL") == "gpt-4o"
    # No GPU → voice forced off, docling on CPU (Decision 5 / feature matrix).
    assert _read_env(tmp_path, "ARIA_VOICE_ENABLED") == "false"
    assert _read_env(tmp_path, "ARIA_DOCLING_DEVICE") == "cpu"
    data = json.loads((tmp_path / ".init-completed.json").read_text())
    assert data["chat_mode"] == "remote"
    assert data["tier"]["chat_model"] is None


def test_finalize_never_overwrites_user_chat_model_path(
    monkeypatch, tmp_path: Path
) -> None:
    """Never-overwrite contract (same as CLI init): a user-customized tier
    value in .env survives the wizard."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _seed_aria_home(tmp_path)
    from aria.helpers.dotenv import parse_dotenv, write_dotenv

    values, raw = parse_dotenv(tmp_path / ".env")
    values["CHAT_MODEL_PATH"] = "my-org/my-custom-model"
    write_dotenv(tmp_path / ".env", values, raw)

    with patch("aria.bootstrap.detect.detect_hardware", return_value=_hw(8192)):
        _finalize_init(_page("local", FeatureChoices()))

    assert _read_env(tmp_path, "CHAT_MODEL_PATH") == "my-org/my-custom-model"


def test_apply_features_makes_preflight_reflect_checkboxes(
    monkeypatch, tmp_path: Path
) -> None:
    """The deps page applies feature choices before preflight (CLI-parity
    order): ticking voice+vision on the connection page must flip
    ``Voice.enabled``/``Vllm.vision_enabled`` so preflight no longer shows
    the stale "Disabled" informational rows."""
    from aria.config.api import Vllm, Voice
    from aria.preflight import run_preflight_checks

    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _seed_aria_home(tmp_path)

    with patch("aria.bootstrap.detect.detect_hardware", return_value=_hw(24576)):
        apply_features(_page("local", FeatureChoices(vision=True, voice=True)))

    assert Voice.enabled is True
    assert Vllm.vision_enabled is True

    names = [c.name for c in run_preflight_checks().checks]
    assert "vision" in names
    # Voice enabled → the short-circuit "Disabled" row must NOT appear;
    # instead the whisper/kokoro install checks run.
    assert not any(
        c.name == "voice" and c.informational for c in run_preflight_checks().checks
    )
    assert "whisper.cpp (STT)" in names


def test_apply_features_disabled_keeps_informational_rows(
    monkeypatch, tmp_path: Path
) -> None:
    """Unticked voice+vision (GPU present) → the informational Disabled
    rows remain (no install offered)."""
    from aria.config.api import Vllm, Voice
    from aria.preflight import run_preflight_checks

    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    _seed_aria_home(tmp_path)

    with patch("aria.bootstrap.detect.detect_hardware", return_value=_hw(24576)):
        apply_features(_page("local", FeatureChoices(vision=False, voice=False)))

    assert Voice.enabled is False
    assert Vllm.vision_enabled is False
    checks = {c.name: c for c in run_preflight_checks().checks}
    assert checks["vision"].informational is True
    assert checks["voice"].informational is True
