"""Tests for the wizard deps-page check filtering (S7)."""

from __future__ import annotations

from types import SimpleNamespace

from aria.gui.wizard.deps_page import _DependenciesPage


def _hw(vram: int):
    from aria.bootstrap.detect import HardwareProfile

    return HardwareProfile(
        has_nvidia_gpu=vram > 0,
        has_rocm=False,
        cuda_version="12.8" if vram > 0 else "",
        vram_mb=vram,
        platform="nvidia" if vram > 0 else "cpu",
    )


def _check(name: str):
    return SimpleNamespace(name=name)


def test_no_gpu_hides_voice_check_row() -> None:
    """Preflight emits a literal 'voice' check (disabled state) even without
    a GPU — the no-GPU hide must cover that name, not just whisper/kokoro."""
    assert (
        _DependenciesPage._should_show_check(_check("voice"), _hw(0), remote=False)
        is False
    )
    assert (
        _DependenciesPage._should_show_check(
            _check("whisper.cpp model"), _hw(0), remote=False
        )
        is False
    )
    assert (
        _DependenciesPage._should_show_check(_check("kokoro TTS"), _hw(0), remote=True)
        is False
    )


def test_gpu_keeps_voice_check_row() -> None:
    assert (
        _DependenciesPage._should_show_check(_check("voice"), _hw(24576), remote=False)
        is True
    )
    assert (
        _DependenciesPage._should_show_check(
            _check("whisper.cpp model"), _hw(24576), remote=False
        )
        is True
    )


def test_optional_installable_check_offers_download_but_does_not_block() -> None:
    """A missing-but-warning check (docling) offers a Download and stays
    skippable: show=True, block=False."""
    block, show = _DependenciesPage._install_shown(
        "docling",
        SimpleNamespace(name="docling worker", passed=True, warning=True),
    )
    assert show is True
    assert block is False


def test_missing_hard_requirement_blocks_and_offers_download() -> None:
    block, show = _DependenciesPage._install_shown(
        "vllm", SimpleNamespace(name="vLLM package", passed=False)
    )
    assert show is True
    assert block is True


def test_clean_pass_offers_no_download() -> None:
    block, show = _DependenciesPage._install_shown(
        "docling", SimpleNamespace(name="docling worker", passed=True, warning=False)
    )
    assert show is False
    assert block is False


def test_unknown_target_offers_no_download() -> None:
    block, show = _DependenciesPage._install_shown(
        None, SimpleNamespace(name="docling worker", passed=False, warning=True)
    )
    assert show is False
    assert block is False


def test_icon_for_fail() -> None:
    assert (
        _DependenciesPage._icon_for(
            SimpleNamespace(name="x", passed=False, warning=False, informational=False)
        )
        == "❌"
    )


def test_icon_for_warning() -> None:
    assert (
        _DependenciesPage._icon_for(
            SimpleNamespace(name="x", passed=True, warning=True, informational=False)
        )
        == "⚠️"
    )


def test_icon_for_informational() -> None:
    assert (
        _DependenciesPage._icon_for(
            SimpleNamespace(
                name="voice", passed=True, warning=False, informational=True
            )
        )
        == "ℹ️"
    )


def test_icon_for_pass() -> None:
    assert (
        _DependenciesPage._icon_for(
            SimpleNamespace(name="x", passed=True, warning=False, informational=False)
        )
        == "✅"
    )


def _vc(name: str, passed: bool, warning: bool = False):
    return SimpleNamespace(
        name=name, passed=passed, warning=warning, informational=False
    )


def test_voice_rows_collapse_to_one_labeled_row() -> None:
    """The 4 voice preflight rows share the single "voice" install target
    (whisper + kokoro together) — they must collapse to one row labeled
    for what the Download actually installs, not 4 whisper/kokoro rows."""
    checks = [
        _vc("whisper.cpp (STT)", passed=False),
        _vc("whisper.cpp model", passed=True),
        _vc("kokoro TTS", passed=True),
        _vc("kokoro-tts tool", passed=True),
    ]
    rows = _DependenciesPage._group_rows(checks)
    assert len(rows) == 1
    assert rows[0].name == _DependenciesPage._VOICE_ROW
    assert "whisper" in rows[0].name and "kokoro" in rows[0].name
    assert rows[0].passed is False  # the failing row drives the merged state


def test_voice_group_all_present_is_single_pass_row() -> None:
    checks = [
        _vc("whisper.cpp (STT)", passed=True),
        _vc("kokoro TTS", passed=True),
    ]
    rows = _DependenciesPage._group_rows(checks)
    assert len(rows) == 1
    assert rows[0].passed is True
    assert rows[0].name == _DependenciesPage._VOICE_ROW


def test_non_voice_rows_untouched_by_grouping() -> None:
    checks = [
        _vc("lightpanda", passed=True),
        _vc("docling worker", passed=True, warning=True),
    ]
    rows = _DependenciesPage._group_rows(checks)
    assert rows == checks  # no voice target → unchanged


def test_voice_row_resolves_to_voice_target() -> None:
    """The merged voice row must still map to the "voice" install target."""
    assert _DependenciesPage._resolve_target(_DependenciesPage._VOICE_ROW) == "voice"


def test_target_labels_match_install_action() -> None:
    """Every installable target has a human label; the voice label names
    both components so the progress text can't say "downloading whisper"
    while kokoro installs too."""
    for target in ("lightpanda", "vllm", "chat", "embeddings", "docling", "voice"):
        assert target in _DependenciesPage._TARGET_LABELS
    voice_label = _DependenciesPage._TARGET_LABELS["voice"]
    assert "whisper" in voice_label and "kokoro" in voice_label
