"""About dialog for the Aria application."""

from importlib.metadata import version

from PySide6.QtWidgets import QDialog, QWidget

from aria.gui.ui.aboutwindow import Ui_AboutDialog


class AboutDialog(QDialog):
    """Dialog showing application information."""

    @staticmethod
    def _get_version_text() -> str:
        """Return the installed Aria package version for display."""
        return f"v{version('aria-ai')}"

    def __init__(self, parent: QWidget):
        super().__init__(parent=parent)
        self.ui = Ui_AboutDialog()
        self.ui.setupUi(self)
        self.ui.label_Version.setText(self._get_version_text())

        self.ui.pushButton_Ok.clicked.connect(self.accept)
