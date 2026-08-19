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
