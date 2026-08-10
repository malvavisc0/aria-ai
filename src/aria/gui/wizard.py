"""First-run setup wizard for Aria.

A QWizard-based guided setup that walks new users through:
1. Connection setup (Local vs Remote)
2. Download dependencies (Lightpanda, embeddings model)
3. Create admin user
4. Finish

The wizard is shown automatically on first run when no users exist.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal
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
        from aria.config.models import Chat

        self._endpoint_edit = QLineEdit()
        self._endpoint_edit.setPlaceholderText("https://api.openai.com/v1")
        self._endpoint_edit.setText(Chat.api_url or "https://api.openai.com/v1")
        self._remote_container.addWidget(QLabel("Endpoint:"))
        self._remote_container.addWidget(self._endpoint_edit)

        # API Key
        from aria.config.api import Vllm

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("sk-...")
        self._api_key_edit.setText(Vllm.api_key or "")
        self._remote_container.addWidget(QLabel("API Key:"))
        self._remote_container.addWidget(self._api_key_edit)

        # Model name
        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText("auto")
        self._model_edit.setText(Chat.model or "")
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
        for i in range(1, self._remote_container.count()):
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
        """Save connection configuration to .env file.

        Uses the correct env var names expected by aria.config.api.Vllm
        and aria.config.models.Chat. Preserves comments and blank lines.
        """
        from pathlib import Path

        try:
            import os

            aria_home = Path(os.environ.get("ARIA_HOME", Path.home() / ".aria"))
            env_path = aria_home / ".env"
            env_path.parent.mkdir(parents=True, exist_ok=True)

            mode = self.get_connection_mode()

            # Build the updates using the correct variable names
            updates: dict[str, str] = {}
            if mode == "remote":
                updates["ARIA_VLLM_REMOTE"] = "true"
                updates["CHAT_OPENAI_API"] = self._endpoint_edit.text().strip()
                updates["ARIA_VLLM_API_KEY"] = self._api_key_edit.text().strip()
                updates["CHAT_MODEL"] = self._model_edit.text().strip()
            else:
                updates["ARIA_VLLM_REMOTE"] = ""

            # Read existing .env preserving comments and structure
            lines: list[str] = []
            keys_written: set[str] = set()
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    stripped = line.strip()
                    # Preserve comments and blank lines
                    if not stripped or stripped.startswith("#"):
                        lines.append(line)
                        continue
                    if "=" in stripped:
                        key = stripped.split("=", 1)[0].strip()
                        if key in updates:
                            lines.append(f"{key} = {updates[key]}")
                            keys_written.add(key)
                        else:
                            lines.append(line)
                    else:
                        lines.append(line)

            # Append any new keys not already in the file
            for key, value in updates.items():
                if key not in keys_written:
                    lines.append(f"{key} = {value}")

            env_path.write_text("\n".join(lines) + "\n")
            return True
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Configuration Error",
                f"Could not save connection settings:\n{exc}",
            )
            return False


# ---------------------------------------------------------------------------
# Background workers for dependency downloads
# ---------------------------------------------------------------------------


class _PreflightWorker(QObject):
    """Run preflight checks off the GUI thread."""

    finished = Signal(object)

    def run(self):
        from aria.preflight import run_preflight_checks

        self.finished.emit(run_preflight_checks())


class _DownloadWorker(QObject):
    """Download a single dependency off the GUI thread."""

    finished = Signal(bool, str)  # (success, message)

    def __init__(self, target: str):
        super().__init__()
        self._target = target

    def run(self):
        try:
            if self._target == "lightpanda":
                from aria.config.api import Lightpanda
                from aria.scripts.lightpanda import download_lightpanda

                download_lightpanda(
                    bin_dir=Lightpanda.get_bin_path(),
                    version=Lightpanda.version,
                )
                self.finished.emit(True, "Lightpanda installed.")
            elif self._target == "embeddings":
                from os import getenv

                from huggingface_hub import snapshot_download

                from aria.config.huggingface import HuggingFace
                from aria.config.models import Embeddings

                repo_id = getenv("EMBED_MODEL_PATH", "")
                local_dir = Embeddings.model_path
                token = HuggingFace.token
                snapshot_download(
                    repo_id=repo_id,
                    local_dir=local_dir,
                    token=token,
                )
                self.finished.emit(True, "Embeddings model downloaded.")
            else:
                self.finished.emit(False, f"Unknown target: {self._target}")
        except Exception as exc:
            self.finished.emit(False, str(exc))


# ---------------------------------------------------------------------------
# Dependencies page
# ---------------------------------------------------------------------------


class _DependenciesPage(QWizardPage):
    """Wizard page that checks and downloads required dependencies.

    Uses ``run_preflight_checks()`` to detect what's missing, then lets
    the user download each item with a button.  ``isComplete()`` returns
    ``True`` only when all required checks pass.
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
        wizard: SetupWizard = self.wizard()  # type: ignore[assignment]
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

    def _on_preflight_done(self, result):
        """Display preflight results and build download buttons."""
        # Clear previous widgets
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

        # Filter for binaries + models categories
        relevant = [c for c in result.checks if c.category in ("binaries", "models")]

        if not relevant:
            self._info_label.setText("No dependencies to check.")
            self._all_ok = True
            self.completeChanged.emit()
            return

        all_passed = True
        for check in relevant:
            row = QHBoxLayout()
            icon = "\u2705" if check.passed else "\u274c"
            label = QLabel(f"{icon}  {check.name}")
            row.addWidget(label)

            if not check.passed:
                all_passed = False
                btn = QPushButton("Download")
                btn.setProperty("dep_name", check.name)
                btn.clicked.connect(lambda checked, n=check.name: self._on_download(n))
                row.addWidget(btn)

            self._status_layout.addLayout(row)

        self._all_ok = all_passed
        if all_passed:
            self._info_label.setText("All dependencies are ready.")
        else:
            self._info_label.setText(
                "Some dependencies are missing. Click Download to install them."
            )
        self.completeChanged.emit()

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


