"""vLLM installation and detection utilities.

vLLM is treated as an **external tool**: it is installed into an
isolated virtualenv (``~/.aria/venvs/vllm``) and launched as an
OpenAI-compatible server over HTTP.  Aria's own dependency tree never
imports vLLM — it only shells out to the isolated interpreter.

This module handles platform-specific installation (CUDA, ROCm, CPU)
by inspecting the system's GPU drivers, then builds the isolated venv
and a ``~/.aria/bin/vllm`` shim that points at it.

Example:
    ```python
    from aria.scripts.vllm import detect_install_target, install_vllm

    target = detect_install_target()
    print(f"Install target: {target}")  # "cu124", "rocm6", or "cpu"

    install_vllm()  # build isolated venv + shim
    ```
"""

import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

from loguru import logger
from rich.console import Console

from aria.config.api import Vllm
from aria.config.folders import Bin

console = Console(width=200)
error_console = Console(stderr=True, style="bold red", width=200)

# PyTorch wheel indexes per hardware target.  vLLM v0.20.0+ ships
# CUDA 13.0 wheels on PyPI by default, so no extra index is needed for
# CUDA 13+ (see :func:`_resolve_extra_index_url`).
PYTORCH_INDEX: dict[str, str] = {
    "cu126": "https://download.pytorch.org/whl/cu126",
    "cu124": "https://download.pytorch.org/whl/cu124",
    "cu121": "https://download.pytorch.org/whl/cu121",
    "cu118": "https://download.pytorch.org/whl/cu118",
    "rocm6": "https://download.pytorch.org/whl/rocm6",
}
PYPI_JSON = "https://pypi.org/pypi/vllm/json"


def _cuda_target_from_version(major: int, minor: int) -> str:
    """Map CUDA version to the highest compatible PyTorch wheel target."""
    if major >= 13 or (major == 12 and minor >= 6):
        return "cu126"
    if major == 12 and minor >= 4:
        return "cu124"
    if major == 12 and minor >= 1:
        return "cu121"
    if major == 11 and minor >= 8:
        return "cu118"
    return "cu126"  # Fallback to latest


def _detect_cuda_target() -> str | None:
    try:
        from aria.helpers.nvidia import get_cuda_version

        cuda_version = get_cuda_version()
    except Exception as exc:
        logger.debug(f"NVIDIA CUDA detection failed: {exc}")
        return None
    if not cuda_version:
        return None
    major_str, minor_str = cuda_version.split(".", 1)
    target = _cuda_target_from_version(int(major_str), int(minor_str))
    logger.info(f"CUDA {cuda_version} detected → {target} target")
    return target


def _detect_rocm_target() -> str | None:
    try:
        if shutil.which("rocm-smi") is not None:
            logger.info("rocm-smi found → rocm6 target")
            return "rocm6"
        if Path("/opt/rocm").is_dir():
            logger.info("/opt/rocm directory found → rocm6 target")
            return "rocm6"
    except Exception as exc:
        logger.debug(f"ROCm detection failed: {exc}")
    return None


def detect_install_target() -> str:
    """Detect the appropriate vLLM install target for this system.

    Priority:
        1. NVIDIA CUDA — detected via CUDA version from nvidia-smi
        2. AMD ROCm — detected via ``rocm-smi`` or ``/opt/rocm`` directory
        3. CPU fallback

    Returns:
        One of ``"cu126"``, ``"cu124"``, ``"cu121"``, ``"cu118"``,
        ``"rocm6"``, or ``"cpu"``.

    Example:
        ```python
        target = detect_install_target()
        # "cu126" on an NVIDIA system with CUDA 12.6+
        ```
    """
    cuda_target = _detect_cuda_target()
    if cuda_target:
        return cuda_target
    rocm_target = _detect_rocm_target()
    if rocm_target:
        return rocm_target
    logger.info("No GPU detected → cpu target")
    return "cpu"


# ---------------------------------------------------------------------------
# Detection (cheap; no torch import, no subprocess)
# ---------------------------------------------------------------------------


def _find_vllm_dist_info() -> Path | None:
    """Locate the ``vllm-*.dist-info`` directory in the isolated venv.

    Uses a filesystem glob (not an ``import vllm`` subprocess) so the
    check is cheap and safe to run on every preflight / status lookup.
    """
    sp = Vllm.get_site_packages()
    if not sp or not sp.is_dir():
        return None
    return next(iter(sp.glob("vllm-*.dist-info")), None)


def is_vllm_installed() -> bool:
    """Check whether vLLM is installed in the isolated venv.

    Returns:
        True if the isolated interpreter exists AND a ``vllm`` dist-info
        directory is present in its ``site-packages``.

    This is a pure filesystem check — it never imports torch or spawns a
    subprocess, so it stays cheap for use in preflight.
    """
    return Vllm.get_python_executable().exists() and _find_vllm_dist_info() is not None


