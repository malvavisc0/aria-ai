"""Basic preflight checks: environment, storage, and binaries."""

import os

from aria.preflight.results import CheckResult

# Required environment variables for the application to start
REQUIRED_ENV_VARS = [
    "ARIA_DB_FILENAME",
    "CHROMADB_PERSISTENT_PATH",
    "CHAT_MODEL",
    "CHAT_MODEL_PATH",
    "EMBED_MODEL_PATH",
    "CHAT_OPENAI_API",
    "MAX_ITERATIONS",
    "TOKEN_LIMIT_RATIO",
    "EMBEDDINGS_MODEL",
    "CHAINLIT_AUTH_SECRET",
]


def _check_env_vars(checks: list[CheckResult]) -> None:
    """Check that all required environment variables are set."""
    from aria.config.api import Vllm as VllmConfig

    required = list(REQUIRED_ENV_VARS)
    if VllmConfig.remote:
        # CHAT_MODEL_PATH is not required in remote mode —
        # the model is served by the remote endpoint.
        required = [v for v in required if v != "CHAT_MODEL_PATH"]

    passed = sum(1 for var in required if os.getenv(var))
    total = len(required)

    if passed == total:
        checks.append(
            CheckResult(
                name="Environment variables",
                passed=True,
                category="environment",
                details=f"All {total} variables configured",
            )
        )
    else:
        for var in REQUIRED_ENV_VARS:
            if os.getenv(var):
                continue
            checks.append(
                CheckResult(
                    name=f"env:{var}",
                    passed=False,
                    category="environment",
                    error=f"'{var}' is not set",
                    hint=f"Add '{var}' to your .env file",
                )
            )


def _check_data_folder(checks: list[CheckResult]) -> None:
    """Check that the data folder exists."""
    from aria.config.folders import Data

    data_path = Data.path
    if data_path.exists():
        checks.append(
            CheckResult(
                name="Data folder",
                passed=True,
                category="storage",
                details=f"exists at {data_path}",
            )
        )
    else:
        checks.append(
            CheckResult(
                name="Data folder",
                passed=False,
                category="storage",
                error=f"does not exist: {data_path}",
                hint=f"Create the directory: mkdir -p {data_path}",
            )
        )


def _check_binaries(checks: list[CheckResult]) -> None:
    """Check that vLLM is installed (skipped in remote mode)."""
    from aria.config.api import Vllm as VllmConfig

    if VllmConfig.remote:
        checks.append(
            CheckResult(
                name="vLLM",
                passed=True,
                category="binaries",
                details="Remote mode — local install not required",
            )
        )
        return

    from aria.scripts.vllm import get_vllm_version, is_vllm_installed

    if is_vllm_installed():
        version = get_vllm_version()
        checks.append(
            CheckResult(
                name="vLLM",
                passed=True,
                category="binaries",
                details=f"v{version}",
            )
        )
    else:
        checks.append(
            CheckResult(
                name="vLLM",
                passed=False,
                category="binaries",
                error="vLLM is not installed",
                hint="Run: aria init  (or aria vllm install)",
            )
        )


def _check_lightpanda(checks: list[CheckResult]) -> None:
    """Check that Lightpanda is installed."""
    from aria.config.api import Lightpanda

    if Lightpanda.is_available():
        binary = Lightpanda.get_binary_path()
        checks.append(
            CheckResult(
                name="lightpanda",
                passed=True,
                category="binaries",
                details=f"Found at {binary}",
            )
        )
    else:
        checks.append(
            CheckResult(
                name="lightpanda",
                passed=False,
                category="binaries",
                error="Lightpanda is not installed",
                hint="Run: aria init  (or aria lightpanda download)",
            )
        )


