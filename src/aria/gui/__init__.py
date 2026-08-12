"""Aria GUI application.

This package provides the graphical user interface for the Aria application,
including the main window and various dialogs.

Example usage:
    from aria.gui import main

    main()
"""

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

__all__ = ["main"]


def _install_exception_hook() -> None:
    """Install a global exception hook that shows error dialogs.

    Without this, unhandled exceptions in Qt slots silently go to stderr
    and the user sees nothing.  The hook displays a critical message box
    with the exception info and logs the full traceback.
    """

    _original_hook = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        # Always log the full traceback to stderr
        _original_hook(exc_type, exc_value, exc_tb)
        # Show a user-friendly dialog (only for real exceptions)
        if exc_type is not None and not issubclass(exc_type, KeyboardInterrupt):
            msg = f"{exc_type.__name__}: {exc_value}"
            QMessageBox.critical(
                None,
                "Unexpected Error",
                f"An unexpected error occurred:\n\n{msg}",
            )

    sys.excepthook = _hook


def main():
    """Launch the Aria GUI application."""
    from aria.initializer import is_initialized, run_initialization

    if not is_initialized():
        run_initialization()

    _install_exception_hook()

    from aria.gui.windows import MainWindow
    from aria.gui.wizard import run_wizard, should_show_wizard

    app = QApplication(sys.argv)
    app.setApplicationName("Aria")
    app.setApplicationDisplayName("Aria")

    # Apply global stylesheet
    from aria.gui.theme import STYLESHEET

    app.setStyleSheet(STYLESHEET)

    window = MainWindow()

    # Show first-run wizard if no users exist yet
    if should_show_wizard():
        if run_wizard(window):
            # Reload env so config picks up wizard-written values
            from aria.config import reload_env

            reload_env()
        window.load_users()

    window.show()

    sys.exit(app.exec())
