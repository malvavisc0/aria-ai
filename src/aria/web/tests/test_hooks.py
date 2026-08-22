"""Tests for aria.web.hooks — Chainlit lifecycle handlers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from chainlit.types import ThreadDict

from aria.web import hooks as hooks_mod


@pytest.fixture
def stub_context(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Provide an observable stub session whose thread_id we can inspect."""
    session = SimpleNamespace(thread_id="stale-thread")
    monkeypatch.setattr(
        hooks_mod.cl,
        "context",
        SimpleNamespace(session=session),
    )
    monkeypatch.setattr(
        hooks_mod.cl,
        "user_session",
        SimpleNamespace(get=lambda k: None, set=lambda k, v: None),
    )
    return session


@pytest.mark.asyncio
async def test_on_chat_resume_sets_session_thread_id(
    stub_context: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After resume the session thread id points at the resumed thread.

    Every ``cl.Message`` in the session stamps ``thread_id`` from the
    session, so without this the assistant's answer is written to a fresh
    random thread while the user message lands in the resumed one.
    """
    monkeypatch.setattr(hooks_mod._state.__class__, "is_initialized", lambda self: True)
    monkeypatch.setattr(
        hooks_mod, "restore_chat_history", AsyncMock(return_value=MagicMock())
    )
    monkeypatch.setattr("aria.web.supervisor.ensure_watching", AsyncMock())

    thread = cast(ThreadDict, {"id": "resumed-thread", "name": "T", "steps": []})
    await hooks_mod.on_chat_resume_handler(thread)

    assert stub_context.thread_id == "resumed-thread"


@pytest.mark.asyncio
async def test_on_chat_resume_returns_without_setting_when_not_initialized(
    stub_context: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timed-out initialization aborts before touching the thread id."""
    monkeypatch.setattr(
        hooks_mod._state.__class__, "is_initialized", lambda self: False
    )
    monkeypatch.setattr(
        hooks_mod, "wait_for_initialization", AsyncMock(return_value=False)
    )

    thread = cast(ThreadDict, {"id": "resumed-thread", "name": "T", "steps": []})
    await hooks_mod.on_chat_resume_handler(thread)

    assert stub_context.thread_id == "stale-thread"
