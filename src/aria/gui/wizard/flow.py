"""First-run gating and the wizard driver."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from PySide6.QtWidgets import QWizard

from aria.gui.wizard.db import _has_admin_user, _is_model_downloaded
from aria.gui.wizard.pages import SetupWizard, _ConnectionPage, _UserPage

if TYPE_CHECKING:
    from aria.gui.windows.main_window import MainWindow


def should_show_wizard() -> bool:
    """Check if the first-run wizard should be shown.

    Returns True when any setup step is incomplete:

    1. No users in the database
    2. No NVIDIA GPU → remote mode required:
       Chat.api_url, Chat.model, and Vllm.api_key must all be set
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
        conn_page = cast(_ConnectionPage, wizard.page(0))
        if not conn_page.save_connection_config():
            return False

        # Create user only if User page was shown
        if not wizard.has_admin:
            user_page = cast(_UserPage, wizard.page(2))
            return user_page.create_user()

        return True

    return False
