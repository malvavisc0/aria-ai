"""Wizard pages and the SetupWizard container."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)
from sqlalchemy import select

from aria.gui.wizard.db import _has_admin_user
from aria.gui.wizard.workers import _DownloadWorker, _PreflightWorker

if TYPE_CHECKING:
    from aria.gui.windows.main_window import MainWindow


class _ConnectionPage(QWizardPage):
    """Wizard page for connection setup — Local vs Remote mode."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("AI Connection")
        self.setSubTitle(
            "Choose how Aria connects to the AI model. "
            "Remote mode is recommended for macOS."
        )

        layout = QVBoxLayout(self)

        # Connection mode selection
        mode_group = QVBoxLayout()
        mode_group.addWidget(QLabel("Connection Mode:"))

        self._local_radio = QRadioButton("Local (vLLM)")
        mode_group.addWidget(self._local_radio)

        self._remote_radio = QRadioButton("Remote (OpenAI-compatible API)")
        mode_group.addWidget(self._remote_radio)

        # macOS auto-detection: default to Remote since vLLM not supported
        import sys

        if sys.platform == "darwin":
            self._remote_radio.setChecked(True)
            self._local_radio.setEnabled(False)
            self._local_radio.setToolTip(
                "vLLM is not supported on macOS. Use Remote mode."
            )
        else:
            self._local_radio.setChecked(True)

        layout.addLayout(mode_group)

        # Remote settings container
        self._remote_container = QVBoxLayout()
        self._remote_container.addWidget(QLabel("Remote Settings:"))

        # Endpoint URL
        from aria.config import get_optional_env

        self._endpoint_edit = QLineEdit()
        self._endpoint_edit.setPlaceholderText("https://api.openai.com/v1")
        self._endpoint_edit.setText(get_optional_env("CHAT_OPENAI_API", ""))
        self._remote_container.addWidget(QLabel("Endpoint:"))
        self._remote_container.addWidget(self._endpoint_edit)

        # API Key
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("sk-...")
        self._api_key_edit.setText(get_optional_env("ARIA_VLLM_API_KEY", ""))
        self._remote_container.addWidget(QLabel("API Key:"))
        self._remote_container.addWidget(self._api_key_edit)

        # Model name
        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText("auto")
        self._model_edit.setText(get_optional_env("CHAT_MODEL", ""))
        self._remote_container.addWidget(QLabel("Model:"))
        self._remote_container.addWidget(self._model_edit)

        layout.addLayout(self._remote_container)

        # Status label
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        layout.addStretch()

        # Connect signals
        self._local_radio.toggled.connect(self._on_mode_changed)
        self._remote_radio.toggled.connect(self._on_mode_changed)
        self._endpoint_edit.textChanged.connect(self._validate)
        self._api_key_edit.textChanged.connect(self._validate)
        self._model_edit.textChanged.connect(self._validate)

        # Initial state
        self._on_mode_changed()

    def _on_mode_changed(self):
        """Show/hide remote settings based on mode selection."""
        is_remote = self._remote_radio.isChecked()
        for i in range(self._remote_container.count()):
            item = self._remote_container.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.setVisible(is_remote)
        self._validate()

    def _validate(self):
        """Validate fields based on mode."""
        errors = []

        if self._remote_radio.isChecked():
            endpoint = self._endpoint_edit.text().strip()
            if not endpoint:
                errors.append("Endpoint URL is required for remote mode.")
            elif not endpoint.startswith(("http://", "https://")):
                errors.append("Endpoint must be a valid HTTP/HTTPS URL.")

            api_key = self._api_key_edit.text().strip()
            if not api_key:
                errors.append("API Key is required for remote mode.")

            model = self._model_edit.text().strip()
            if not model:
                errors.append("Model name is required for remote mode.")

        self._status_label.setText("\n".join(errors) if errors else "")
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        """Return True if the current configuration is valid."""
        if self._local_radio.isChecked():
            return True

        endpoint = self._endpoint_edit.text().strip()
        api_key = self._api_key_edit.text().strip()
        model = self._model_edit.text().strip()

        return (
            bool(endpoint)
            and endpoint.startswith(("http://", "https://"))
            and bool(api_key)
            and bool(model)
        )

    def get_connection_mode(self) -> str:
        """Return 'local' or 'remote'."""
        return "remote" if self._remote_radio.isChecked() else "local"

    def save_connection_config(self) -> bool:
        """Save connection configuration to .env.

        Writes through the shared ``parse_dotenv``/``write_dotenv`` helpers
        (same path as the main window) so comments and structure are
        preserved. ``ARIA_VLLM_REMOTE`` is persisted explicitly for both
        modes.
        """
        import os
        from pathlib import Path

        from aria.helpers.dotenv import parse_dotenv, write_dotenv

        env_path = Path(os.environ.get("ARIA_HOME", Path.home() / ".aria")) / ".env"
        env_path.parent.mkdir(parents=True, exist_ok=True)

        mode = self.get_connection_mode()
        values: dict[str, str] = {
            "ARIA_VLLM_REMOTE": "true" if mode == "remote" else "false",
        }
        if mode == "remote":
            values["CHAT_OPENAI_API"] = self._endpoint_edit.text().strip()
            values["ARIA_VLLM_API_KEY"] = self._api_key_edit.text().strip()
            values["CHAT_MODEL"] = self._model_edit.text().strip()

        try:
            _, raw_lines = parse_dotenv(env_path)
            write_dotenv(env_path, values, raw_lines)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Configuration Error",
                f"Could not save connection settings:\n{exc}",
            )
            return False
        return True


