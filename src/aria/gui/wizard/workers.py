"""Background workers for the setup wizard."""

from __future__ import annotations

from os import getenv

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
            elif self._target == "embeddings":
                from huggingface_hub import snapshot_download

                from aria.config.huggingface import HuggingFace
                from aria.config.models import Embeddings

                repo_id = getenv("EMBED_MODEL_PATH", "")
                if not repo_id:
                    self.finished.emit(
                        False,
                        "EMBED_MODEL_PATH is not set — configure it in .env first",
                    )
                    return
                snapshot_download(
                    repo_id=repo_id,
                    local_dir=Embeddings.model_path,
                    token=HuggingFace.token,
                )
                self.finished.emit(True, "Embeddings model downloaded.")
            else:
                self.finished.emit(False, f"Unknown target: {self._target}")
        except Exception as exc:
            self.finished.emit(False, str(exc))