def get_vllm_version() -> str:
    """Return the installed vLLM version string.

    Reads the version from the isolated venv's ``vllm-*.dist-info``
    directory name (same cheap path as :func:`is_vllm_installed`).

    Returns:
        Version string (e.g. ``"0.24.0"``), or ``""`` if not installed.
    """
    di = _find_vllm_dist_info()
    if di is None:
        return ""
    return di.name[len("vllm-") : -len(".dist-info")]


# ---------------------------------------------------------------------------
# Extra-index resolution (preserve CUDA-13 "no index" special case)
# ---------------------------------------------------------------------------


def _resolve_extra_index_url(target: str) -> str | None:
    """Resolve the PyTorch extra-index-url for an install target.

    CUDA 13+ uses the default PyPI wheels (vLLM v0.20.0+ ships CUDA 13
    wheels on PyPI), so no extra-index-url is needed in that case.
    """
    url = PYTORCH_INDEX.get(target)
    if target == "cu126" and url:
        try:
            from aria.helpers.nvidia import get_cuda_version

            cv = get_cuda_version()
            if cv and int(cv.split(".")[0]) >= 13:
                return None  # CUDA 13+ uses default PyPI wheels
        except Exception:
            pass  # keep cu126 extra-index-url as fallback
    return url


# ---------------------------------------------------------------------------
# venv + shim helpers
# ---------------------------------------------------------------------------


def _create_venv(venv: Path) -> None:
    """Create the isolated venv (prefer ``uv``, fallback to ``venv``).

    The venv is pinned to the same interpreter Aria runs on
    (``sys.executable``) so it always uses a vLLM-compatible Python
    version — ``uv``'s own interpreter discovery could otherwise pick a
    version (e.g. 3.13) that has no matching vLLM wheel.
    """
    venv.parent.mkdir(parents=True, exist_ok=True)
    if venv.exists():
        shutil.rmtree(venv)
    if shutil.which("uv"):
        subprocess.run(
            ["uv", "venv", "--python", sys.executable, str(venv)], check=True
        )
    else:
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)


def _make_shim(venv: Path) -> Path:
    """Create/refresh the ``~/.aria/bin/vllm`` shim.

    Prefers a symlink to ``<venv>/bin/vllm``; falls back to a tiny
    shell wrapper on filesystems that don't support symlinks.
    """
    Bin.path.mkdir(parents=True, exist_ok=True)
    shim = Bin.path / "vllm"
    target = venv / "bin" / "vllm"
    if shim.exists() or shim.is_symlink():
        shim.unlink()
    try:
        shim.symlink_to(target)
    except OSError:  # filesystem without symlink support
        shim.write_text(f'#!/bin/sh\nexec "{target}" "$@"\n')
        shim.chmod(0o755)
    return shim


# ---------------------------------------------------------------------------
# Install / uninstall / update
# ---------------------------------------------------------------------------