class _DependenciesPage(QWizardPage):
    """Wizard page that checks and downloads installable dependencies.

    Checks that can be installed from the wizard (vLLM, lightpanda, chat
    and embeddings models) gate progression. Other preflight results
    (docling, voice) are shown for information only — they are enforced
    by the main window's preflight gate on the Start button.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Dependencies")
        self.setSubTitle("Download the required dependencies before continuing.")

        layout = QVBoxLayout(self)

        # Status area — populated by preflight results
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
        """Run preflight checks when the page becomes visible."""
        self._info_label.setText("Checking dependencies\u2026")
        self._run_preflight()

    def isComplete(self) -> bool:
        return self._all_ok and not self._downloading

    def nextId(self) -> int:
        """Skip User page if admin already exists."""
        wizard = cast(SetupWizard, self.wizard())
        if wizard.has_admin:
            return 3  # Finish page
        return 2  # User page

    # -- Internal -----------------------------------------------------------

    def _run_preflight(self):
        """Run preflight checks in a background thread."""
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
        """Remove all widgets and layouts from the status area."""
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
        """Display preflight results and build download buttons."""
        self._clear_status_layout()

        # Filter for binaries + models categories
        relevant = [c for c in result.checks if c.category in ("binaries", "models")]

        if not relevant:
            self._info_label.setText("No dependencies to check.")
            self._all_ok = True
            self.completeChanged.emit()
            return

        self._all_ok = all(self._add_check_row(c) for c in relevant)
        warnings = [c for c in relevant if c.warning]
        if not self._all_ok:
            self._info_label.setText("Install the missing dependencies to continue.")
        elif warnings:
            names = ", ".join(c.name for c in warnings)
            self._info_label.setText(
                f"Dependencies are ready. Optional components missing: {names}."
            )
        else:
            self._info_label.setText("All dependencies are ready.")
        self.completeChanged.emit()

    def _add_check_row(self, check) -> bool:
        """Render one dependency row.

        Returns True when the check does not block progression: it passed,
        or it has no installable target and is shown for information only.
        """
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
        """Start downloading the named dependency."""
        target = self._resolve_target(name)
        if not target:
            return

        self._downloading = True
        self.completeChanged.emit()
        self._info_label.setText(f"Downloading {name}\u2026")

        # Disable all download buttons
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
        """Handle download completion — re-run preflight."""
        self._downloading = False
        if ok:
            self._info_label.setText(f"\u2705 {message}")
        else:
            self._info_label.setText(f"\u274c Download failed: {message}")
        # Re-check to update status
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
        return None


class _UserPage(QWizardPage):
    """Wizard page for creating the admin user."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Create Admin User")
        self.setSubTitle(
            "Create your first user account to access the Aria web interface."
        )

        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Your name")
        layout.addRow("Name:", self._name_edit)

        self._email_edit = QLineEdit()
        self._email_edit.setPlaceholderText("you@example.com")
        layout.addRow("Email:", self._email_edit)

        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self._password_edit.setPlaceholderText("Choose a password")
        layout.addRow("Password:", self._password_edit)

        self._confirm_edit = QLineEdit()
        self._confirm_edit.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self._confirm_edit.setPlaceholderText("Confirm password")
        layout.addRow("Confirm:", self._confirm_edit)

        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        layout.addRow(self._error_label)

        self._name_edit.textChanged.connect(self._validate)
        self._email_edit.textChanged.connect(self._validate)
        self._password_edit.textChanged.connect(self._validate)
        self._confirm_edit.textChanged.connect(self._validate)

    def _validate(self):
        name = self._name_edit.text().strip()
        email = self._email_edit.text().strip()
        password = self._password_edit.text()
        confirm = self._confirm_edit.text()

        errors = []
        if not name:
            errors.append("Name is required.")
        if not email or "@" not in email:
            errors.append("A valid e-mail address is required.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")

        self._error_label.setText("\n".join(errors))
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        name = self._name_edit.text().strip()
        email = self._email_edit.text().strip()
        password = self._password_edit.text()
        confirm = self._confirm_edit.text()

        return (
            bool(name)
            and bool(email)
            and "@" in email
            and len(password) >= 6
            and password == confirm
        )

    def create_user(self) -> bool:
        """Create the user in the database.

        Returns True on success, False on failure.
        """
        from aria.cli import get_db_session
        from aria.db.auth import hash_password
        from aria.db.models import User

        try:
            with get_db_session() as session:
                existing = session.execute(
                    select(User).where(
                        User.identifier == self._email_edit.text().strip()
                    )
                ).scalar_one_or_none()

                if existing:
                    QMessageBox.warning(
                        self,
                        "User Exists",
                        "A user with this email already exists.",
                    )
                    return False

                session.add(
                    User(
                        id=str(uuid.uuid4()),
                        display_name=self._name_edit.text().strip(),
                        identifier=self._email_edit.text().strip(),
                        metadata_=json.dumps({"role": "admin", "created_by": "wizard"}),
                        password=hash_password(self._password_edit.text()),
                        createdAt=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    )
                )
            return True
        except Exception as exc:
            QMessageBox.warning(
                self,
                "User Creation Failed",
                f"Could not create user:\n{exc}",
            )
            return False


class _FinishPage(QWizardPage):
    """Final wizard page — ready to start."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("All Set!")
        self.setSubTitle(
            "Aria is ready. Click Finish to close the wizard and "
            "start using the application."
        )

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "You can start the server from the main window "
                "using the Start button in the toolbar."
            )
        )
        layout.addStretch()


class SetupWizard(QWizard):
    """First-run setup wizard for Aria."""

    def __init__(self, parent: MainWindow | None = None):
        super().__init__(parent)
        self.setWindowTitle("Aria Setup Wizard")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumSize(600, 450)

        self.has_admin = _has_admin_user()

        self.setPage(0, _ConnectionPage(self))
        self.setPage(1, _DependenciesPage(self))
        if not self.has_admin:
            self.setPage(2, _UserPage(self))
        self.setPage(3, _FinishPage(self))
