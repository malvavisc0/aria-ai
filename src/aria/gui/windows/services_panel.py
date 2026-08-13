"""Services overview panel for the MainWindow Home tab.

This module provides a mixin class that renders per-service status pills
(Web UI, vLLM, Whisper, Kokoro, Lightpanda, Docling) in the Services
groupBox, probed with fast TCP-connect checks.
"""

from __future__ import annotations

from aria.gui.ui.mainwindow import Ui_MainWindow


class ServicesPanelMixin:
    """Mixin class providing the Services panel rendering for MainWindow.

    Expects to be combined with ``ServerHandlersMixin`` (for
    ``_refresh_status_style``) and a QMainWindow that has a ``ui``
    attribute of type ``Ui_MainWindow``.
    """

    ui: Ui_MainWindow

    @staticmethod
    def _port_open(port: int, host: str = "127.0.0.1") -> bool:
        """Return True if something is listening on *port* (fast TCP probe)."""
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.3)
        try:
            return sock.connect_ex((host, port)) == 0
        finally:
            sock.close()

    def _set_service_row(self, label, text: str, prop: str) -> None:
        """Set a Services panel row's pill text and status property."""
        label.setText(text)
        self._refresh_status_style(label, prop)

    def _render_daemon_row(self, label, port: int, installed: bool) -> None:
        """Render a daemon-style service row from install state + port probe."""
        if not installed:
            self._set_service_row(label, "○ Not installed", "idle")
        elif self._port_open(port):
            self._set_service_row(label, "● Running", "running")
        else:
            self._set_service_row(label, "○ Down", "error")

    def _render_services_panel(self, status) -> None:
        """Refresh the per-service status pills in the Services panel.

        Sub-services are probed with fast TCP-connect checks on their ports
        (localhost refuses instantly when down, so the 1s timer never
        blocks). Docling is an on-demand worker, not a daemon, so it
        reports install state instead of a port probe.
        """
        from aria.config.api import Lightpanda, Vllm, Voice
        from aria.config.models import Chat

        # Web UI mirrors the main server status.
        if status.healthy:
            self._set_service_row(self.ui.label_SvcWebUI, "● Running", "running")
        elif status.running:
            self._set_service_row(self.ui.label_SvcWebUI, "● Starting…", "warning")
        else:
            self._set_service_row(self.ui.label_SvcWebUI, "○ Stopped", "idle")

        # vLLM is unmanaged in remote mode — report that instead of probing.
        if Vllm.remote:
            self._set_service_row(self.ui.label_SvcVllm, "Remote", "idle")
        else:
            self._render_daemon_row(self.ui.label_SvcVllm, Chat.get_port(), True)

        if not Voice.enabled:
            self._set_service_row(self.ui.label_SvcWhisper, "Disabled", "idle")
            self._set_service_row(self.ui.label_SvcKokoro, "Disabled", "idle")
        else:
            self._render_daemon_row(
                self.ui.label_SvcWhisper,
                Voice.whisper_port,
                Voice.get_whisper_binary_path() is not None,
            )
            self._render_daemon_row(
                self.ui.label_SvcKokoro,
                Voice.kokoro_port,
                Voice.is_kokoro_available(),
            )

        self._render_daemon_row(
            self.ui.label_SvcLightpanda,
            Lightpanda.port,
            Lightpanda.is_available(),
        )

        from aria.scripts.docling import is_installed as docling_installed

        if docling_installed():
            self._set_service_row(self.ui.label_SvcDocling, "● Installed", "running")
        else:
            self._set_service_row(self.ui.label_SvcDocling, "○ Not installed", "idle")
