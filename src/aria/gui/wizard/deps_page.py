"""Wizard dependencies page — checks and downloads installable components.

Extracted from ``pages.py`` to keep that file under the size cap. Has full
parity with ``aria init`` (§7.2): docling (install + model) and voice
(whisper + kokoro) join the existing lightpanda/vllm/chat/embeddings
targets. vLLM/chat rows are hidden in remote mode; voice rows are hidden
without a GPU (Decision 5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWizardPage,
)

from aria.gui.wizard.workers import _DownloadWorker, _PreflightWorker

if TYPE_CHECKING:
    from aria.gui.wizard.pages import SetupWizard


class _DependenciesPage(QWizardPage):
    """Wizard page that checks and downloads installable dependencies.

    Installable checks (vLLM, lightpanda, chat/embeddings models, docling,
    voice) gate progression. Other preflight results are shown for
    information only — enforced by the main window's preflight gate.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Dependencies")
        self.setSubTitle("Download the required dependencies before continuing.")

        layout = QVBoxLayout(self)

        self._status_layout = QVBoxLayout()
        layout.addLayout(self._status_layout)

        self._info_label = QLabel("Checking dependencies\u2026")
        self._info_label.setWordWrap(True)
        layout.addWidget(self._info_label)

        layout.addStretch()

        self._all_ok = False
        self._downloading = False

    # -- Qt overrides -------------------------------------------------------

    def initializePage(self):
        self._info_label.setText("Checking dependencies\u2026")
        self._run_preflight()

    def isComplete(self) -> bool:
        return self._all_ok and not self._downloading

    def nextId(self) -> int:
        wizard = cast("SetupWizard", self.wizard())
        if wizard.has_admin:
            return 3  # Finish page
        return 2  # User page

    # -- Internal -----------------------------------------------------------

    def _run_preflight(self):
        self._thread = QThread()
        self._worker = _PreflightWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_preflight_done)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _clear_status_layout(self) -> None:
        while self._status_layout.count():
            item = self._status_layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()
            sub = item.layout()
            if sub is not None:
                while sub.count():
                    child = sub.takeAt(0)
                    if child is not None:
                        cw = child.widget()
                        if cw is not None:
                            cw.deleteLater()

    def _on_preflight_done(self, result):
        self._clear_status_layout()

        hardware, remote = self._connection_context()
        relevant = [
            c
            for c in result.checks
            if c.category in ("binaries", "models")
            and self._should_show_check(c, hardware, remote)
        ]

        if not relevant:
            self._info_label.setText("No dependencies to check.")
            self._all_ok = True
            self.completeChanged.emit()
            return

        self._all_ok = all(self._add_check_row(c) for c in relevant)
        self._info_label.setText(self._deps_summary(relevant))
        self.completeChanged.emit()

    @staticmethod
    def _deps_summary(relevant) -> str:
        """Build the info-label text from the relevant checks."""
        warnings = [c for c in relevant if c.warning]
        if not all(c.passed for c in relevant):
            return "Install the missing dependencies to continue."
        if warnings:
            names = ", ".join(c.name for c in warnings)
            return f"Dependencies are ready. Optional components missing: {names}."
        return "All dependencies are ready."

    def _connection_context(self):
        """Read hardware + remote flag from the connection page (page 0)."""
        from aria.gui.wizard.pages import SetupWizard as _SetupWizard
        from aria.gui.wizard.pages import _ConnectionPage as _ConnPage

        wizard = cast(_SetupWizard, self.wizard())
        conn_page = cast(_ConnPage, wizard.page(0))
        return conn_page._hardware, conn_page.get_connection_mode() == "remote"

    def _add_check_row(self, check) -> bool:
        target = self._resolve_target(check.name)
        icon = "❌" if not check.passed else ("⚠️" if check.warning else "✅")
        text = f"{icon}  {check.name}"
        if check.passed:
            if check.details:
                text += f"  ({check.details})"
        elif check.hint and target is None:
            text += f"  ({check.hint})"

        download_required = target is not None and not check.passed

        row = QHBoxLayout()
        row.addWidget(QLabel(text))
        if download_required:
            btn = QPushButton("Download")
            btn.clicked.connect(
                lambda checked=False, n=check.name: self._on_download(n)
            )
            row.addWidget(btn)
        self._status_layout.addLayout(row)

        return not download_required

    def _on_download(self, name: str):
        target = self._resolve_target(name)
        if not target:
            return

        self._downloading = True
        self.completeChanged.emit()
        self._info_label.setText(f"Downloading {name}\u2026")

        for i in range(self._status_layout.count()):
            row_item = self._status_layout.itemAt(i)
            if row_item is None:
                continue
            row_layout = row_item.layout()
            if row_layout is None:
                continue
            for j in range(row_layout.count()):
                w = row_layout.itemAt(j).widget()
                if isinstance(w, QPushButton):
                    w.setEnabled(False)

        self._dl_thread = QThread()
        self._dl_worker = _DownloadWorker(target)
        self._dl_worker.moveToThread(self._dl_thread)
        self._dl_thread.started.connect(self._dl_worker.run)
        self._dl_worker.finished.connect(self._on_download_done)
        self._dl_worker.finished.connect(self._dl_thread.quit)
        self._dl_worker.finished.connect(self._dl_worker.deleteLater)
        self._dl_thread.finished.connect(self._dl_thread.deleteLater)
        self._dl_thread.start()

    def _on_download_done(self, ok: bool, message: str):
        self._downloading = False
        if ok:
            self._info_label.setText(f"\u2705 {message}")
        else:
            self._info_label.setText(f"\u274c Download failed: {message}")
        self._run_preflight()

    @staticmethod
    def _resolve_target(name: str) -> str | None:
        """Map a preflight check name to a download target key."""
        name_lower = name.lower()
        if "lightpanda" in name_lower:
            return "lightpanda"
        if "vllm" in name_lower:
            return "vllm"
        if "chat model" in name_lower:
            return "chat"
        if "embedding" in name_lower:
            return "embeddings"
        if "docling" in name_lower:
            return "docling"
        if "whisper" in name_lower or "kokoro" in name_lower:
            return "voice"
        return None

    @staticmethod
    def _should_show_check(check, hardware, remote: bool) -> bool:
        """Hide rows that don't apply to the chosen mode / hardware.

        - Remote mode: vLLM and chat-model rows are hidden (not installed).
        - No GPU: voice rows are hidden (Decision 5 — no CPU voice).
        """
        name = check.name.lower()
        if remote and ("vllm" in name or "chat model" in name):
            return False
        # No GPU: hide every voice row — preflight emits a literal
        # "voice" check (disabled state) plus the whisper/kokoro rows.
        if not hardware.has_nvidia_gpu and (
            "voice" in name or "whisper" in name or "kokoro" in name
        ):
            return False
        return True
