"""Tests for aria.llm.utility — shared utility LLM call with thinking disabled.

Verifies that ``utility_completion`` always passes ``enable_thinking: False``,
constructs the correct request shape from config, supports both shared and
self-managed httpx clients, and parses the response content correctly.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from aria.llm.tests.helpers import (
    mock_completion_response,
    mock_httpx_client,
    patch_llm_config,
)
from aria.llm.utility import utility_completion


class TestUtilityCompletion:
    """Tests for utility_completion."""

    @pytest.mark.asyncio
    async def test_returns_content_on_success(self, monkeypatch) -> None:
        patch_llm_config(monkeypatch)
        client = mock_httpx_client(mock_completion_response("A description"))
        result = await utility_completion(
            [{"role": "user", "content": "hi"}],
            max_tokens=100,
            client=client,
        )
        assert result == "A description"

    @pytest.mark.asyncio
    async def test_returns_empty_string_on_null_content(self, monkeypatch) -> None:
        patch_llm_config(monkeypatch)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"choices": [{"message": {"content": None}}]}
        client = mock_httpx_client(resp)
        result = await utility_completion(
            [{"role": "user", "content": "hi"}],
            max_tokens=100,
            client=client,
        )
        assert result == ""

    @pytest.mark.asyncio
    async def test_always_disables_thinking(self, monkeypatch) -> None:
        patch_llm_config(monkeypatch)
        client = mock_httpx_client(mock_completion_response())
        await utility_completion(
            [{"role": "user", "content": "hi"}],
            max_tokens=100,
            client=client,
        )
        body = client.post.call_args[1]["json"]
        assert body["chat_template_kwargs"] == {"enable_thinking": False}

    @pytest.mark.asyncio
    async def test_passes_max_tokens(self, monkeypatch) -> None:
        patch_llm_config(monkeypatch)
        client = mock_httpx_client(mock_completion_response())
        await utility_completion(
            [{"role": "user", "content": "hi"}],
            max_tokens=777,
            client=client,
        )
        body = client.post.call_args[1]["json"]
        assert body["max_tokens"] == 777

    @pytest.mark.asyncio
    async def test_omits_temperature_when_none(self, monkeypatch) -> None:
        """When temperature is None, the field is omitted so the server uses its default."""
        patch_llm_config(monkeypatch)
        client = mock_httpx_client(mock_completion_response())
        await utility_completion(
            [{"role": "user", "content": "hi"}],
            max_tokens=100,
            client=client,
        )
        body = client.post.call_args[1]["json"]
        assert "temperature" not in body

    @pytest.mark.asyncio
    async def test_sends_explicit_temperature(self, monkeypatch) -> None:
        """When temperature is provided, it is included in the payload."""
        patch_llm_config(monkeypatch)
        client = mock_httpx_client(mock_completion_response())
        await utility_completion(
            [{"role": "user", "content": "hi"}],
            max_tokens=100,
            temperature=0.1,
            client=client,
        )
        body = client.post.call_args[1]["json"]
        assert body["temperature"] == 0.1

    @pytest.mark.asyncio
    async def test_builds_correct_request_shape(self, monkeypatch) -> None:
        patch_llm_config(monkeypatch)
        client = mock_httpx_client(mock_completion_response())
        await utility_completion(
            [{"role": "user", "content": "describe"}],
            max_tokens=1024,
            client=client,
        )
        call = client.post.call_args
        assert call[0][0] == "http://test:9090/v1/chat/completions"
        assert call[1]["headers"]["Authorization"] == "Bearer sk-test"
        body = call[1]["json"]
        assert body["model"] == "test-model"
        assert body["messages"] == [{"role": "user", "content": "describe"}]

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self, monkeypatch) -> None:
        patch_llm_config(monkeypatch)
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad request",
            request=MagicMock(),
            response=MagicMock(status_code=400),
        )
        client = mock_httpx_client(resp)
        with pytest.raises(httpx.HTTPStatusError):
            await utility_completion(
                [{"role": "user", "content": "hi"}],
                max_tokens=100,
                client=client,
            )

    @pytest.mark.asyncio
    async def test_creates_own_client_when_none_provided(self, monkeypatch) -> None:
        patch_llm_config(monkeypatch)
        client = mock_httpx_client(mock_completion_response("from own client"))
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)

        result = await utility_completion(
            [{"role": "user", "content": "hi"}],
            max_tokens=100,
            timeout=15.0,
        )
        assert result == "from own client"
