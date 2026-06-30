"""Guard test: Aria's venv must not carry unused CUDA wheels.

Aria pins torch to the CPU wheel via the ``[tool.uv]`` pytorch-cpu index in
``pyproject.toml`` (embeddings run on CPU; vLLM owns the GPU stack in its
isolated venv). This test asserts no ``nvidia-*``/``cuda-*``/``triton``
packages leak into Aria's own venv, guarding against a future dependency
reintroducing the multi-GB CUDA stack silently.

Skipped when ``UV_TORCH_BACKEND`` is not ``cpu`` (e.g. a developer who
intentionally synced a CUDA torch backend for GPU embeddings).
"""

import importlib.util
import os

import pytest

_CUDA_PKGS = (
    "nvidia.cuda_runtime",
    "nvidia.cudnn",
    "nvidia.nccl",
    "nvidia.cusparse_lt",
    "nvidia_nvshmem",
    "cuda.bindings",
    "cuda_toolkit",
    "triton",
)


def _is_installed(pkg: str) -> bool:
    """Return True if *pkg* is importable (find_spec raises on missing parent)."""
    try:
        return importlib.util.find_spec(pkg) is not None
    except ModuleNotFoundError:
        return False


@pytest.mark.skipif(
    os.environ.get("UV_TORCH_BACKEND", "cpu") != "cpu",
    reason="CUDA torch backend explicitly requested",
)
def test_no_cuda_packages_in_aria_venv():
    """No nvidia-/cuda-/triton packages should be installed in Aria's venv."""
    leaked = [pkg for pkg in _CUDA_PKGS if _is_installed(pkg)]
    assert not leaked, (
        f"CUDA packages found in Aria's venv (should be CPU-only): {leaked}. "
        "Aria pins CPU torch via [tool.uv] pytorch-cpu index; vLLM's GPU "
        "stack lives in its isolated venv (~/.aria/venvs/vllm)."
    )
