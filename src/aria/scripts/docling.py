"""Granite-Docling worker installation and detection utilities.

The docling stack (docling + docling-ibm-models + torch + transformers)
is an external tool: installed into an isolated venv at
``~/.aria/venvs/docling`` and invoked as a subprocess. Aria's own
dependency tree never imports these packages.
"""

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from aria.config.folders import Bin
from aria.config.pdf import DoclingVenv
from aria.helpers.nvidia import get_cuda_version, pypi_torch_supports_cuda
from aria.scripts.vllm import _create_venv  # reuse the venv builder

# Heavy deps installed into the isolated venv (immutable — never mutate).
_PACKAGES: tuple[str, ...] = (
    "docling",
    "docling-ibm-models",
    "pypdfium2",  # page-count pre-check
)

_EXTRA_INDEX = "https://download.pytorch.org/whl/"

# CUDA 13+ ships CUDA-13 torch wheels on PyPI by default (same as
# scripts/vllm.py); only CUDA 12.x needs the cu126 extra index.
_CUDA13_INDEX: str | None = None


@lru_cache(maxsize=1)
def detect_device() -> str:
    """Resolve the inference device: ``"cuda"`` if NVIDIA, else ``"cpu"``.

    Cached per process — the GPU presence rarely changes during a session.
    Cheap: shells out to ``nvidia-smi`` at most (no torch import),
    matching ``scripts/vllm.py``'s contract. ROCm/Intel iGPU fall through
    to ``"cpu"``.
    """
    if get_cuda_version():
        return "cuda"
    return "cpu"


def _find_worker_dist_info() -> Path | None:
    sp = DoclingVenv.get_site_packages()
    if not sp or not sp.is_dir():
        return None
    return next(iter(sp.glob("docling-*.dist-info")), None)


def is_installed() -> bool:
    """Pure filesystem check — no subprocess, no torch import.

    Mirrors ``is_vllm_installed`` (scripts/vllm.py).
    """
    return (
        DoclingVenv.get_python_executable().exists()
        and _find_worker_dist_info() is not None
    )


def _resolve_torch_index() -> str | None:
    """PyTorch wheel index URL for the detected CUDA version.

    CUDA 13+ uses PyPI's default torch wheels (which bundle the CUDA 13
    runtime), so no extra index is needed.  CUDA 12.6+ uses the cu126
    index.  CPU-only systems use the cpu index to avoid pulling the
    multi-GB CUDA stack.
    """
    if detect_device() != "cuda":
        return _EXTRA_INDEX + "cpu"
    if pypi_torch_supports_cuda(get_cuda_version()):
        return _CUDA13_INDEX  # PyPI default = CUDA 13 torch
    return _EXTRA_INDEX + "cu126"


def _make_shim(venv: Path) -> Path:
    """Create/refresh the ``~/.aria/bin/docling`` shim.

    Prefers a symlink to ``<venv>/bin/docling``; falls back to a shell
    wrapper on filesystems without symlink support.
    """
    Bin.path.mkdir(parents=True, exist_ok=True)
    shim = Bin.path / "docling"
    target = venv / "bin" / "docling"
    if shim.exists() or shim.is_symlink():
        shim.unlink()
    try:
        shim.symlink_to(target)
    except OSError:  # filesystem without symlink support
        shim.write_text(f'#!/bin/sh\nexec "{target}" "$@"\n')
        shim.chmod(0o755)
    return shim


def install_docling() -> None:
    """Build the isolated docling venv + install worker + create shim.

    Uses ``detect_device()`` to pick the torch wheel: CPU torch from the
    pytorch-cpu index when no GPU, or the cu126 index when CUDA is
    detected. ``--no-config`` isolates the install from Aria's own
    [tool.uv] (mirrors scripts/vllm.py).
    """
    if DoclingVenv.is_externally_managed_venv():
        raise RuntimeError(
            "docling venv is externally managed via ARIA_DOCLING_VENV "
            f"({DoclingVenv.get_venv_path()}). Aria will not create or overwrite it. "
            "Unset ARIA_DOCLING_VENV to use Aria's managed install."
        )
    venv = DoclingVenv.get_venv_path()
    _create_venv(venv)
    py = DoclingVenv.get_python_executable()

    # Editable install of the worker package + heavy runtime deps.
    worker_src = Path(__file__).resolve().parents[2] / "docling"
    cmd = [
        "uv",
        "--no-config",
        "pip",
        "install",
        "--python",
        str(py),
        "-e",
        str(worker_src),
    ]
    cmd += [*_PACKAGES]
    # CUDA 13+: PyPI's default torch wheels are CUDA 13 builds, so no
    # extra index is needed.  CUDA 12.x / CPU: pin the index so the
    # correct torch variant wins (unsafe-best-match so the cu126/cpu
    # wheel actually beats PyPI's default-CUDA wheel).
    torch_index = _resolve_torch_index()
    if torch_index is not None:
        cmd += [
            "--extra-index-url",
            torch_index,
            "--index-strategy",
            "unsafe-best-match",
        ]
    subprocess.run(cmd, check=True)

    _make_shim(venv)


def uninstall_docling() -> None:
    if DoclingVenv.is_externally_managed_venv():
        raise RuntimeError("docling venv is externally managed; refusing to delete")
    venv = DoclingVenv.get_venv_path()
    if venv.is_dir():
        shutil.rmtree(venv)
    shim = Bin.path / "docling"
    if shim.exists() or shim.is_symlink():
        shim.unlink()
