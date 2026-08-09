"""PDF conversion backend configuration.

Reuses the lazy descriptor and model-path resolver from
:mod:`aria.config.models` so env vars are not read at import time.
"""

from pathlib import Path

from aria.config import get_optional_env
from aria.config.folders import Venvs
from aria.config.models import _Lazy, _resolve_model_path


class Pdf:
    """PDF conversion backend settings (lazy, env-driven)."""

    backend = _Lazy(
        lambda: get_optional_env("ARIA_PDF_BACKEND", "auto").lower()
    )  # "auto" | "granite-docling" | "markitdown"

    vlm_model_id = _Lazy(
        lambda: get_optional_env(
            "ARIA_PDF_VLM_MODEL", "ibm-granite/granite-docling-258M"
        )
    )

    vlm_device = _Lazy(
        lambda: get_optional_env("ARIA_PDF_VLM_DEVICE", "auto").lower()
    )  # "auto" | "cpu" | "cuda" | "mps"

    vlm_max_pages = _Lazy(
        lambda: int(get_optional_env("ARIA_PDF_VLM_MAX_PAGES", "200"))
    )

    vlm_timeout_seconds = _Lazy(
        lambda: int(get_optional_env("ARIA_PDF_VLM_TIMEOUT_SECONDS", "600"))
    )

    max_file_mb = _Lazy(lambda: int(get_optional_env("ARIA_PDF_MAX_FILE_MB", "100")))

    model_path = _Lazy(
        lambda: _resolve_model_path(get_optional_env("ARIA_PDF_VLM_MODEL_PATH", ""))
    )


class PdfVlm:
    """Isolated pdf-vlm venv resolution (mirrors :class:`Vllm`)."""

    @classmethod
    def get_venv_path(cls) -> Path:
        override = get_optional_env("ARIA_PDF_VLM_VENV", "")
        if override:
            return Path(override).expanduser().resolve()
        return Venvs.pdf_vlm

    @classmethod
    def is_externally_managed_venv(cls) -> bool:
        return bool(get_optional_env("ARIA_PDF_VLM_VENV", ""))

    @classmethod
    def get_python_executable(cls) -> Path:
        return cls.get_venv_path() / "bin" / "python"

    @classmethod
    def get_site_packages(cls) -> Path | None:
        hits = sorted(cls.get_venv_path().glob("lib/python3.*/site-packages"))
        return hits[-1] if hits else None
