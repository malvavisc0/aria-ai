"""Shared test helpers for LLM-layer and web-layer tests that patch config.

Centralises the ``_Lazy``-descriptor bypass and mock-client factories so
they don't drift across test files.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def patch_llm_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch ChatConfig/VllmConfig for tests (bypasses _Lazy descriptors).

    Sets ``ChatConfig.api_url``, ``ChatConfig.model``, and
    ``VllmConfig.api_key`` to deterministic test values without requiring
    environment variables.
    """
    from aria.config.api import Vllm as VllmConfig
    from aria.config.models import Chat as ChatConfigCls

    monkeypatch.setattr(
        ChatConfigCls.__dict__["api_url"], "_value", "http://test:9090/v1"
    )
    monkeypatch.setattr(ChatConfigCls.__dict__["model"], "_value", "test-model")
    monkeypatch.setattr(VllmConfig, "api_key", "sk-test")


def mock_httpx_client(response: MagicMock) -> AsyncMock:
    """Create a fake httpx.AsyncClient whose ``post`` returns *response*.

    Includes ``__aenter__``/``__aexit__`` so the mock works both as a
    passed-in client and as an ``async with`` context manager.
    """
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def mock_completion_response(content: str = "hello") -> MagicMock:
    """Mock an OpenAI ``/chat/completions`` response with the given content."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp
