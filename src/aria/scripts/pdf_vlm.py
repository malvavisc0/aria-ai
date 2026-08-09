"""Granite-Docling (pdf-vlm) installation and detection utilities.

The pdf-vlm stack (docling + docling-ibm-models + torch + transformers)
is an external tool: installed into an isolated venv at
``~/.aria/venvs/pdf_vlm`` and invoked as a subprocess. Aria's own
dependency tree never imports these packages.
"""

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from aria.config.folders import Bin
from aria.config.pdf import PdfVlm
from aria.helpers.nvidia import get_cuda_version
from aria.scripts.vllm import _create_venv  # reuse the venv builder

# Heavy deps installed into the isolated venv (immutable — never mutate).
_PACKAGES: tuple[str, ...] = (
    "docling>=2.0,<3.0",
    "docling-ibm-models>=2.0",
    "pypdfium2",  # page-count pre-check
)

_EXTRA_INDEX = "https://download.pytorch.org/whl/"


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
    sp = PdfVlm.get_site_packages()
    if not sp or not sp.is_dir():
        return None
    return next(iter(sp.glob("aria_pdf_vlm-*.dist-info")), None)


def is_installed() -> bool:
    """Pure filesystem check — no subprocess, no torch import.

    Mirrors ``is_vllm_installed`` (scripts/vllm.py).
    """
    return (
        PdfVlm.get_python_executable().exists() and _find_worker_dist_info() is not None
    )


def _torch_wheel_target() -> str:
    """Pick the PyTorch wheel target for the detected device."""
    return "cu126" if detect_device() == "cuda" else "cpu"


def _make_shim(venv: Path) -> Path:
    """Create/refresh the ``~/.aria/bin/pdf-vlm`` shim.

    Prefers a symlink to ``<venv>/bin/pdf-vlm``; falls back to a shell
    wrapper on filesystems without symlink support.
    """
    Bin.path.mkdir(parents=True, exist_ok=True)
    shim = Bin.path / "pdf-vlm"
    target = venv / "bin" / "pdf-vlm"
    if shim.exists() or shim.is_symlink():
        shim.unlink()
    try:
        shim.symlink_to(target)
    except OSError:  # filesystem without symlink support
        shim.write_text(f'#!/bin/sh\nexec "{target}" "$@"\n')
        shim.chmod(0o755)
    return shim


def install_pdf_vlm() -> None:
    """Build the isolated pdf-vlm venv + install worker + create shim.

    Uses ``detect_device()`` to pick the torch wheel: CPU torch from the
    pytorch-cpu index when no GPU, or the cu126 index when CUDA is
    detected. ``--no-config`` isolates the install from Aria's own
    [tool.uv] (mirrors scripts/vllm.py).
    """
    if PdfVlm.is_externally_managed_venv():
        raise RuntimeError(
            "pdf-vlm venv is externally managed via ARIA_PDF_VLM_VENV "
            f"({PdfVlm.get_venv_path()}). Aria will not create or overwrite it. "
            "Unset ARIA_PDF_VLM_VENV to use Aria's managed install."
        )
    venv = PdfVlm.get_venv_path()
    _create_venv(venv)
    py = PdfVlm.get_python_executable()

    extra_index = _EXTRA_INDEX + _torch_wheel_target()

    # Editable install of the worker package + heavy runtime deps.
    worker_src = Path(__file__).resolve().parents[2] / "aria_pdf_vlm"
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
    cmd += ["--extra-index-url", extra_index, "--index-strategy", "unsafe-best-match"]
    subprocess.run(cmd, check=True)

    _make_shim(venv)


def uninstall_pdf_vlm() -> None:
    if PdfVlm.is_externally_managed_venv():
        raise RuntimeError("pdf-vlm venv is externally managed; refusing to delete")
    venv = PdfVlm.get_venv_path()
    if venv.is_dir():
        shutil.rmtree(venv)
    shim = Bin.path / "pdf-vlm"
    if shim.exists() or shim.is_symlink():
        shim.unlink()