def _check_docling(checks: list[CheckResult]) -> None:
    """Report the docling worker state.

    The Granite-Docling worker is required: the documents tool and the
    knowledge hub both need it for PDF conversion. The hub's
    ``_pdf_chunks`` raises a skip with reason ``docling_not_installed``
    when PDFs are present and the worker is missing, so silent fallback
    cannot happen.
    """
    from pathlib import Path

    from aria.config.models import _resolve_model_path
    from aria.config.pdf import Pdf
    from aria.scripts.docling import detect_device, is_installed

    if not is_installed():
        # Warning, not a failure: the app works without docling
        # (ARIA_PDF_BACKEND=auto degrades to "no PDF conversion").
        checks.append(
            CheckResult(
                name="docling worker",
                passed=True,
                category="binaries",
                details="not installed; run 'aria init' (or 'aria docling install') for PDF conversion",
                warning=True,
            )
        )
        return

    device = Pdf.vlm_device
    if device == "auto":
        device = detect_device()

    model_path = Pdf.model_path or _resolve_model_path(Pdf.vlm_model_id)
    model_cached = bool(model_path) and Path(model_path).is_dir()
    state = f"installed (device={device}, model_cached={model_cached})"
    if not model_cached:
        state += " — model downloads on first PDF conversion"
    checks.append(
        CheckResult(
            name="docling worker",
            passed=True,
            category="binaries",
            details=state,
        )
    )


def _check_voice(checks: list[CheckResult]) -> None:
    """Check that voice components (whisper.cpp STT + kokoro TTS) are installed.

    Both are required: the voice pipeline degrades to STT-only if TTS is
    missing, but STT alone still depends on the whisper binary. A missing
    whisper binary or kokoro tool/model is a hard preflight failure.

    Skipped entirely when voice is disabled via ``ARIA_VOICE_ENABLED=false``.
    """
    from aria.config.api import Voice

    if not Voice.enabled:
        checks.append(
            CheckResult(
                name="voice",
                passed=True,
                category="binaries",
                details="Disabled via ARIA_VOICE_ENABLED=false",
            )
        )
        return

    # Informational: tell the user if their hardware supports the CUDA build.
    from aria.scripts.voice import _detect_whisper_target

    try:
        target = _detect_whisper_target()
        if target == "cuda":
            checks.append(
                CheckResult(
                    name="whisper.cpp GPU",
                    passed=True,
                    category="binaries",
                    details="NVIDIA GPU detected — CUDA build available",
                )
            )
    except RuntimeError:
        pass  # non-Linux; skip

    whisper = Voice.get_whisper_binary_path()
    if whisper is not None:
        checks.append(
            CheckResult(
                name="whisper.cpp (STT)",
                passed=True,
                category="binaries",
                details=f"Found at {whisper}",
            )
        )
    else:
        checks.append(
            CheckResult(
                name="whisper.cpp (STT)",
                passed=False,
                category="binaries",
                error="whisper.cpp binary not installed",
                hint="Run: aria init  (or aria voice download)",
            )
        )

    whisper_model = Voice.get_whisper_model_path()
    if whisper_model.is_file():
        checks.append(
            CheckResult(
                name="whisper.cpp model",
                passed=True,
                category="binaries",
                details=f"Found at {whisper_model}",
            )
        )
    else:
        checks.append(
            CheckResult(
                name="whisper.cpp model",
                passed=False,
                category="binaries",
                error=f"Whisper GGUF model not found at {whisper_model}",
                hint="Run: aria init  (or aria voice download)",
            )
        )

    if Voice.is_kokoro_available():
        checks.append(
            CheckResult(
                name="kokoro TTS",
                passed=True,
                category="binaries",
                details=f"Model at {Voice.get_kokoro_model_path()}",
            )
        )
    else:
        checks.append(
            CheckResult(
                name="kokoro TTS",
                passed=False,
                category="binaries",
                error="kokoro TTS model not installed",
                hint="Run: aria init  (or aria voice download)",
            )
        )

    kokoro_voices = Voice.get_kokoro_voices_path()
    if kokoro_voices.is_file():
        checks.append(
            CheckResult(
                name="kokoro voices",
                passed=True,
                category="binaries",
                details=f"Found at {kokoro_voices}",
            )
        )
    else:
        checks.append(
            CheckResult(
                name="kokoro voices",
                passed=False,
                category="binaries",
                error=f"kokoro voices file not found at {kokoro_voices}",
                hint="Run: aria init  (or aria voice download)",
            )
        )

    if Voice.get_kokoro_python() is None:
        checks.append(
            CheckResult(
                name="kokoro-tts tool",
                passed=False,
                category="binaries",
                error="kokoro-tts Python tool not installed",
                hint="Run: aria init  (or aria voice download)",
            )
        )
    else:
        checks.append(
            CheckResult(
                name="kokoro-tts tool",
                passed=True,
                category="binaries",
                details="uv tool env ready",
            )
        )
