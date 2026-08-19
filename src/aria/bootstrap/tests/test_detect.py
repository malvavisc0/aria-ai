"""Tests for [`detect_hardware`](../detect.py)."""

from unittest.mock import patch

from aria.bootstrap.detect import HardwareProfile, detect_hardware


def _patch_nvidia(monkeypatch, *, vram: int, cuda: str) -> None:
    """Point the nvidia helpers at fixed values (None → empty string)."""
    import aria.helpers.nvidia as nv

    monkeypatch.setattr(nv, "get_total_vram_mb", lambda: vram)
    monkeypatch.setattr(nv, "get_cuda_version", lambda: cuda or "")
    # detect_hardware imports the names lazily inside its try block, so
    # also patch the lazy-import path used there.
    monkeypatch.setattr("aria.helpers.nvidia.get_total_vram_mb", lambda: vram)
    monkeypatch.setattr("aria.helpers.nvidia.get_cuda_version", lambda: cuda or "")


def test_detect_nvidia_gpu(monkeypatch) -> None:
    _patch_nvidia(monkeypatch, vram=24576, cuda="12.8")
    with patch("aria.bootstrap.detect._detect_rocm", return_value=False):
        profile = detect_hardware()
    assert profile.has_nvidia_gpu is True
    assert profile.vram_mb == 24576
    assert profile.cuda_version == "12.8"
    assert profile.platform == "nvidia"
    assert profile.has_rocm is False


def test_detect_no_gpu_cpu_platform(monkeypatch) -> None:
    _patch_nvidia(monkeypatch, vram=0, cuda="")
    with (
        patch("aria.bootstrap.detect._detect_rocm", return_value=False),
        patch("aria.bootstrap.detect.platform.system", return_value="Linux"),
    ):
        profile = detect_hardware()
    assert profile.has_nvidia_gpu is False
    assert profile.vram_mb == 0
    assert profile.cuda_version == ""
    assert profile.platform == "cpu"
    assert profile.has_rocm is False


def test_detect_rocm_reporting_only(monkeypatch) -> None:
    _patch_nvidia(monkeypatch, vram=0, cuda="")
    with (
        patch("aria.bootstrap.detect._detect_rocm", return_value=True),
        patch("aria.bootstrap.detect.platform.system", return_value="Linux"),
    ):
        profile = detect_hardware()
    # ROCm is reported but does not enable local chat (NVIDIA-only this iteration).
    assert profile.has_rocm is True
    assert profile.has_nvidia_gpu is False
    assert profile.platform == "cpu"


def test_detect_metal_platform(monkeypatch) -> None:
    _patch_nvidia(monkeypatch, vram=0, cuda="")
    import subprocess

    with (
        patch("aria.bootstrap.detect._detect_rocm", return_value=False),
        patch("aria.bootstrap.detect.platform.system", return_value="Darwin"),
        patch.object(subprocess, "check_output", return_value=b"arm64"),
    ):
        profile = detect_hardware()
    assert profile.platform == "metal"
    assert profile.has_nvidia_gpu is False


def test_detect_vram_tiers_preserved(monkeypatch) -> None:
    """VRAM is reported verbatim so tier boundaries (12288, 16384, 24576)
    resolve correctly downstream."""
    for vram in (0, 1, 8192, 12288, 16384, 24576):
        _patch_nvidia(monkeypatch, vram=vram, cuda="12.8")
        with patch("aria.bootstrap.detect._detect_rocm", return_value=False):
            assert detect_hardware().vram_mb == vram


def test_detect_never_raises_on_failure(monkeypatch) -> None:
    def _boom() -> int:
        raise RuntimeError("no nvidia-smi")

    monkeypatch.setattr("aria.helpers.nvidia.get_total_vram_mb", _boom)
    with patch("aria.bootstrap.detect._detect_rocm", return_value=False):
        profile = detect_hardware()
    assert (
        profile
        == HardwareProfile(
            has_nvidia_gpu=False,
            has_rocm=False,
            cuda_version="",
            vram_mb=0,
            platform="cpu",
        )
        or profile.has_nvidia_gpu is False
    )
