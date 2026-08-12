"""Server management handlers for the MainWindow.

This module provides a mixin class with server control functionality
for the Aria GUI application.
"""

from __future__ import annotations

import time
import webbrowser

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import QMessageBox

from aria.config.service import Server
from aria.gui.ui.mainwindow import Ui_MainWindow
from aria.server import ServerManager


class _StopWorker(QObject):
    """Background worker that calls ServerManager.stop() off the GUI thread."""

    finished = Signal()
    failed = Signal(str)

    def __init__(self, server_manager):
        super().__init__()
        self._server_manager = server_manager

    def run(self):
        try:
            self._server_manager.stop()
            self.finished.emit()
        except Exception as exc:  # pragma: no cover - defensive UI path
            self.failed.emit(str(exc))


class _EndpointValidationWorker(QObject):
    """Background worker that validates the AI endpoint off the GUI thread."""

    finished = Signal(bool, str)  # (ok, message)

    def run(self):
        import httpx

        from aria.config import get_optional_env
        from aria.config.api import Vllm
        from aria.config.models import Chat

        url = Chat.api_url
        headers = {}
        if Vllm.remote:
            api_key = get_optional_env("ARIA_VLLM_API_KEY", "")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

        try:
            r = httpx.get(f"{url}/models", headers=headers, timeout=5)
            if r.status_code == 200:
                data = r.json()
                model_count = len(data.get("data", []))
                self.finished.emit(
                    True, f"Connected ({model_count} model(s) available)"
                )
            elif r.status_code == 401:
                self.finished.emit(False, "Authentication failed — check your API key")
            else:
                self.finished.emit(False, f"Endpoint returned HTTP {r.status_code}")
        except httpx.ConnectError:
            self.finished.emit(False, f"Cannot connect to {url}")
        except httpx.TimeoutException:
            self.finished.emit(False, f"Connection timed out ({url})")
        except Exception as e:
            self.finished.emit(False, str(e))


class _PreflightWorker(QObject):
    """Background worker that runs preflight checks off the GUI thread."""

    finished = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            from aria.preflight import run_preflight_checks

            self.finished.emit(run_preflight_checks())
        except Exception as exc:  # pragma: no cover - defensive UI path
            self.failed.emit(str(exc))


