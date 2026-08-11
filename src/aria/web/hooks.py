"""Chainlit webhook handlers for the Aria web UI.

This module provides callback handlers for Chainlit events including:
- Authentication (login/logout)
- Chat session lifecycle (start, resume, end)
- Data layer initialization

These handlers are invoked by Chainlit at various points in the app lifecycle.
"""

from __future__ import annotations

import json
from typing import Any

import chainlit as cl
from chainlit.types import ThreadDict
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from aria.config.database import SQLite as SQLiteConfig
from aria.config.folders import Storage as StorageConfig
from aria.db.auth import verify_password
from aria.db.layer import SQLiteSQLAlchemyDataLayer
from aria.db.local_storage_client import LocalStorageClient
from aria.db.models import User
from aria.web.session import (
    drain_memory,
    restore_chat_history,
    wait_for_initialization,
)
from aria.web.state import _state


class _DataLayerCache:
    instance: SQLiteSQLAlchemyDataLayer | None = None


_cache = _DataLayerCache()


def reset_data_layer_cache() -> None:
    """Clear the cached data layer (called on shutdown)."""
    _cache.instance = None


def get_data_layer_handler() -> SQLiteSQLAlchemyDataLayer:
    """Return a cached SQLite data layer instance.

    The data layer is created once and reused for all subsequent calls.
    The database engine and tables are already initialized at startup
    by lifecycle.py, so no additional setup is needed here.

    Returns:
        SQLiteSQLAlchemyDataLayer: Configured data layer instance.
    """
    if _cache.instance is not None:
        return _cache.instance

    storage_client = LocalStorageClient(
        storage_path=StorageConfig.path, base_url="/storage"
    )
    _cache.instance = SQLiteSQLAlchemyDataLayer(
        conninfo=SQLiteConfig.conn_info,
        storage_provider=storage_client,
        show_logger=True,
    )
    return _cache.instance


async def auth_callback_handler(username: str, password: str) -> cl.User | None:
    """Authenticate a user with username and password.

    Called by Chainlit during login to verify user credentials
    against the database. Returns a Chainlit User object with
    metadata if authentication succeeds, None otherwise.

    Credential failures (unknown user, wrong password) return ``None`` so
    Chainlit shows a normal "invalid credentials" outcome.  Unexpected
    errors (database down, schema issues) are **not** masked as auth
    failures — they are logged at error level and re-raised so a backend
    outage is visible rather than indistinguishable from a bad password.

    Args:
        username: The user's identifier (login name).
        password: The user's password to verify.

    Returns:
        cl.User | None: Authenticated user object with metadata,
            or None if authentication fails.
    """
    try:
        with Session(_state.db_engine) as session:
            user = session.execute(
                select(User).where(User.identifier == username)
            ).scalar_one_or_none()

            if not user:
                logger.debug(f"User not found: {username}")
                return None

            user_password = str(user.password)
            if user_password and verify_password(password, user_password):
                metadata = json.loads(str(user.metadata_))
                logger.debug(f"User authenticated: {username}")
                return cl.User(
                    identifier=str(user.identifier),
                    metadata=metadata,
                )

            logger.debug(f"Invalid password for user: {username}")
            return None

    except Exception as e:
        # Backend failure — do not disguise it as an auth failure.
        logger.error(f"Authentication backend error for user {username}: {e}")
        raise


async def on_chat_start_handler() -> None:
    """Handle the start of a new chat session.

    Called by Chainlit when a new chat session begins. Drains and clears
    any stale memory from the previous thread (so its pending embedding
    work is not orphaned) and sets up custom commands available in the
    chat interface.
    """
    await drain_memory(cl.user_session.get("memory"))
    cl.user_session.set("memory", None)
    cl.user_session.set("thread_titled", False)
    logger.debug("Starting new chat session")
    await cl.context.emitter.set_commands(
        [
            {
                "id": "Enhance",
                "icon": "wand-sparkles",
                "description": "Enhance Prompt",
                "button": None,
                "persistent": True,
                "selected": False,
            },
            {
                "id": "Knowledge",
                "icon": "book",
                "description": "Ground answer in your documents",
                "button": None,
                "persistent": True,
                "selected": False,
            },
        ]
    )


async def on_chat_end_handler() -> None:
    """Handle the end of a chat session.

    Called by Chainlit when a chat session ends (user disconnects or
    starts a new chat).  Awaits any in-flight background memory flush so
    the embedding waterfall completes before the session's memory is
    discarded — without this, trimmed-off turns are never persisted to
    Chroma.  See ``docs/fix-chat-resume-freeze.md`` (Fix 1b).
    """
    memory = cl.user_session.get("memory")
    if memory is None:
        return
    await drain_memory(memory)
    cl.user_session.set("memory", None)


async def on_chat_resume_handler(thread: ThreadDict) -> None:
    """Resume an existing chat session with conversation history.

    Called by Chainlit when resuming a previous chat session.
    Restores the chat memory from the thread history so the
    conversation can continue from where it left off.

    Args:
        thread: Thread dictionary containing conversation history
            and metadata from the previous session.
    """
    cl.user_session.set("thread_titled", True)
    try:
        if not _state.is_initialized():
            logger.info(
                "AppState not yet initialized, waiting for startup to complete..."
            )
            if not await wait_for_initialization():
                logger.warning(
                    "AppState initialization timed out after 30s. "
                    "Continuing with empty memory."
                )
                return

        memory = await restore_chat_history(thread)
        cl.user_session.set("memory", memory)
    except Exception as e:
        logger.exception(f"Failed to restore chat history: {e}")


async def on_mcp_connect_handler(connection: Any, client_session: Any) -> None:
    """Register a connected MCP server's ClientSession on the user session."""
    sessions: dict = cl.user_session.get("_mcp_sessions") or {}
    sessions[connection.name] = client_session
    cl.user_session.set("_mcp_sessions", sessions)
    logger.info(f"MCP server connected: {connection.name}")


async def on_mcp_disconnect_handler(name: str, client_session: Any) -> None:
    """Drop a disconnected MCP server from the user session."""
    sessions: dict = cl.user_session.get("_mcp_sessions") or {}
    sessions.pop(name, None)
    cl.user_session.set("_mcp_sessions", sessions)
    logger.info(f"MCP server disconnected: {name}")
