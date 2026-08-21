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
