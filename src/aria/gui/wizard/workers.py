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
    """Download a single dependency off the GUI thread."""

    finished = Signal(bool, str)  # (success, message)

    def __init__(self, target: str):
        super().__init__()
        self._target = target

    def run(self):
        try:
            if self._target == "lightpanda":
                from aria.config.api import Lightpanda
                from aria.scripts.lightpanda import download_lightpanda

                download_lightpanda(
                    bin_dir=Lightpanda.get_bin_path(),
                    version=Lightpanda.version,
                )
                self.finished.emit(True, "Lightpanda installed.")
            elif self._target == "vllm":
                from aria.scripts.vllm import install_vllm

                install_vllm()
                self.finished.emit(True, "vLLM installed.")
            elif self._target in ("chat", "embeddings"):
                from os import getenv
                from pathlib import Path

                from aria.config.models import Chat, Embeddings
                from aria.server.lifecycle import download_model_snapshot

                env_var = (
                    "CHAT_MODEL_PATH" if self._target == "chat" else "EMBED_MODEL_PATH"
                )
                config = Chat if self._target == "chat" else Embeddings
                raw = getenv(env_var, "")
                if not raw or Path(raw).is_absolute():
                    self.finished.emit(
                        False,
                        f"{env_var} must be a HuggingFace repo ID "
                        "(owner/model) to download from the wizard.",
                    )
                    return
                download_model_snapshot(self._target, raw, Path(config.model_path))
                self.finished.emit(
                    True, f"{self._target.capitalize()} model downloaded."
                )
            else:
                self.finished.emit(False, f"Unknown target: {self._target}")
        except Exception as exc:
            self.finished.emit(False, str(exc))
