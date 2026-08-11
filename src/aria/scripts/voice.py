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


def download_whisper_cpp(model: str = "small.en") -> Path:
    """Fetch the whisper.cpp server binary plus the GGUF model.

    Downloads the prebuilt CPU binary from the whisper.cpp GitHub releases.
    The Linux bundle ships its own ``libggml*.so`` libraries, so it works on
    any glibc-based Linux (Arch, Ubuntu, Fedora, …), not just Ubuntu. For GPU
    acceleration (CUDA/OpenVINO/ROCm), build whisper.cpp from source — no
    Linux GPU prebuilts are published.

    Args:
        model: HuggingFace GGUF model name (e.g. ``small.en``).

    Returns:
        The whisper-server binary path.

    Raises:
        RuntimeError: On download failure or unsupported platform.
    """
    Bin.path.mkdir(parents=True, exist_ok=True)

    asset_name = _whisper_platform_asset()
    url = f"{_WHISPER_RELEASES}/{_WHISPER_VERSION}/{asset_name}"
    archive = Bin.path / asset_name
    console.print(f"[cyan]Downloading[/cyan] {asset_name}...")
    _download_file(url, archive)

    dest_dir = Bin.path / "whisper-cpp"
    dest_dir.mkdir(parents=True, exist_ok=True)
    binary = _extract_whisper_binary(archive, dest_dir)
    if platform.system() != "Windows":
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Fetch the GGUF model from HuggingFace into ~/.aria/models.
    Models.path.mkdir(parents=True, exist_ok=True)
    model_path = Models.path / f"ggml-{model}.bin"
    console.print(f"[cyan]Downloading[/cyan] model ggml-{model}.bin...")
    _download_file(f"{_WHISPER_MODEL_BASE}/ggml-{model}.bin", model_path)

    console.print(f"[green]✓[/green] whisper.cpp installed at {binary}")
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


def _whisper_platform_asset() -> str:
    """Map platform.system()/machine() to a whisper.cpp release asset name.

    whisper.cpp publishes prebuilt CPU bundles for Linux (x64/arm64) and
    Windows. The Linux bundle ships its own ``libggml*.so`` libraries, so it
    runs on any glibc-based Linux (Arch, Ubuntu, Fedora, …), not just the
    Ubuntu it was built on. No Linux GPU prebuilts (CUDA/OpenVINO/ROCm)
    exist — build from source for GPU acceleration.

    Returns:
        The release asset filename.

    Raises:
        RuntimeError: If the platform has no prebuilt asset.
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":
        if any(tok in machine for tok in ("aarch64", "arm64")):
            return "whisper-bin-ubuntu-arm64.tar.gz"
        return "whisper-bin-ubuntu-x64.tar.gz"

    raise RuntimeError(
        f"No prebuilt whisper.cpp binary for {system}-{machine}. "
        "Only Linux is supported by 'aria voice download'; build "
        "whisper.cpp from source on other platforms."
    )


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
