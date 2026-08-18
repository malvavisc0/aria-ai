"""Knowledge hub tab handlers for the MainWindow.

This module provides a mixin class with knowledge-hub management
functionality for the Aria GUI application: status display, file
add/remove, and reindex execution in a background worker.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFileDialog, QListWidgetItem, QMessageBox

from aria.config.api import KnowledgeHub
from aria.gui.ui.mainwindow import Ui_MainWindow
from aria.server.digest_lease import active_digest

_STATE_INDEXED = "indexed"
_STATE_SKIPPED = "skipped"


class _KbStatus:
    """Snapshot of the knowledge hub state for one status render."""

    __slots__ = ("indexed_count", "skipped_count", "last_index_at", "rows")

    def __init__(
        self,
        indexed_count: int,
        skipped_count: int,
        last_index_at: str | None,
        rows: dict[str, tuple[str, float, int, str | None]],
    ) -> None:
        self.indexed_count = indexed_count
        self.skipped_count = skipped_count
        self.last_index_at = last_index_at
        # rel path -> (state, mtime, size, skip_reason)
        self.rows = rows


def _fetch_kb_status() -> _KbStatus | None:
    """Read index state directly from tools.db (no tool envelope).

    Returns None when the DB is not ready yet (first run before any
    reindex created the tables).
    """
    from sqlalchemy import select

    from aria.tools.database import get_tools_database
    from aria.tools.knowledge.models import KnowledgeIndexStateModel as M

    try:
        with get_tools_database().get_session() as session:
            rows = session.execute(
                select(M.path, M.mtime, M.size, M.state, M.skip_reason, M.indexed_at)
            ).all()
    except Exception:  # DB/tables not ready yet
        return None
    states = {
        path: (state, mtime, size, skip_reason)
        for path, mtime, size, state, skip_reason, _ in rows
    }
    last = max((indexed_at for *_, indexed_at in rows), default=None)
    return _KbStatus(
        indexed_count=sum(1 for r in rows if r[3] == _STATE_INDEXED),
        skipped_count=sum(1 for r in rows if r[3] == _STATE_SKIPPED),
        last_index_at=last.isoformat() if last is not None else None,
        rows=states,
    )


def _file_marker(
    rel: str,
    st_mtime: float,
    st_size: int,
    rows: dict[str, tuple[str, float, int, str | None]],
) -> str:
    """Return the state marker prefix for one file (● indexed / ○ pending / ⚠ skipped)."""
    row = rows.get(rel)
    if row is None:
        return "○"
    state, mtime, size, _ = row
    if state == _STATE_SKIPPED:
        return "⚠"
    return "●" if mtime == st_mtime and size == st_size else "○"


def _kb_files(root: Path) -> list[Path]:
    """List knowledge-hub files (sorted, skipping dirs and dotfiles)."""
    if not root.is_dir():
        return []
    return sorted(
        fp for fp in root.rglob("*") if not fp.is_dir() and not fp.name.startswith(".")
    )


def _kb_placeholder_item() -> QListWidgetItem:
    """Empty-state row shown when the knowledge hub has no files."""
    text = (
        "Knowledge hub is disabled."
        if not KnowledgeHub.enabled
        else "No files yet. Add files to build the knowledge base."
    )
    item = QListWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
    item.setForeground(QColor("#9CA3AF"))
    return item


def _kb_file_item(
    rel: str,
    st: os.stat_result,
    rows: dict[str, tuple[str, float, int, str | None]],
) -> QListWidgetItem:
    """Build one file-list row with its state marker and styling."""
    marker = _file_marker(rel, st.st_mtime, st.st_size, rows)
    row = rows.get(rel)
    reason = row[3] if row is not None and row[0] == _STATE_SKIPPED else None
    label = f"{marker} {rel}" + (f"  ({reason})" if reason else "")
    item = QListWidgetItem(label)
    item.setData(Qt.ItemDataRole.UserRole, rel)
    if reason:
        item.setToolTip(f"Skipped: {reason}")
        item.setForeground(QColor("#B45309"))  # amber
    elif marker == "○":
        item.setToolTip("Not indexed yet — run Reindex")
        item.setForeground(QColor("#7A8794"))  # muted
    else:
        item.setToolTip("Indexed")
    return item


def _humanize_ts(iso: str | None) -> str:
    """Format an ISO timestamp for the status row; 'never' when absent."""
    if not iso:
        return "never"
    from datetime import datetime

    try:
        return datetime.fromisoformat(iso).strftime("%b %d, %H:%M")
    except ValueError:
        return iso


def _load_embeddings_path() -> str:
    """Resolve the local embeddings model path, mirroring web startup.

    Raises RuntimeError with the download hint when the model is missing.
    """
    from aria.config.models import Embeddings as EmbeddingsConfig

    model_ref = EmbeddingsConfig.model_path or EmbeddingsConfig.model
    model_path = Path(model_ref) if model_ref else None
    if model_path and model_path.is_dir():
        return str(model_path)
    raise RuntimeError(
        f"Embeddings model not found locally at '{model_ref}'. "
        "Pre-download it: aria models download --model embeddings"
    )


class _ReindexWorker(QObject):
    """Background worker that runs a knowledge-hub reindex off the GUI thread.

    Lazy-loads the embeddings model and Chroma client on first run (cached
    on the mixin), sets them on the shared ``aria.web.state._state``
    singleton, then runs ``KnowledgeHubIndexer().reindex()`` — which takes
    the cross-process digest lease itself.
    """

    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, mixin: KnowledgeHandlersMixin, *, force: bool) -> None:
        super().__init__()
        self._mixin = mixin
        self._force = force

    def run(self) -> None:
        try:
            self._run()
        except Exception as exc:  # pragma: no cover - defensive UI path
            self.failed.emit(str(exc))

    def _run(self) -> None:
        import asyncio

        from chromadb import PersistentClient

        from aria.config.database import ChromaDB
        from aria.llm import get_embeddings_model
        from aria.server.knowledge_hub import KnowledgeHubIndexer
        from aria.tools.database import get_tools_database
        from aria.web.state import _state

        if self._mixin._kb_embeddings is None:
            self._mixin._kb_embeddings = get_embeddings_model(
                model_name=_load_embeddings_path()
            )
        if self._mixin._kb_vector_db is None:
            self._mixin._kb_vector_db = PersistentClient(path=str(ChromaDB.db_path))

        _state.embeddings = self._mixin._kb_embeddings
        _state.vector_db = self._mixin._kb_vector_db

        get_tools_database().create_tables()
        result = asyncio.run(KnowledgeHubIndexer().reindex(force=self._force))
        if "error" in result:
            self.failed.emit(str(result["error"]))
        else:
            self.finished.emit(result)


class KnowledgeHandlersMixin:
    """Mixin class providing knowledge-hub tab handlers for MainWindow.

    Expects to be combined with ``ServerHandlersMixin`` (for
    ``_refresh_status_style``) and a QMainWindow that has a ``ui``
    attribute of type ``Ui_MainWindow``.
    """

    ui: Ui_MainWindow

    def _init_knowledge_tab(self) -> None:
        """Initialize knowledge tab state. Call from MainWindow __init__."""
        self._kb_embeddings: Any = None
        self._kb_vector_db: Any = None
        self._kb_reindex_running = False
        self._knowledge_timer = QTimer()
        self._knowledge_timer.timeout.connect(self._refresh_knowledge_status)
        # Counts/last-index are metadata, not status — quiet grey, no pill.
        self.ui.label_KbCounts.setProperty("muted", True)
        self.ui.label_KbLastIndex.setProperty("muted", True)
        if KnowledgeHub.enabled:
            # Idempotent — ensures the status query works before the first
            # reindex ever ran (fresh install).
            import aria.tools.knowledge.models  # noqa: F401 — registers table
            from aria.tools.database import get_tools_database

            get_tools_database().create_tables()

    def _connect_knowledge_signals(self) -> None:
        """Connect knowledge tab button signals. Call from MainWindow __init__."""
        self.ui.pushButton_KbAdd.clicked.connect(self._on_kb_add_files)
        self.ui.pushButton_KbRemove.clicked.connect(self._on_kb_remove_selected)
        self.ui.pushButton_KbReindex.clicked.connect(
            lambda: self._on_kb_reindex(force=False)
        )
        self.ui.pushButton_KbForceReindex.clicked.connect(
            lambda: self._on_kb_reindex(force=True)
        )
        self.ui.listWidget_KnowledgeFiles.itemSelectionChanged.connect(
            self._update_kb_buttons
        )

    # --- status rendering ---------------------------------------------------

    def _refresh_knowledge_status(self) -> None:
        """Poll status (2s timer): digest lease, counts, file list, buttons."""
        if not KnowledgeHub.enabled:
            self._refresh_status_style(self.ui.label_KbStatus, "idle")
            self.ui.label_KbStatus.setText(
                "○ Disabled — set ARIA_KNOWLEDGE_ENABLED=true"
            )
            self._refresh_status_style(self.ui.label_KbDigest, "idle")
            self.ui.label_KbDigest.setText("-")
            self.ui.label_KbCounts.setText("-")
            self.ui.label_KbLastIndex.setText("-")
            self._update_kb_buttons()
            return

        self._refresh_status_style(self.ui.label_KbStatus, "running")
        self.ui.label_KbStatus.setText("● Enabled")

        lease = active_digest()
        if lease is not None:
            current = lease.get("current_file") or "…"
            fm = self.ui.label_KbDigest.fontMetrics()
            elided = fm.elidedText(current, Qt.TextElideMode.ElideMiddle, 320)
            self._refresh_status_style(self.ui.label_KbDigest, "warning")
            self.ui.label_KbDigest.setText(f"● Digesting: {elided}")
            self.ui.label_KbDigest.setToolTip(current)
        else:
            self._refresh_status_style(self.ui.label_KbDigest, "idle")
            self.ui.label_KbDigest.setText("○ Idle")
            self.ui.label_KbDigest.setToolTip("")

        status = _fetch_kb_status()
        if status is not None:
            self.ui.label_KbCounts.setText(
                f"{status.indexed_count} indexed · {status.skipped_count} skipped"
            )
            self.ui.label_KbLastIndex.setText(
                f"Last index: {_humanize_ts(status.last_index_at)}"
            )
            self._render_kb_file_list(status)

        self._update_kb_buttons()

    def _render_kb_file_list(self, status: _KbStatus) -> None:
        """Rebuild the file list with per-file state markers.

        Markers: ● indexed (mtime+size match the state row), ○ pending
        (new or changed since last run — e.g. added while the server was
        stopped), ⚠ skipped (state row carries the reason). Selection and
        scroll position survive the 2s rebuild.
        """
        root = Path(KnowledgeHub.dir)
        selected = {
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.ui.listWidget_KnowledgeFiles.selectedItems()
        }
        scrollbar = self.ui.listWidget_KnowledgeFiles.verticalScrollBar()
        scroll_pos = scrollbar.value()

        self.ui.listWidget_KnowledgeFiles.clear()
        files = _kb_files(root)
        if not files:
            self.ui.listWidget_KnowledgeFiles.addItem(_kb_placeholder_item())
            return

        for fp in files:
            rel = str(fp.relative_to(root))
            try:
                st = fp.stat()
            except OSError:
                continue
            item = _kb_file_item(rel, st, status.rows)
            self.ui.listWidget_KnowledgeFiles.addItem(item)
            if rel in selected:
                item.setSelected(True)
        scrollbar.setValue(scroll_pos)

    def _update_kb_buttons(self) -> None:
        """Enable/disable knowledge buttons from current state."""
        digesting = active_digest() is not None
        blocked = not KnowledgeHub.enabled or digesting or self._kb_reindex_running
        for btn in (
            self.ui.pushButton_KbAdd,
            self.ui.pushButton_KbReindex,
            self.ui.pushButton_KbForceReindex,
        ):
            btn.setEnabled(not blocked)
        has_selection = bool(self.ui.listWidget_KnowledgeFiles.selectedItems())
        self.ui.pushButton_KbRemove.setEnabled(not blocked and has_selection)
        if not KnowledgeHub.enabled:
            tooltip = "Knowledge hub is disabled (ARIA_KNOWLEDGE_ENABLED)"
        elif digesting:
            tooltip = "A digest is running — wait for it to finish"
        elif self._kb_reindex_running:
            tooltip = "Reindex in progress…"
        else:
            tooltip = ""
        self.ui.pushButton_KbReindex.setToolTip(tooltip)
        self.ui.pushButton_KbForceReindex.setToolTip(tooltip)

    # --- file operations ----------------------------------------------------

    def _confirm_kb_overwrite(self, paths: list[str], root: Path) -> bool:
        """One batched overwrite confirm instead of N sequential dialogs."""
        existing = [p for p in paths if (root / Path(p).name).exists()]
        if not existing:
            return False
        reply = QMessageBox.question(
            self,
            "Overwrite?",
            f"{len(existing)} of {len(paths)} file(s) already exist. Overwrite them?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _on_kb_add_files(self) -> None:
        """Copy picked files into the knowledge dir, then offer to index."""
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files to knowledge hub")
        if not paths:
            return
        root = Path(KnowledgeHub.dir)
        root.mkdir(parents=True, exist_ok=True)
        overwrite = self._confirm_kb_overwrite(paths, root)

        added = 0
        for src in paths:
            dest = root / Path(src).name
            if dest.exists() and not overwrite:
                continue
            shutil.copy2(src, dest)
            added += 1
        self._refresh_knowledge_status()
        if added and active_digest() is None:
            reply = QMessageBox.question(
                self,
                "Index files",
                f"{added} file(s) added — index them now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._on_kb_reindex(force=False)

    def _on_kb_remove_selected(self) -> None:
        """Delete selected files from the knowledge dir, then refresh."""
        items = self.ui.listWidget_KnowledgeFiles.selectedItems()
        if not items:
            return
        reply = QMessageBox.question(
            self,
            "Remove files",
            f"Delete {len(items)} file(s) from the knowledge hub?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        root = Path(KnowledgeHub.dir)
        for item in items:
            rel = item.data(Qt.ItemDataRole.UserRole)
            (root / rel).unlink(missing_ok=True)
        self._refresh_knowledge_status()
        # Removed files keep their Chroma chunks until the next reindex
        # purges them — offer to purge now rather than letting the
        # assistant keep citing deleted content.
        if active_digest() is None:
            purge = QMessageBox.question(
                self,
                "Purge removed content",
                f"{len(items)} file(s) removed — reindex now to purge "
                "their indexed content?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if purge == QMessageBox.StandardButton.Yes:
                self._on_kb_reindex(force=False)
        else:
            self.statusBar().showMessage(
                f"{len(items)} file(s) removed — chunks purged on next reindex",
                5000,
            )

    # --- reindex --------------------------------------------------------------

    def _on_kb_reindex(self, *, force: bool) -> None:
        """Start a reindex in a background worker (refuses during a digest)."""
        if active_digest() is not None:
            self.statusBar().showMessage(
                "A digest is already running — wait for it to finish", 5000
            )
            return
        if force:
            reply = QMessageBox.question(
                self,
                "Force Reindex",
                "Rebuild the entire knowledge collection from scratch?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._kb_reindex_running = True
        self._update_kb_buttons()
        self.statusBar().showMessage("Reindexing knowledge hub…")

        self._kb_thread = QThread()
        self._kb_worker = _ReindexWorker(self, force=force)
        self._kb_worker.moveToThread(self._kb_thread)
        self._kb_thread.started.connect(self._kb_worker.run)
        self._kb_worker.finished.connect(self._on_kb_reindex_finished)
        self._kb_worker.failed.connect(self._on_kb_reindex_failed)
        self._kb_worker.finished.connect(self._kb_thread.quit)
        self._kb_worker.failed.connect(self._kb_thread.quit)
        self._kb_worker.finished.connect(self._kb_worker.deleteLater)
        self._kb_worker.failed.connect(self._kb_worker.deleteLater)
        self._kb_thread.finished.connect(self._kb_thread.deleteLater)
        self._kb_thread.start()

    def _on_kb_reindex_finished(self, result: dict) -> None:
        """Handle a completed reindex."""
        self._kb_reindex_running = False
        indexed = result.get("indexed", 0)
        skipped = len(result.get("skipped") or [])
        self.statusBar().showMessage(
            f"Reindex done: {indexed} file(s) indexed, {skipped} skipped", 8000
        )
        self._refresh_knowledge_status()

    def _on_kb_reindex_failed(self, error: str) -> None:
        """Handle a failed reindex."""
        self._kb_reindex_running = False
        self.statusBar().showMessage(f"Reindex failed: {error}", 10000)
        QMessageBox.warning(self, "Reindex Failed", error)
        self._refresh_knowledge_status()
