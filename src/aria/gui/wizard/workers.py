"""Background workers for the setup wizard."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class _PreflightWorker(QObject):
    """Run preflight checks off the GUI thread."""

    finished = Signal(object)

    def run(self):
        from aria.preflight import run_preflight_checks

        self.finished.emit(run_preflight_checks())


class _DownloadWorker(QObject):
    """Download a single dependency off the GUI thread.

    Targets mirror ``aria init``'s install/download steps (§7.2 full
    parity): ``lightpanda``, ``vllm``, ``chat``, ``embeddings``,
    ``docling`` (install + model), and ``voice`` (whisper + kokoro).
    """

    finished = Signal(bool, str)  # (success, message)

    def __init__(self, target: str):
        super().__init__()
        self._target = target

    def run(self):
        try:
            self._dispatch(self._target)
        except Exception as exc:
            self.finished.emit(False, str(exc))

    def _dispatch(self, target: str) -> None:
        if target == "lightpanda":
            self._install_lightpanda()
        elif target == "vllm":
            self._install_vllm()
        elif target in ("chat", "embeddings"):
            self._download_model(target)
        elif target == "docling":
            self._install_docling()
        elif target == "voice":
            self._install_voice()
        else:
            self.finished.emit(False, f"Unknown target: {target}")

    def _install_lightpanda(self) -> None:
        from aria.config.api import Lightpanda
        from aria.scripts.lightpanda import download_lightpanda

        download_lightpanda(
            bin_dir=Lightpanda.get_bin_path(),
            version=Lightpanda.version,
        )
        self.finished.emit(True, "Lightpanda installed.")

    def _install_vllm(self) -> None:
        from aria.scripts.vllm import install_vllm

        install_vllm()
        self.finished.emit(True, "vLLM installed.")

    def _download_model(self, target: str) -> None:
        from os import getenv
        from pathlib import Path

        from aria.config.models import Chat, Embeddings
        from aria.server.lifecycle import download_model_snapshot

        env_var = "CHAT_MODEL_PATH" if target == "chat" else "EMBED_MODEL_PATH"
        config = Chat if target == "chat" else Embeddings
        raw = getenv(env_var, "")
        if not raw or Path(raw).is_absolute():
            self.finished.emit(
                False,
                f"{env_var} must be a HuggingFace repo ID "
                "(owner/model) to download from the wizard.",
            )
            return
        download_model_snapshot(target, raw, Path(config.model_path))
        self.finished.emit(True, f"{target.capitalize()} model downloaded.")

    def _install_docling(self) -> None:
        from aria.config.models import _resolve_model_path
        from aria.config.pdf import Pdf
        from aria.scripts.docling import install_docling
        from aria.server.lifecycle import download_model_snapshot

        install_docling()
        # Pre-fetch the docling model so the first PDF conversion doesn't
        # block (mirrors `aria docling download`).
        docling_path = Pdf.model_path or _resolve_model_path(Pdf.vlm_model_id)
        from pathlib import Path

        if not Path(docling_path).is_dir():
            download_model_snapshot("docling", Pdf.vlm_model_id, Path(docling_path))
        self.finished.emit(True, "docling worker + model installed.")

    def _install_voice(self) -> None:
        from aria.scripts.voice import download_kokoro, download_whisper_cpp

        download_whisper_cpp()
        download_kokoro()
        self.finished.emit(True, "voice assistant (whisper + kokoro) installed.")