class ServerHandlersMixin:
    """Mixin class providing server management handlers for MainWindow.

    This mixin expects to be combined with a QMainWindow that has a ``ui``
    attribute of type ``Ui_MainWindow``. It provides:

    - Server start/stop/open button handlers
    - Periodic status updates via QTimer
    - Button state management based on server running state

    Attributes:
        _server_manager: ServerManager instance for controlling the webserver.
        _server_timer: QTimer for periodic status updates.
    """

    ui: Ui_MainWindow

    def _init_server_manager(self):
        """Initialize the server manager and status update timer.

        This method should be called in the MainWindow __init__ method
        after the UI is set up.
        """
        self._server_manager = ServerManager()
        self._preflight_result = None
        self._preflight_running = False
        self._is_stopping = False  # Track stopping state for UI feedback
        self._stopping_since: float = 0.0  # Timestamp for timeout
        self._was_healthy = False  # Track crash detection
        self._server_timer = QTimer()
        self._server_timer.timeout.connect(self._update_server_status)
        self._server_timer.start(1000)

    def _connect_server_signals(self):
        """Connect server control button signals.

        This method should be called in the MainWindow __init__ method
        to connect the Start, Stop, Open, and Test Connection buttons.
        """
        self.ui.pushButton_ServiceStart.clicked.connect(self.on_start_server)
        self.ui.pushButton_ServiceStop.clicked.connect(self.on_stop_server)
        self.ui.pushButton_ServiceOpen.clicked.connect(self.on_open_server)
        self.ui.pushButton_TestConnection.clicked.connect(
            self._on_test_connection_clicked
        )

    def _run_preflight(self) -> None:
        """Run preflight checks and cache the result.

        Calls ``run_preflight_checks()`` (which may invoke nvidia-smi and
        other subprocess calls) and stores the result in
        ``self._preflight_result``.  Triggers a status-bar refresh so the
        Start button state is updated immediately.

        Call this on startup and whenever the environment may have changed
        (e.g. after a binary or model download completes, or when the user
        switches to the Overview / Setup tab).
        """
        if self._preflight_running:
            return

        self._preflight_running = True
        self.statusBar().showMessage("Running preflight checks…")
        self._preflight_thread = QThread()
        self._preflight_worker = _PreflightWorker()
        self._preflight_worker.moveToThread(self._preflight_thread)
        self._preflight_thread.started.connect(self._preflight_worker.run)
        self._preflight_worker.finished.connect(self._on_preflight_finished)
        self._preflight_worker.failed.connect(self._on_preflight_failed)
        self._preflight_worker.finished.connect(self._preflight_thread.quit)
        self._preflight_worker.failed.connect(self._preflight_thread.quit)
        self._preflight_worker.finished.connect(self._preflight_worker.deleteLater)
        self._preflight_worker.failed.connect(self._preflight_worker.deleteLater)
        self._preflight_thread.finished.connect(self._preflight_thread.deleteLater)
        self._preflight_thread.start()

    def _on_preflight_finished(self, result) -> None:
        """Persist completed preflight results and refresh the UI."""
        self._preflight_result = result
        self._preflight_running = False

        if result.passed:
            self.statusBar().showMessage("All preflight checks passed.", 5000)
        else:
            failure_count = len(result.failures)
            self.statusBar().showMessage(
                f"{failure_count} preflight check(s) failed. "
                "Hover over Start button for details.",
                10000,
            )

        self._update_server_status()

    def _on_preflight_failed(self, error: str) -> None:
        """Recover UI state when background preflight execution fails."""
        self._preflight_running = False
        self.statusBar().showMessage(f"Preflight failed: {error}")
        QMessageBox.warning(
            self,
            "Preflight Failed",
            f"Preflight checks failed unexpectedly:\n{error}",
        )
        self._update_server_status()

    def _on_test_connection_clicked(self):
        """Handle Test Connection button click (runs validation in background)."""
        self.ui.pushButton_TestConnection.setEnabled(False)
        self.ui.label_ConnectionStatus.setText("Testing…")
        self._run_endpoint_validation(self._on_test_connection_result)

    def _on_test_connection_result(self, ok: bool, message: str):
        """Update the connection status label with validation result."""
        self.ui.pushButton_TestConnection.setEnabled(True)
        label = self.ui.label_ConnectionStatus
        if ok:
            label.setText(f"✓ {message}")
            label.setProperty("connection", "ok")
        else:
            label.setText(f"✗ {message}")
            label.setProperty("connection", "fail")
        label.style().unpolish(label)
        label.style().polish(label)

    def _run_endpoint_validation(self, callback) -> None:
        """Run endpoint validation in a background thread.

        Args:
            callback: Function(ok: bool, message: str) called on completion.
        """
        self._validation_thread = QThread()
        self._validation_worker = _EndpointValidationWorker()
        self._validation_worker.moveToThread(self._validation_thread)
        self._validation_thread.started.connect(self._validation_worker.run)
        self._validation_worker.finished.connect(callback)
        self._validation_worker.finished.connect(self._validation_thread.quit)
        self._validation_worker.finished.connect(self._validation_worker.deleteLater)
        self._validation_thread.finished.connect(self._validation_thread.deleteLater)
        self._validation_thread.start()

    def on_start_server(self):
        """Handle Start button click.

        Starts the Chainlit webserver as a background subprocess.
        The llama-server inference processes are started automatically
        by the web UI via the Chainlit ``on_app_startup`` lifecycle hook.

        Validates the AI endpoint in a background thread before starting.
        """
        self.ui.pushButton_ServiceStart.setEnabled(False)
        self.statusBar().showMessage("Validating AI endpoint…")
        self._run_endpoint_validation(self._on_start_validation_result)

    def _on_start_validation_result(self, ok: bool, message: str):
        """Handle endpoint validation result before starting the server."""
        if not ok:
            self.ui.pushButton_ServiceStart.setEnabled(True)
            QMessageBox.warning(
                self,
                "Cannot Start Server",
                f"AI endpoint validation failed:\n\n{message}\n\n"
                "Check your connection settings and try again.",
            )
            return

        self.statusBar().showMessage("Starting Aria server\u2026")

        started = self._server_manager.start()
        if not started:
            QMessageBox.warning(
                self,
                "Already Running",
                "The server is already running.",
            )

        self._update_server_status()

    def on_stop_server(self):
        """Handle Stop button click.

        Stops the Chainlit webserver off the GUI thread to avoid blocking.
        The llama-server inference processes are stopped automatically by
        the web UI via the Chainlit ``on_app_shutdown`` lifecycle hook.
        """
        # Confirm before stopping a healthy server
        status = self._server_manager.get_status()
        if status.healthy:
            reply = QMessageBox.question(
                self,
                "Confirm Stop",
                "Are you sure you want to stop the server?\n"
                "Active chat sessions will be disconnected.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Disable both buttons immediately to prevent double-clicks
        self.ui.pushButton_ServiceStop.setEnabled(False)
        self.ui.pushButton_ServiceStart.setEnabled(False)
        self._is_stopping = True
        self._stopping_since = time.monotonic()
        self.statusBar().showMessage("Stopping Aria server\u2026")

        self._stop_thread = QThread()
        self._stop_worker = _StopWorker(self._server_manager)
        self._stop_worker.moveToThread(self._stop_thread)
        self._stop_thread.started.connect(self._stop_worker.run)
        self._stop_worker.finished.connect(self._stop_thread.quit)
        self._stop_worker.failed.connect(self._stop_thread.quit)
        self._stop_worker.finished.connect(self._stop_worker.deleteLater)
        self._stop_worker.failed.connect(self._stop_worker.deleteLater)
        self._stop_thread.finished.connect(self._stop_thread.deleteLater)
        self._stop_thread.finished.connect(self._on_stop_finished)
        self._stop_worker.failed.connect(self._on_stop_failed)
        self._stop_thread.start()

    def _on_stop_finished(self):
        """Called when the stop worker thread finishes."""
        self._is_stopping = False
        self._stopping_since = 0.0
        self._update_server_status()

    def _on_stop_failed(self, error: str) -> None:
        """Called when the stop worker encounters an error."""
        self._is_stopping = False
        self._stopping_since = 0.0
        self.statusBar().showMessage(f"Stop failed: {error}")
        QMessageBox.warning(
            self,
            "Stop Failed",
            f"Failed to stop the server:\n{error}",
        )
        self._update_server_status()

    def on_open_server(self):
        """Handle Open button click.

        Opens the system web browser to the server URL.
        """
        webbrowser.open(Server.get_base_url())

    def _refresh_status_style(self, widget, status_value: str) -> None:
        """Update a QLabel's status property and trigger style re-evaluation.

        Args:
            widget: The QLabel to update.
            status_value: The status property value (e.g. "running", "error").
        """
        widget.setProperty("status", status_value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _update_server_status(self):
        """Update server status display and button states (called every second).

        The Service groupBox uses a compact row layout:

        Idle / Stopped:
          Row 0:  Status  ○ Idle                          [ Start Server ]

        Running:
          Row 0:  Status  ● Running (92ms)                [ Stop Server  ]
          Row 1:  URL     http://localhost:9876            [ Open ]
          Row 2:  PID     18422     Uptime  00:13:47

        Starting / Stopping transitional states are shown with a warning
        badge and the URL/detail rows hidden.
        """
        status = self._server_manager.get_status()
        status_text, status_prop = self._render_status_state(status)
        self.ui.label_ServiceStatus.setText(status_text)
        self._refresh_status_style(self.ui.label_ServiceStatus, status_prop)
        self._render_status_rows(status)
        self._render_buttons(status)
        self._render_start_tooltip(status)
        self._sync_tray(status)

    def _render_status_state(self, status) -> tuple[str, str]:
        """Return (label text, status property) and surface status-bar messages.

        Tracks the ``_was_healthy`` flag for crash detection and clears the
        ``_is_stopping`` flag once the server has actually stopped.
        """
        if status.healthy:
            self._was_healthy = True
            latency = (
                f" ({status.latency_ms:.0f}ms)" if status.latency_ms is not None else ""
            )
            self.statusBar().clearMessage()
            return f"\u25cf Running{latency}", "running"

        if status.running:
            if self._is_stopping:
                self.statusBar().showMessage("Stopping Aria server\u2026")
                return "\u25cf Stopping\u2026", "warning"
            self.statusBar().showMessage(
                "Starting Aria server\u2026 this may take a few seconds."
            )
            return "\u25cf Starting\u2026", "warning"

        # Idle / stopped
        if self._is_stopping:
            self._is_stopping = False
            self._stopping_since = 0.0
        crashed = self._was_healthy
        self._was_healthy = False
        if crashed:
            self.statusBar().showMessage(
                "Server stopped unexpectedly. Check logs for details.", 10000
            )
        elif self._preflight_result is not None and not self._preflight_result.passed:
            n = len(self._preflight_result.failures)
            self.statusBar().showMessage(
                f"Cannot start: {n} preflight check(s) failed. "
                "Hover over Start button for details."
            )
        else:
            self.statusBar().clearMessage()
        return "\u25cb Idle", "idle"

    def _render_status_rows(self, status) -> None:
        """Update the URL, PID, and uptime rows from server status."""
        self.ui.label_ServiceURL.setText(
            f'<a href="{Server.get_base_url()}">{Server.get_base_url()}</a>'
        )
        self.ui.label_ServiceURL.setOpenExternalLinks(True)
        self.ui.label_ServicePID.setText(str(status.pid) if status.pid else "-")
        if status.uptime_seconds is not None:
            hours, remainder = divmod(int(status.uptime_seconds), 3600)
            minutes, seconds = divmod(remainder, 60)
            self.ui.label_ServiceUptime.setText(
                f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            )
        else:
            self.ui.label_ServiceUptime.setText("-")

    def _render_buttons(self, status) -> None:
        """Enable/disable service buttons based on server and preflight state.

        A 30-second safety timeout resets a stuck ``_is_stopping`` flag so
        the buttons cannot lock up if the stop worker never reports back.
        """
        preflight_ok = (
            self._preflight_result is not None and self._preflight_result.passed
        )
        can_start = not status.running and preflight_ok

        if self._is_stopping and time.monotonic() - self._stopping_since > 30:
            self._is_stopping = False
            self._stopping_since = 0.0

        if self._is_stopping:
            self.ui.pushButton_ServiceStart.setEnabled(False)
            self.ui.pushButton_ServiceStop.setEnabled(False)
        else:
            self.ui.pushButton_ServiceStart.setEnabled(
                can_start and not self._preflight_running
            )
            self.ui.pushButton_ServiceStop.setEnabled(status.healthy)

        self.ui.pushButton_ServiceOpen.setEnabled(status.healthy)

    def _render_start_tooltip(self, status) -> None:
        """Set the Start button tooltip from the current preflight state."""
        if self._preflight_running:
            self.ui.pushButton_ServiceStart.setToolTip(
                "Preflight checks are running\u2026"
            )
            return

        preflight_ok = (
            self._preflight_result is not None and self._preflight_result.passed
        )
        if status.running or preflight_ok:
            self.ui.pushButton_ServiceStart.setToolTip("")
            return

        if self._preflight_result is not None:
            failures = "\n".join(
                f"  \u2022 {c.name}: {c.error}" for c in self._preflight_result.failures
            )
            self.ui.pushButton_ServiceStart.setToolTip(
                f"Cannot start \u2014 fix these issues first:\n{failures}"
            )
        else:
            self.ui.pushButton_ServiceStart.setToolTip(
                "Cannot start \u2014 preflight checks have not run yet"
            )

    def _sync_tray(self, status) -> None:
        """Mirror server state to the tray icon, if it has been created.

        The tray icon is created late in MainWindow init (after the server
        timer starts), so the first timer tick may fire before it exists.
        """
        tray = getattr(self, "_tray_icon", None)
        if tray is not None:
            tray.update_status(running=status.running, healthy=status.healthy)
