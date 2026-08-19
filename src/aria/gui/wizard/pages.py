"""Wizard pages and the SetupWizard container."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)
from sqlalchemy import select

from aria.gui.wizard.db import _has_admin_user
from aria.gui.wizard.deps_page import _DependenciesPage

if TYPE_CHECKING:
    from aria.gui.windows.main_window import MainWindow


class _ConnectionPage(QWizardPage):
    """Wizard page for connection setup — Local vs Remote mode.

    Uses :func:`aria.bootstrap.detect_hardware` to decide the default and
    whether local mode is offered at all: no NVIDIA GPU (any platform) →
    default remote, disable the local radio. A GPU present keeps the
    current defaults; choosing remote does NOT forfeit the GPU — docling
    and whisper still use it (the status label says so).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("AI Connection")
        self.setSubTitle(
            "Choose how Aria connects to the AI model. "
            "Remote mode is required when no NVIDIA GPU is detected."
        )

        self._hardware = self._detect_hardware()

        layout = QVBoxLayout(self)

        # Connection mode selection
        mode_group = QVBoxLayout()
        mode_group.addWidget(QLabel("Connection Mode:"))

        self._local_radio = QRadioButton("Local (vLLM)")
        mode_group.addWidget(self._local_radio)

        self._remote_radio = QRadioButton("Remote (OpenAI-compatible API)")
        mode_group.addWidget(self._remote_radio)

        if not self._hardware.has_nvidia_gpu:
            # No NVIDIA GPU (any platform) → remote is the only local-capable
            # path. Local chat is refused (Decision 1).
            self._remote_radio.setChecked(True)
            self._local_radio.setEnabled(False)
            self._local_radio.setToolTip("No NVIDIA GPU detected. Use Remote mode.")
        else:
            self._local_radio.setChecked(True)

        layout.addLayout(mode_group)

        # GPU status note (explains remote+GPU still uses the GPU locally).
        self._gpu_note = QLabel(self._gpu_note_text())
        self._gpu_note.setWordWrap(True)
        self._gpu_note.setStyleSheet("color: gray;")
        layout.addWidget(self._gpu_note)

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

        # Feature opt-ins (vision / voice). Voice is hidden entirely when
        # no GPU is present (Decision 5 — CPU voice too slow).

        self._vision_check = QCheckBox("Enable vision (image uploads)")
        self._vision_check.setChecked(
            get_optional_env("ARIA_VLLM_VISION_ENABLED", "").lower() == "true"
        )
        layout.addWidget(self._vision_check)

        self._voice_check = QCheckBox(
            "Enable voice assistant (whisper.cpp + kokoro-tts)"
        )
        self._voice_check.setChecked(
            get_optional_env("ARIA_VOICE_ENABLED", "").lower() == "true"
        )
        if not self._hardware.has_nvidia_gpu:
            self._voice_check.setVisible(False)
        layout.addWidget(self._voice_check)

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

    @staticmethod
    def _detect_hardware():
        from aria.bootstrap.detect import detect_hardware

        return detect_hardware()

    def _gpu_note_text(self) -> str:
        if not self._hardware.has_nvidia_gpu:
            return (
                "No NVIDIA GPU detected — local vLLM is not available. "
                "Use Remote mode; document and voice processing run on CPU."
            )
        gb = self._hardware.vram_mb / 1024
        return (
            f"NVIDIA GPU detected ({gb:.0f} GB VRAM). Choosing Remote does "
            "not forfeit the GPU — local document and voice processing still "
            "use it."
        )

    def feature_choices(self):
        """Return the :class:`FeatureChoices` for the wizard's init finalize."""
        from aria.bootstrap.features import FeatureChoices

        return FeatureChoices(
            vision=self._vision_check.isChecked(),
            voice=self._voice_check.isChecked()
            if self._hardware.has_nvidia_gpu
            else False,
            remote_url=self._endpoint_edit.text().strip(),
            remote_api_key=self._api_key_edit.text().strip(),
            remote_model=self._model_edit.text().strip(),
        )

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
