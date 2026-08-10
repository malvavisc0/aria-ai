from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from aria.llm.tests.helpers import mock_httpx_client, patch_llm_config
from aria.web import thread_titler


def _patch_emitter(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patch cl.context.emitter.emit so tests don't need a Chainlit session."""
    mock_emit = AsyncMock()

    class _FakeEmitter:
        emit = mock_emit

    class _FakeContext:
        emitter = _FakeEmitter()

    import chainlit as cl

    monkeypatch.setattr(cl, "context", _FakeContext(), raising=False)
    return mock_emit


class TestGenerateThreadTitle:
    """Tests for generate_thread_title()."""

    @pytest.mark.asyncio
    async def test_returns_title_on_success(self, monkeypatch) -> None:
        patch_llm_config(monkeypatch)

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Python Deployment Help"}}]
        }

        monkeypatch.setattr(
            httpx, "AsyncClient", lambda **kw: mock_httpx_client(mock_response)
        )

        result = await thread_titler.generate_thread_title(
            "how do I deploy a Flask app?", "You can use gunicorn..."
        )
        assert result == "Python Deployment Help"

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_content(self, monkeypatch) -> None:
        patch_llm_config(monkeypatch)

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": ""}}]}

        monkeypatch.setattr(
            httpx, "AsyncClient", lambda **kw: mock_httpx_client(mock_response)
        )

        result = await thread_titler.generate_thread_title("hey", "hi there")
        assert result is None

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self, monkeypatch) -> None:
        patch_llm_config(monkeypatch)

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad request",
            request=MagicMock(),
            response=MagicMock(status_code=400),
        )

        monkeypatch.setattr(
            httpx, "AsyncClient", lambda **kw: mock_httpx_client(mock_response)
        )

        with pytest.raises(httpx.HTTPStatusError):
            await thread_titler.generate_thread_title("hi", "hello")

    @pytest.mark.asyncio
    async def test_truncates_long_title(self, monkeypatch) -> None:
        patch_llm_config(monkeypatch)

        long_title = "A" * 200
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": long_title}}]
        }

        monkeypatch.setattr(
            httpx, "AsyncClient", lambda **kw: mock_httpx_client(mock_response)
        )

        result = await thread_titler.generate_thread_title("q", "a")
        assert result is not None
        assert len(result) == 80

    @pytest.mark.asyncio
    async def test_sends_correct_payload(self, monkeypatch) -> None:
        patch_llm_config(monkeypatch)

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Title"}}]
        }

        client = mock_httpx_client(mock_response)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)

        await thread_titler.generate_thread_title("question", "answer")

        call_kwargs = client.post.call_args
        assert call_kwargs[0][0] == "http://test:9090/v1/chat/completions"
        assert call_kwargs[1]["headers"]["Authorization"] == "Bearer sk-test"

        body = call_kwargs[1]["json"]
        assert body["model"] == "test-model"
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        assert body["max_tokens"] == 50
        assert body["temperature"] == 0.1
        assert body["messages"][0]["role"] == "system"
        assert "User: question" in body["messages"][1]["content"]
        assert "Assistant: answer" in body["messages"][1]["content"]


class TestMaybeTitleThread:
    """Tests for maybe_title_thread() orchestration."""

    @pytest.mark.asyncio
    async def test_updates_data_layer_on_success(self, monkeypatch) -> None:
        patch_llm_config(monkeypatch)

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Greeting Exchange"}}]
        }

        monkeypatch.setattr(
            httpx, "AsyncClient", lambda **kw: mock_httpx_client(mock_response)
        )

        mock_data_layer = AsyncMock()
        monkeypatch.setattr(
            thread_titler, "get_data_layer_handler", lambda: mock_data_layer
        )

        mock_emit = _patch_emitter(monkeypatch)

        await thread_titler.maybe_title_thread("thread-1", "hi", "hello")

        mock_data_layer.update_thread.assert_awaited_once_with(
            thread_id="thread-1", name="Greeting Exchange"
        )
        mock_emit.assert_awaited_once_with(
            "first_interaction",
            {"interaction": "Greeting Exchange", "thread_id": "thread-1"},
        )

    @pytest.mark.asyncio
    async def test_skips_update_on_empty_title(self, monkeypatch) -> None:
        patch_llm_config(monkeypatch)

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": "  "}}]}

        monkeypatch.setattr(
            httpx, "AsyncClient", lambda **kw: mock_httpx_client(mock_response)
        )

        mock_data_layer = AsyncMock()
        monkeypatch.setattr(
            thread_titler, "get_data_layer_handler", lambda: mock_data_layer
        )

        _patch_emitter(monkeypatch)

        await thread_titler.maybe_title_thread("thread-1", "hi", "hello")

        mock_data_layer.update_thread.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_raise_on_failure(self, monkeypatch) -> None:
        patch_llm_config(monkeypatch)

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )

        monkeypatch.setattr(
            httpx, "AsyncClient", lambda **kw: mock_httpx_client(mock_response)
        )

        mock_data_layer = AsyncMock()
        monkeypatch.setattr(
            thread_titler, "get_data_layer_handler", lambda: mock_data_layer
        )

        _patch_emitter(monkeypatch)

        # Must not raise — the default name is kept.
        await thread_titler.maybe_title_thread("thread-1", "hi", "hello")

        mock_data_layer.update_thread.assert_not_awaited()
