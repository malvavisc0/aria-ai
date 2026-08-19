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

    0. The ``aria init`` completion marker is absent (Decision 3) — the
       wizard **is** the GUI's init path, so a missing marker routes the
       user into it instead of refusing.
    1. No users in the database
    2. Remote mode (``Vllm.remote``):
       Chat.api_url, Chat.model, and Vllm.api_key must all be set
    3. Local mode:
       Chat model must be downloaded
    4. Embeddings model must be downloaded (always)
    5. Lightpanda must be installed (always)

    The gate follows the configured mode, not the physical GPU: a
    remote-configured user on a GPU box must not be looped back into
    the wizard for a local chat model that remote mode never uses.
    """
    from aria.bootstrap import is_init_completed

    if not is_init_completed():
        return True

    if not _has_admin_user():
        return True

    from aria.config.api import Vllm

    if Vllm.remote:
        from aria.config.models import Chat

        if not Chat.api_url or not Chat.model or not Vllm.api_key:
            return True
    else:
        from aria.config.models import Chat

        if not _is_model_downloaded(Chat.model_path):
            return True

    from aria.config.models import Embeddings

    if not _is_model_downloaded(Embeddings.model_path):
        return True

    from aria.config.api import Lightpanda

    if not Lightpanda.is_available():
        return True

    return False


def run_wizard(parent: MainWindow | None = None) -> bool:
    """Show the setup wizard and return True if setup succeeded.

    Returns False if the wizard was cancelled, config save failed,
    or user creation failed. On success the wizard writes the
    ``.init-completed.json`` marker (the same one ``aria init`` writes) so
    the entry-point gate passes for the GUI front-end too, and syncs the
    deployed ``config.toml`` feature flags so the file matches the chosen
    mode immediately (no waiting for the first server start).
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

        # Sync config.toml features + write the init-completed marker so
        # the entry-point gate (§6) passes for the GUI front-end.
        _finalize_init(conn_page)

        # Create user only if User page was shown
        if not wizard.has_admin:
            user_page = cast(_UserPage, wizard.page(2))
            return user_page.create_user()

        return True

    return False


def _finalize_init(conn_page: _ConnectionPage) -> None:
    """Sync config.toml features and write the init-completed marker.

    Runs the GUI's share of the ``aria init`` feature application: the
    connection page already wrote ``ARIA_VLLM_REMOTE`` (+ remote endpoint
    fields) to ``.env``; this mirrors the CLI's step 4 (config.toml sync)
    and step 9 (marker). Binary installs and model downloads happen on
    the dependencies page (full parity with CLI init, §7.2).
    """
    import os
    from pathlib import Path

    from aria.bootstrap import write_init_completed_marker
    from aria.bootstrap.defaults import resolve_defaults
    from aria.bootstrap.detect import detect_hardware
    from aria.bootstrap.features import (
        CHAT_MODE_LOCAL,
        CHAT_MODE_REMOTE,
        vision_enabled_for_config,
    )
    from aria.server.manager import sync_chainlit_features

    aria_home = Path(os.environ.get("ARIA_HOME", Path.home() / ".aria"))
    mode = conn_page.get_connection_mode()
    hardware = detect_hardware()
    vision = vision_enabled_for_config(
        hardware,
        CHAT_MODE_REMOTE if mode == "remote" else CHAT_MODE_LOCAL,
        conn_page.feature_choices(),
    )
    sync_chainlit_features(aria_home, vision_enabled=vision)
    tier = resolve_defaults(hardware) if mode == "local" else None
    write_init_completed_marker(mode, tier)