def _has_admin_user() -> bool:
    """Return True if at least one admin user exists in the database."""
    try:
        from aria.cli import get_db_session
        from aria.db.models import User

        with get_db_session() as session:
            users = session.execute(select(User)).scalars().all()
            return len(users) > 0
    except Exception:
        return False


def _is_model_downloaded(model_path: str) -> bool:
    """Check if a model directory exists and is non-empty."""
    from pathlib import Path

    p = Path(model_path)
    return p.exists() and any(p.iterdir())


def should_show_wizard() -> bool:
    """Check if the first-run wizard should be shown.

    Returns True when any setup step is incomplete:

    1. No users in the database
    2. No NVIDIA GPU → remote mode required:
       Chat.api_url, Chat.model, and Vllm.api_key must be set
    3. NVIDIA GPU present → local mode:
       Chat model must be downloaded
    4. Embeddings model must be downloaded (always)
    5. Lightpanda must be installed (always)
    """
    from aria.helpers.nvidia import check_nvidia_smi_available

    # 1. No users in DB → always show
    if not _has_admin_user():
        return True

    has_nvidia = check_nvidia_smi_available()

    if not has_nvidia:
        # 2. No NVIDIA → remote mode required
        from aria.config.api import Vllm
        from aria.config.models import Chat

        if not Chat.api_url or not Chat.model or not Vllm.api_key:
            return True
    else:
        # 3. NVIDIA present → chat model must be downloaded
        from aria.config.models import Chat

        if not _is_model_downloaded(Chat.model_path):
            return True

    # 4. Embeddings model must be downloaded
    from aria.config.models import Embeddings

    if not _is_model_downloaded(Embeddings.model_path):
        return True

    # 5. Lightpanda must be installed
    from aria.config.api import Lightpanda

    if not Lightpanda.is_available():
        return True

    return False


def run_wizard(parent: MainWindow | None = None) -> bool:
    """Show the setup wizard and return True if setup succeeded.

    Returns False if the wizard was cancelled, config save failed,
    or user creation failed.
    """
    wizard = SetupWizard(parent)

    # Store reference so closeEvent can reject the wizard on force-quit
    if parent is not None:
        parent._wizard = wizard

    result = wizard.exec()

    if result == QWizard.DialogCode.Accepted:
        # Save connection config
        conn_page: _ConnectionPage = wizard.page(0)  # type: ignore[assignment]
        if not conn_page.save_connection_config():
            return False

        # Create user only if User page was shown
        if not wizard.has_admin:
            user_page: _UserPage = wizard.page(2)  # type: ignore[assignment]
            return user_page.create_user()

        return True

    return False
