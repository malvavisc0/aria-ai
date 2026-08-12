"""Download and manage voice assistant binaries (whisper.cpp + kokoro-tts).

Mirrors ``scripts/lightpanda.py``: a prebuilt binary (plus libraries)
fetched from GitHub releases, and a GGUF model file. kokoro-tts is
installed via ``uv tool install`` into an isolated uv tool env (like
vLLM's separated venv), with its model files fetched separately to
``~/.aria/models/kokoro``.
"""

import platform
import stat
import subprocess
import tarfile
from pathlib import Path

from loguru import logger
from rich.console import Console

from aria.config.folders import Bin, Models
from aria.scripts.lightpanda import _download_file

console = Console(width=200)

_WHISPER_REPO = "ggml-org/whisper.cpp"
_WHISPER_VERSION = "v1.9.2"
_WHISPER_RELEASES = f"https://github.com/{_WHISPER_REPO}/releases/download"
_WHISPER_MODEL_BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"
_KOKORO_RELEASES = "https://github.com/nazdridoy/kokoro-tts/releases/download/v1.0.0"

# Aria's own GitHub releases (where we host the CUDA build).
_ARIA_RELEASES = "https://github.com/malvavisc0/aria-ai/releases/download"

# CUDA minimum driver version (matches CUDA 12.6 toolkit requirement).
_MIN_CUDA_VERSION_FOR_GPU = (12, 6)


def download_whisper_cpp(model: str = "base.en") -> Path:
    """Fetch the whisper.cpp server binary plus the GGUF model.

    Detects the hardware and downloads the appropriate build:
    - NVIDIA GPU + compatible CUDA driver -> static CUDA build from
      Aria's GitHub releases (GPU-accelerated, ~75-95x faster STT).
    - No NVIDIA GPU -> official CPU prebuilt from whisper.cpp releases.

    Args:
        model: HuggingFace GGUF model name (e.g. ``base.en``).

    Returns:
        The whisper-server binary path.

    Raises:
        RuntimeError: On download failure or unsupported platform.
    """
    Bin.path.mkdir(parents=True, exist_ok=True)

    target = _detect_whisper_target()
    url = _whisper_download_url(target)
    asset_name = url.rsplit("/", 1)[-1]
    archive = Bin.path / asset_name

    console.print(f"[cyan]Downloading[/cyan] whisper-server ({target} build)...")
    _download_file(url, archive)

    dest_dir = Bin.path / "whisper-cpp"
    dest_dir.mkdir(parents=True, exist_ok=True)
    binary = _extract_whisper_binary(archive, dest_dir)
    if platform.system() != "Windows":
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Tag the build type for status reporting.
    (dest_dir / ".build_type").write_text(target)

    # Fetch the GGUF model from HuggingFace into ~/.aria/models.
    Models.path.mkdir(parents=True, exist_ok=True)
    model_path = Models.path / f"ggml-{model}.bin"
    console.print(f"[cyan]Downloading[/cyan] model ggml-{model}.bin...")
    _download_file(f"{_WHISPER_MODEL_BASE}/ggml-{model}.bin", model_path)

    console.print(f"[green]✓[/green] whisper.cpp ({target}) installed at {binary}")
    return binary


def download_kokoro() -> Path:
    """Install kokoro-tts via ``uv tool install`` and fetch its model files.

    Returns:
        The kokoro model directory.

    Raises:
        RuntimeError: On install or download failure.
    """
    kokoro_dir = Models.path / "kokoro"
    kokoro_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Installing kokoro-tts (isolated uv tool env)")
    subprocess.run(
        ["uv", "tool", "install", "--python", "3.12", "kokoro-tts"],
        check=True,
    )

    for fname in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
        console.print(f"[cyan]Downloading[/cyan] {fname}...")
        _download_file(f"{_KOKORO_RELEASES}/{fname}", kokoro_dir / fname)

    from aria.config.api import Voice

    python_exe = Voice.get_kokoro_python()
    if python_exe is not None:
        console.print(f"[green]✓[/green] kokoro-tts interpreter: {python_exe}")
    console.print(f"[green]✓[/green] kokoro-tts model installed at {kokoro_dir}")
    return kokoro_dir


def _detect_whisper_target() -> str:
    """Detect which whisper.cpp build to download for this system.

    Returns one of:
        - "cuda"  — NVIDIA GPU with a compatible CUDA driver
        - "cpu"   — no NVIDIA GPU, or CUDA driver too old

    Raises:
        RuntimeError: On non-Linux platforms (no prebuilt available).
    """
    system = platform.system().lower()

    if system != "linux":
        raise RuntimeError(
            f"No prebuilt whisper.cpp binary for {system}. "
            "Only Linux is supported by 'aria voice download'; build "
            "whisper.cpp from source on other platforms."
        )

    try:
        from aria.helpers.nvidia import get_cuda_version, get_total_vram_mb

        if get_total_vram_mb() > 0:
            cuda_ver = get_cuda_version()
            if cuda_ver:
                major, minor = cuda_ver.split(".", 1)
                if (int(major), int(minor)) >= _MIN_CUDA_VERSION_FOR_GPU:
                    return "cuda"
                logger.warning(
                    f"CUDA {cuda_ver} detected but whisper GPU build "
                    f"requires >= {_MIN_CUDA_VERSION_FOR_GPU[0]}."
                    f"{_MIN_CUDA_VERSION_FOR_GPU[1]}; "
                    "falling back to CPU build"
                )
    except Exception as exc:
        logger.debug(f"NVIDIA detection failed: {exc}")
    return "cpu"


def _whisper_download_url(target: str) -> str:
    """Resolve the whisper-server download URL for a build target.

    - "cuda": static CUDA build from Aria's GitHub releases
    - "cpu":  official CPU prebuilt from whisper.cpp releases
    """
    if target == "cuda":
        from aria import __version__

        return f"{_ARIA_RELEASES}/v{__version__}/whisper-server-cuda-12.6-x86_64.tar.gz"
    # CPU prebuilt from official whisper.cpp releases
    machine = platform.machine().lower()
    if any(tok in machine for tok in ("aarch64", "arm64")):
        asset = "whisper-bin-ubuntu-arm64.tar.gz"
    else:
        asset = "whisper-bin-ubuntu-x64.tar.gz"
    return f"{_WHISPER_RELEASES}/{_WHISPER_VERSION}/{asset}"


def _extract_whisper_binary(archive: Path, dest_dir: Path) -> Path:
    """Extract the whisper bundle and return the ``whisper-server`` executable.

    whisper.cpp bundles a ``whisper-server`` executable plus the shared
    libraries (``libggml*.so``) it loads from its own directory, so the
    whole archive is extracted rather than a single file.

    Args:
        archive: The downloaded tarball.
        dest_dir: Directory to extract into.

    Returns:
        The path to the extracted whisper-server binary.

    Raises:
        RuntimeError: If no binary is found in the archive.
    """
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(dest_dir, filter="data")
    except (tarfile.TarError, OSError) as e:
        raise RuntimeError(f"Failed to extract whisper.cpp archive: {e}") from e

    for candidate in dest_dir.rglob("whisper-server"):
        if candidate.is_file():
            return candidate

    raise RuntimeError("whisper-server binary not found in downloaded archive")
