"""Main window for the Aria application."""

import os
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

from aria.config.folders import Debug
from aria.gui.dialogs import AboutDialog
from aria.gui.tray import TrayIcon
from aria.gui.ui.mainwindow import Ui_MainWindow
from aria.gui.windows.server_handlers import ServerHandlersMixin
from aria.gui.windows.user_handlers import UserHandlersMixin


class MainWindow(
    UserHandlersMixin,
    ServerHandlersMixin,
    QMainWindow,
):
    """Main application window with user management and logs."""

    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        # Hide redundant title label (window title bar shows "Aria")
        self.ui.label_title.hide()

        # Increase minimum height so content is readable
        self.setMinimumSize(600, 650)

        # Make form fields expand to fill available width
        from PySide6.QtWidgets import QFormLayout

        self.ui.formLayout_remote.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        # Set button properties per design system
        self.ui.pushButton_CreateUser.setProperty("primary", True)
        self.ui.pushButton_ServiceStart.setProperty("primary", True)
        self.ui.pushButton_DeleteUser.setProperty("danger", True)
        self.ui.pushButton_ServiceStop.setProperty("warning", True)

        self._connect_menu_signals()
        self._connect_tab_signals()
        self._connect_user_management_signals()

        self._init_server_manager()
        self._connect_server_signals()
        self.ui.pushButton_SaveSettings.clicked.connect(self._save_remote_settings)

        self.load_overview()
        self._run_preflight()

        # Initialize connection mode based on platform
        self._init_connection_mode()

        self._tray_icon = TrayIcon(self)
        self._force_quit = False
        self._wizard: object = None

        # Incremental log reading state
        self._log_file_offset: int = 0
        self._log_filter_active: bool = False

    def _connect_menu_signals(self):
        """Connect menu action signals."""
        self.ui.actionQuit.triggered.connect(self._force_close)
        self.ui.actionAbout.triggered.connect(self.show_about_dialog)

    def _force_close(self):
        """Set force-quit flag and close the window."""
        self._force_quit = True
        self.close()

    def _connect_tab_signals(self):
        """Connect tab-related signals."""
        self.ui.tabWidget.currentChanged.connect(self.on_tab_changed)
        self.ui.pushButton_RefreshLogs.clicked.connect(self.load_logs)
        self.ui.pushButton_AutoRefresh.clicked.connect(self.toggle_auto_refresh)
        self.ui.lineEdit_LogSearch.textChanged.connect(self.load_logs)
        self.ui.comboBox_LogFilter.currentTextChanged.connect(self.load_logs)

        self._logs_timer = QTimer()
        self._logs_timer.timeout.connect(self.load_logs)

    def _connect_user_management_signals(self):
        """Connect user management button signals."""
        self.ui.pushButton_CreateUser.clicked.connect(self.on_create_user_clicked)
        self.ui.pushButton_EditUser.clicked.connect(self.on_edit_user_clicked)
        self.ui.pushButton_DeleteUser.clicked.connect(self.on_delete_user_clicked)

        self.ui.pushButton_CreateUser.setEnabled(False)
        self.ui.lineEdit_UserName.textChanged.connect(self.validate_create_fields)
        self.ui.lineEdit_UserEmail.textChanged.connect(self.validate_create_fields)
        self.ui.lineEdit_UserPassword.textChanged.connect(self.validate_create_fields)
        self.ui.lineEdit_UserPassword.textChanged.connect(
            self._update_password_strength
        )
        self.ui.lineEdit_UserConfirmPassword.textChanged.connect(
            self.validate_create_fields
        )

        self.ui.pushButton_EditUser.setEnabled(False)
        self.ui.pushButton_DeleteUser.setEnabled(False)
        self.ui.listWidget_CurrentUsers.itemSelectionChanged.connect(
            self.validate_user_selection
        )

    def _set_auto_refresh_running(self, running: bool):
        """Update the Auto-Refresh button to reflect the current timer state.

        Args:
            running: True if auto-refresh is active, False if paused.
        """
        if running:
            self.ui.pushButton_AutoRefresh.setText("Pause")
        else:
            self.ui.pushButton_AutoRefresh.setText("Resume")

    def toggle_auto_refresh(self):
        """Toggle the auto-refresh timer on or off."""
        if self._logs_timer.isActive():
            self._logs_timer.stop()
            self._set_auto_refresh_running(False)
        else:
            self.load_logs()
            self._logs_timer.start(5000)
            self._set_auto_refresh_running(True)

    @staticmethod
    def _tail_file(path: Path, max_lines: int = 500) -> list[str]:
        """Read the last *max_lines* lines from *path* efficiently.

        Instead of reading the entire file (which can be very large for a log
        that grows continuously), we seek to the end and read backwards in
        blocks until we have collected enough newline characters.

        Returns:
            A list of at most *max_lines* lines (without trailing newlines).
            An empty list if the file does not exist or cannot be read.
        """
        try:
            with open(path, "rb") as f:
                f.seek(0, 2)  # jump to end
                file_size = f.tell()
                if file_size == 0:
                    return []

                block_size = 8192
                blocks: list[bytes] = []
                remaining = file_size
                newline_count = 0

                while remaining > 0:
                    read_size = min(block_size, remaining)
                    remaining -= read_size
                    f.seek(remaining)
                    block = f.read(read_size)
                    blocks.append(block)
                    newline_count += block.count(b"\n")
                    # +1 because the last line may not end with \n
                    if newline_count >= max_lines + 1:
                        break

                content = b"".join(reversed(blocks))
                lines = content.decode("utf-8", errors="replace").splitlines()
                return lines[-max_lines:]
        except (FileNotFoundError, OSError):
            return []

    def _log_text_color(self) -> QColor:
        """Return the default log text color for the styled light log view."""
        return QColor("#111318")

    def _log_muted_color(self) -> QColor:
        """Return a muted but readable color for INFO lines."""
        return QColor("#62666B")

    def _format_log_line(self, stripped: str):
        """Return (level, color) for a log line."""
        if " ERROR " in stripped or stripped.startswith("ERROR"):
            return "ERROR", QColor("#DC2626")  # --error
        if " WARNING " in stripped or stripped.startswith("WARNING"):
            return "WARNING", QColor("#D97706")  # --warning
        if " INFO " in stripped or stripped.startswith("INFO"):
            return "INFO", self._log_muted_color()
        return "", self._log_text_color()

    def _line_matches_filter(
        self, stripped: str, level: str, search: str, level_filter: str
    ) -> bool:
        """Return True if *stripped* passes both filters."""
        if level_filter == "ERROR" and level != "ERROR":
            return False
        if level_filter == "WARNING" and level not in ("ERROR", "WARNING"):
            return False
        if level_filter == "INFO" and level not in (
            "ERROR",
            "WARNING",
            "INFO",
        ):
            return False
        if search and search not in stripped.lower():
            return False
        return True

    def _append_log_lines(self, lines: list[str]) -> None:
        """Append filtered, color-coded lines to the log viewer."""
        search_text = self.ui.lineEdit_LogSearch.text().lower()
        level_filter = self.ui.comboBox_LogFilter.currentText()

        for line in lines:
            stripped = line.rstrip()
            if not stripped:
                continue
            level, color = self._format_log_line(stripped)
            if not self._line_matches_filter(
                stripped, level, search_text, level_filter
            ):
                continue
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            cursor = self.ui.textEdit_Logs.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(stripped + "\n", fmt)

        self.ui.textEdit_Logs.verticalScrollBar().setValue(
            self.ui.textEdit_Logs.verticalScrollBar().maximum()
        )

    def _reload_logs_full(self) -> None:
        """Full reload: tail the file, clear the viewer, and reset offset."""
        lines = self._tail_file(Debug.logs_path)
        self.ui.textEdit_Logs.clear()
        self._append_log_lines(lines)
        try:
            self._log_file_offset = Debug.logs_path.stat().st_size
        except OSError:
            self._log_file_offset = 0

    def _append_incremental_logs(self) -> None:
        """Read only new bytes since the last read and append them.

        On file truncation/rotation (size shrunk below the last offset),
        falls back to a full reload.
        """
        try:
            file_size = Debug.logs_path.stat().st_size
        except OSError:
            return

        if file_size < self._log_file_offset:
            # File was truncated/rotated — full reload
            self._log_file_offset = 0
            self._reload_logs_full()
            return

        if file_size == self._log_file_offset:
            return  # No new data

        try:
            with open(Debug.logs_path, "rb") as f:
                f.seek(self._log_file_offset)
                new_data = f.read()
                self._log_file_offset = file_size
        except OSError:
            return

        if new_data:
            text = new_data.decode("utf-8", errors="replace")
            self._append_log_lines(text.splitlines())

    def load_logs(self):
        """Load logs with color coding, search, and level filter.

        On first call or when a search/filter is active, reads the last
        500 lines.  During auto-refresh (no active filter), only new bytes
        since the last read are appended — avoiding a full re-read of
        potentially large log files.
        """
        if not Debug.logs_path.exists():
            self.ui.textEdit_Logs.setPlainText("Log file not found.")
            self._log_file_offset = 0
            return

        search_text = self.ui.lineEdit_LogSearch.text().lower()
        level_filter = self.ui.comboBox_LogFilter.currentText()
        has_filter = bool(search_text) or level_filter != "All"
        filter_changed = has_filter != self._log_filter_active

        if has_filter or filter_changed or self._log_file_offset == 0:
            self._reload_logs_full()
        else:
            self._append_incremental_logs()

        self._log_filter_active = has_filter

    def load_overview(self):
        """Load overview tab content from the live .env."""
        from aria.config import get_bool_env, get_optional_env

        api_url = get_optional_env("CHAT_OPENAI_API", "")
        ctx_size = get_optional_env("CHAT_CONTEXT_SIZE", "65536")

        # Update local status
        self.ui.label_LocalEndpointValue.setText(api_url)

        # Populate remote settings
        self.ui.lineEdit_EndpointUrl.setText(api_url)
        self.ui.lineEdit_ApiKey.setText(get_optional_env("ARIA_VLLM_API_KEY", ""))
        self.ui.lineEdit_Model.setText(get_optional_env("CHAT_MODEL", ""))
        self.ui.lineEdit_ContextSize.setText(ctx_size)

        # Reflect the persisted connection mode
        remote = get_bool_env("ARIA_VLLM_REMOTE", False)
        self.ui.radioButton_RemoteMode.setChecked(remote)
        self.ui.radioButton_LocalMode.setChecked(not remote)

    def _save_remote_settings(self):
        """Save connection settings to .env.

        Persists the selected mode and, in remote mode, the endpoint,
        API key, model, and context size. TOKEN_LIMIT_RATIO is left
        untouched — it is configured manually in .env.
        """
        from aria.config import reload_env
        from aria.helpers.dotenv import parse_dotenv, write_dotenv

        env_path = Path(os.environ.get("ARIA_HOME", Path.home() / ".aria")) / ".env"

        values: dict[str, str] = {}
        remote = self.ui.radioButton_RemoteMode.isChecked()
        values["ARIA_VLLM_REMOTE"] = "true" if remote else "false"

        if remote:
            try:
                ctx_size = int(self.ui.lineEdit_ContextSize.text().strip())
            except ValueError:
                QMessageBox.warning(
                    self, "Invalid Context Size", "Context Size must be an integer."
                )
                return
            values["CHAT_OPENAI_API"] = self.ui.lineEdit_EndpointUrl.text().strip()
            values["ARIA_VLLM_API_KEY"] = self.ui.lineEdit_ApiKey.text().strip()
            values["CHAT_MODEL"] = self.ui.lineEdit_Model.text().strip()
            values["CHAT_CONTEXT_SIZE"] = str(ctx_size)

        _, raw_lines = parse_dotenv(env_path)
        write_dotenv(env_path, values, raw_lines)
        reload_env()

        self.load_overview()
        self.statusBar().showMessage("Settings saved.", 5000)

    def _init_connection_mode(self):
        """Connect mode radio signals; on macOS vLLM is unavailable."""
        import sys

        self.ui.radioButton_RemoteMode.toggled.connect(self._on_connection_mode_toggled)
        self.ui.radioButton_LocalMode.toggled.connect(self._on_connection_mode_toggled)

        if sys.platform == "darwin":
            self.ui.radioButton_LocalMode.setEnabled(False)
            self.ui.radioButton_LocalMode.setToolTip("vLLM is not supported on macOS.")
            self.ui.radioButton_RemoteMode.setChecked(True)

        self._on_connection_mode_toggled(self.ui.radioButton_RemoteMode.isChecked())

    def _on_connection_mode_toggled(self, _checked: bool):
        """Handle connection mode radio button toggle.

        The Save Settings button writes remote-mode fields, so it is only
        reachable in remote mode — in local mode only the mode flag would
        be persisted, so the button is hidden to avoid a misleading no-op.
        """
        remote = self.ui.radioButton_RemoteMode.isChecked()
        self.ui.frame_RemoteSettings.setVisible(remote)
        self.ui.pushButton_SaveSettings.setVisible(remote)
        self.ui.frame_LocalStatus.setVisible(not remote)

    def on_tab_changed(self, index: int):
        """Handle tab changes - load content when tabs are selected."""
        match self.ui.tabWidget.widget(index):
            case self.ui.tab_home:
                self._logs_timer.stop()
                self.statusBar().clearMessage()
                self.load_overview()
                self._run_preflight()
            case self.ui.tab_users:
                self._logs_timer.stop()
                self.statusBar().clearMessage()
                self.load_users()
            case self.ui.tab_logs:
                self.load_logs()
                self._logs_timer.start(5000)
                self._set_auto_refresh_running(True)
                self.statusBar().showMessage(str(Debug.logs_path))
            case _:
                self._logs_timer.stop()
                self.statusBar().clearMessage()

    def show_about_dialog(self):
        """Show the About dialog."""
        dialog = AboutDialog(self)
        dialog.exec()

    def closeEvent(self, event):
        """Minimize to tray or clean up on forced quit.

        When the user closes the window, it is hidden and continues
        running in the system tray. A forced quit (via tray menu or
        Ctrl+Q) sets ``_force_quit`` to True to skip this behaviour.
        """
        if not self._force_quit:
            event.ignore()
            self.hide()
            return

        # Close wizard if open (it runs a nested event loop)
        wizard = getattr(self, "_wizard", None)
        if wizard is not None:
            wizard.reject()

        self._server_manager.stop()
        self._server_timer.stop()
        self._tray_icon.hide()

        super().closeEvent(event)
        QApplication.quit()
