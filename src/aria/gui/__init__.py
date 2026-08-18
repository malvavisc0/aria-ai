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


def _init_logging() -> None:
    """Add the shared log file sink so GUI-side events reach the Logs tab.

    The web server process configures the same file independently; without
    this, GUI events (first launch, preflight, start/stop failures) only
    reach stderr and the Logs tab is empty until the server process runs.
    """
    from loguru import logger

    from aria.config.folders import LOG_FORMAT, Debug

    logger.add(
        str(Debug.logs_path),
        rotation="10 MB",
        level="INFO",
        format=LOG_FORMAT,
    )


def main():
    """Launch the Aria GUI application."""
    from aria.initializer import (
        is_initialized,
        run_initialization,
        setup_chainlit_config,
        setup_public_assets,
    )

    if not is_initialized():
        run_initialization()

    # Idempotent — mirrors the aria CLI entry point so a home created by
    # other means (pre-seeded .env, partial init) still gets its assets.
    setup_public_assets()
    setup_chainlit_config()

    _init_logging()
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

    # Show first-run wizard if setup is incomplete. A database error
    # here must not kill the GUI before it opens — fail into the wizard
    # path (the old behavior) and log the cause.
    try:
        show_wizard = should_show_wizard()
    except Exception as e:
        from loguru import logger

        logger.exception("Setup check failed — falling back to first-run wizard")
        QMessageBox.warning(
            window,
            "Setup Check Failed",
            f"Could not verify the installation state:\n\n{e}\n\n"
            "The setup wizard will run instead.",
        )
        show_wizard = True

    if show_wizard:
        if run_wizard(window):
            # Reload env so config picks up wizard-written values
            from aria.config import reload_env

            reload_env()
        window.load_users()

    window.show()

    sys.exit(app.exec())
