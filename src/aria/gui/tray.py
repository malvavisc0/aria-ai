"""System tray icon for the Aria GUI application."""

from __future__ import annotations

import webbrowser

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from aria.config.service import Server


class TrayIcon:
    """System tray icon with context menu and dynamic server state.

    Call :meth:`update_status` from the server status timer to keep the
    Start / Stop / Open actions enabled or disabled appropriately.

    Args:
        window: The MainWindow instance.
    """

    def __init__(self, window) -> None:
        self._tray = QSystemTrayIcon(window)
        self._tray.setIcon(window.windowIcon())
        self._tray.setToolTip("Aria Service Manager")

        menu = QMenu(window)

        action_show = QAction("Show Window", window)
        action_show.triggered.connect(window.show)
        action_show.triggered.connect(window.raise_)
        action_show.triggered.connect(window.activateWindow)
        menu.addAction(action_show)

        menu.addSeparator()

        self._action_start = QAction("Start Server", window)
        self._action_start.triggered.connect(window.on_start_server)
        menu.addAction(self._action_start)

        self._action_stop = QAction("Stop Server", window)
        self._action_stop.triggered.connect(window.on_stop_server)
        menu.addAction(self._action_stop)

        self._action_open = QAction("Open in Browser", window)
        self._action_open.triggered.connect(
            lambda: webbrowser.open(Server.get_base_url())
        )
        menu.addAction(self._action_open)

        menu.addSeparator()

        action_quit = QAction("Quit", window)
        action_quit.triggered.connect(
            lambda: (setattr(window, "_force_quit", True), window.close())
        )
        menu.addAction(action_quit)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(
            lambda reason: (
                (
                    window.show(),
                    window.raise_(),
                    window.activateWindow(),
                )
                if reason == QSystemTrayIcon.ActivationReason.DoubleClick
                else None
            )
        )
        self._tray.show()

    def hide(self) -> None:
        """Hide the tray icon so QApplication can exit."""
        self._tray.hide()

    def update_status(self, *, running: bool, healthy: bool) -> None:
        """Enable or disable tray actions based on current server state."""
        self._action_start.setEnabled(not running)
        self._action_stop.setEnabled(running)
        self._action_open.setEnabled(healthy)
        status = "Running" if healthy else ("Starting" if running else "Stopped")
        self._tray.setToolTip(f"Aria — {status}")
