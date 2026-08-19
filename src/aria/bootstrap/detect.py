"""Hardware detection for ``aria init`` (NVIDIA-only).

Detection is intentionally **not** a compute-mode decision: hardware is an
independent axis from the chat-mode choice (see the plan's feature matrix).
``detect_hardware()`` is pure detection with no side effects; the mode
decision lives in ``aria.bootstrap.features``.
"""

from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HardwareProfile:
    """Detected hardware state (NVIDIA-only this iteration).

    Attributes:
        has_nvidia_gpu: True when an NVIDIA GPU with a working ``nvidia-smi``
            and non-zero total VRAM is present.
        has_rocm: True when an AMD ROCm stack is detected (reporting only —
            local chat is NVIDIA-only this iteration).
        cuda_version: CUDA driver version string (e.g. ``"12.8"``), or
            ``""`` when none.
        vram_mb: Total VRAM across all NVIDIA GPUs in MiB, 0 when none.
        platform: Compute platform label: ``"nvidia"`` | ``"metal"`` |
            ``"cpu"`` (mirrors
            ``aria.preflight.checks_hardware._detect_compute_platform``).
    """

    has_nvidia_gpu: bool
    has_rocm: bool
    cuda_version: str
    vram_mb: int
    platform: str


def _detect_rocm() -> bool:
    """True when an AMD ROCm stack appears present (reporting only)."""
    if shutil.which("rocm-smi") is not None:
        return True
    return Path("/opt/rocm").is_dir()


def _detect_platform(has_nvidia: bool) -> str:
    """Compute platform label, mirroring ``checks_hardware`` priority."""
    if has_nvidia:
        return "nvidia"
    if platform.system() == "Darwin":
        import subprocess

        try:
            arch = subprocess.check_output(
                ["uname", "-m"], stderr=subprocess.DEVNULL
            ).decode()
            if arch.strip() == "arm64":
                return "metal"
        except Exception:
            pass
    return "cpu"


def detect_hardware() -> HardwareProfile:
    """Detect the local hardware (NVIDIA CUDA + ROCm reporting only).

    Pure detection — no mode decisions, no side effects. Safe to call on
    any platform; never raises (detection failures yield a no-GPU profile).
    """
    cuda_version = ""
    vram_mb = 0
    has_nvidia = False
    try:
        from aria.helpers.nvidia import get_cuda_version, get_total_vram_mb

        vram_mb = get_total_vram_mb()
        has_nvidia = vram_mb > 0
        if has_nvidia:
            cuda_version = get_cuda_version()
    except Exception:
        pass

    return HardwareProfile(
        has_nvidia_gpu=has_nvidia,
        has_rocm=_detect_rocm(),
        cuda_version=cuda_version,
        vram_mb=vram_mb,
        platform=_detect_platform(has_nvidia),
    )