def install_vllm(
    version: str | None = None, extra_index_url: str | None = None
) -> None:
    """Build the isolated vLLM venv and install the pinned wheel.

    Creates ``Vllm.get_venv_path()`` (preferring ``uv venv``), installs
    the prebuilt PyPI wheel into it with the detected target's
    ``--extra-index-url``, then creates the ``~/.aria/bin/vllm`` shim.

    Args:
        version: Target vLLM version (default: :attr:`Vllm.version`).
        extra_index_url: Override the PyTorch extra-index-url.  When
            *None* (default), the URL is derived from
            :func:`detect_install_target`.

    Raises:
        RuntimeError: On macOS, or if pip/uv exits non-zero.

    Example:
        ```python
        install_vllm()  # auto-detect and install into isolated venv
        ```
    """
    # --- Platform guard: vLLM only supports Linux ---
    if sys.platform == "darwin":
        msg = (
            "vLLM is not supported on macOS. "
            "vLLM requires Linux with an NVIDIA or AMD GPU. "
            "To run vLLM, use a Linux machine or Docker."
        )
        error_console.print(f"[red]✗[/red] {msg}")
        raise RuntimeError(msg)

    # --- Guard: never create/destroy a user-provided venv ---
    if Vllm.is_externally_managed_venv():
        msg = (
            "vLLM venv is externally managed via ARIA_VLLM_VENV "
            f"({Vllm.get_venv_path()}). Aria will not create or overwrite it. "
            "Unset ARIA_VLLM_VENV to use Aria's managed install."
        )
        error_console.print(f"[red]✗[/red] {msg}")
        raise RuntimeError(msg)

    version = version or Vllm.version
    target = detect_install_target()
    if extra_index_url is None:
        extra_index_url = _resolve_extra_index_url(target)

    venv = Vllm.get_venv_path()
    console.print(
        f"[cyan]→[/cyan] Building isolated vLLM venv at [bold]{venv}[/bold] "
        f"(target={target}, version={version})..."
    )
    console.print(
        "[dim]This downloads several GB (torch + CUDA stack). "
        "Progress is streamed below; this can take several minutes.[/dim]"
    )

    _create_venv(venv)
    py = Vllm.get_python_executable()
    spec = f"vllm=={version}"

    if shutil.which("uv"):
        # `--no-config` isolates this install from Aria's own [tool.uv] (which
        # pins CPU torch for Aria's venv). vLLM needs the CUDA torch stack, so
        # it must resolve only against PyPI + the explicit --extra-index-url
        # below, never the pytorch-cpu index declared in pyproject.toml.
        cmd = ["uv", "--no-config", "pip", "install", "--python", str(py), spec]
        if extra_index_url:
            # unsafe-best-match so the CUDA-target torch wheel actually wins;
            # otherwise uv may pick the default-CUDA PyPI wheel.
            cmd += [
                "--extra-index-url",
                extra_index_url,
                "--index-strategy",
                "unsafe-best-match",
            ]
    else:
        cmd = [str(py), "-m", "pip", "install", spec]
        if extra_index_url:
            cmd += ["--extra-index-url", extra_index_url]

    logger.info(f"Installing vLLM (target={target}): {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        error_console.print(
            f"[red]✗[/red] vLLM installation failed (exit {exc.returncode})"
        )
        raise

    _make_shim(venv)
    # Verify the install via the shim.
    subprocess.run([str(Bin.path / "vllm"), "--version"], check=True)
    ver = get_vllm_version()
    console.print(f"[green]✓[/green] vLLM {ver} installed successfully")


def uninstall_vllm() -> None:
    """Remove the isolated vLLM venv and the ``~/.aria/bin/vllm`` shim.

    Refuses to delete a user-provided venv (``ARIA_VLLM_VENV``); only
    Aria's own managed venv is removed.
    """
    if Vllm.is_externally_managed_venv():
        msg = (
            "vLLM venv is externally managed via ARIA_VLLM_VENV "
            f"({Vllm.get_venv_path()}). Aria will not delete it."
        )
        error_console.print(f"[red]✗[/red] {msg}")
        raise RuntimeError(msg)
    venv = Vllm.get_venv_path()
    if venv.is_dir():
        shutil.rmtree(venv)
    shim = Bin.path / "vllm"
    if shim.exists() or shim.is_symlink():
        shim.unlink()


def get_latest_vllm_version() -> str | None:
    """Query PyPI for the newest vLLM release version.

    Returns:
        The latest version string, or ``None`` if the lookup fails
        (offline / network error) so callers can fall back to the pin.
    """
    try:
        with urlopen(PYPI_JSON, timeout=10) as r:
            return json.load(r)["info"]["version"]
    except Exception:
        return None  # offline → caller falls back


def update_vllm(version: str | None = None) -> None:
    """Recreate the isolated venv at a (newer) version.

    Recreating (rather than ``pip install -U``) is required so a
    torch/CUDA wheel change is applied cleanly with no stale
    transitive deps.

    Args:
        version: Explicit target version, or *None* to query PyPI for
            the latest release (falling back to :attr:`Vllm.version`
            when offline).
    """
    target = version or get_latest_vllm_version() or Vllm.version
    uninstall_vllm()  # recreate => clean torch swap
    install_vllm(version=target)


# ---------------------------------------------------------------------------
# Legacy (in-Aria-.venv) detection & cleanup
# ---------------------------------------------------------------------------


def detect_legacy_vllm() -> str | None:
    """Return the version of vLLM living in Aria's OWN interpreter, else None.

    Existing users (and dev machines after ``uv sync``) may still have
    ``vllm`` installed inside Aria's ``.venv`` from before the detach.
    That copy is now ignored (launch uses the isolated interpreter), so
    callers surface a one-line notice when this returns a version.
    """
    try:
        return importlib.metadata.version("vllm")
    except importlib.metadata.PackageNotFoundError:
        return None


def uninstall_legacy_vllm() -> None:
    """Purge a vLLM that predates the detach from Aria's own ``.venv``.

    Runs ``uv pip uninstall vllm`` (or ``pip uninstall``) against the
    active Aria environment to reclaim the multi-GB CUDA/torch stack.
    """
    cmd = (
        ["uv", "pip", "uninstall", "vllm"]
        if shutil.which("uv")
        else [sys.executable, "-m", "pip", "uninstall", "-y", "vllm"]
    )
    subprocess.run(cmd, check=False)
