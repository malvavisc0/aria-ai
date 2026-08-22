from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aria.web import prompt_builder as pipeline


def _mock_message(**kwargs: Any) -> Any:
    """Create a mock cl.Message from keyword attributes."""
    return SimpleNamespace(**kwargs)


def _patch_no_mcp_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    from aria.tools import mcp_bridge

    monkeypatch.setattr(mcp_bridge, "connected_server_names", lambda: [])


class TestDescribeImage:
    """Tests for the describe_image helper."""

    @staticmethod
    def _patch_chat_config(monkeypatch):
        """Set ChatConfig attributes for tests (bypasses _Lazy descriptors).

        _Lazy is a non-data descriptor that caches its value internally.
        We patch the _value attribute directly to avoid triggering the
        factory (which requires env vars that aren't set in tests).
        """
        from aria.config.models import Chat as ChatConfigCls

        monkeypatch.setattr(
            ChatConfigCls.__dict__["api_url"], "_value", "http://test:9090/v1"
        )
        monkeypatch.setattr(ChatConfigCls.__dict__["model"], "_value", "test-model")
        monkeypatch.setattr(pipeline.VllmConfig, "api_key", "sk-test")

    @staticmethod
    def _mock_client(response: MagicMock) -> AsyncMock:
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        return client

    @pytest.mark.asyncio
    async def test_returns_description_on_success(self, monkeypatch) -> None:
        self._patch_chat_config(monkeypatch)

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "A screenshot of a dashboard."}}]
        }

        client = self._mock_client(mock_response)

        result = await pipeline.describe_image(client, "image/png", "base64data")
        assert result == "A screenshot of a dashboard."

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self, monkeypatch) -> None:
        import httpx as real_httpx

        self._patch_chat_config(monkeypatch)

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = real_httpx.HTTPStatusError(
            "Bad request",
            request=MagicMock(),
            response=MagicMock(status_code=400),
        )

        client = self._mock_client(mock_response)

        with pytest.raises(real_httpx.HTTPStatusError):
            await pipeline.describe_image(client, "image/jpeg", "base64data")

    @pytest.mark.asyncio
    async def test_sends_correct_payload(self, monkeypatch) -> None:
        self._patch_chat_config(monkeypatch)

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "desc"}}]
        }

        client = self._mock_client(mock_response)

        await pipeline.describe_image(client, "image/png", "abc123")

        call_kwargs = client.post.call_args
        url = call_kwargs[0][0]
        assert url == "http://test:9090/v1/chat/completions"

        headers = call_kwargs[1]["headers"]
        assert headers["Authorization"] == "Bearer sk-test"

        body = call_kwargs[1]["json"]
        assert body["model"] == "test-model"
        # Thinking is disabled per-request so the model's CoT doesn't eat
        # the entire token budget and leave content=null.
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        assert body["max_tokens"] == 1024
        content = body["messages"][0]["content"]
        assert content[1]["image_url"]["url"] == "data:image/png;base64,abc123"


class TestHandleMessageVision:
    """Tests for handle_message vision image processing."""

    @pytest.mark.asyncio
    async def test_appends_image_descriptions_when_vision_enabled(
        self, monkeypatch
    ) -> None:
        _patch_no_mcp_servers(monkeypatch)
        monkeypatch.setattr(pipeline.VllmConfig, "vision_enabled", True)
        monkeypatch.setattr(
            pipeline,
            "extract_image_data",
            lambda msg: [{"mime_type": "image/png", "base64": "b64", "name": "a.png"}],
        )
        monkeypatch.setattr(pipeline, "extract_file_paths", lambda msg: [])
        monkeypatch.setattr(
            pipeline,
            "describe_image",
            AsyncMock(return_value="A red circle on white background."),
        )

        message = _mock_message(
            content="What is this?",
            command=None,
            thread_id="t1",
            elements=[],
        )

        prompt, meta = await pipeline.handle_message(message)

        assert "[Attached images]:" in prompt
        assert "[Image 1 (a.png)]: A red circle on white background." in prompt
        assert meta == {}

    @pytest.mark.asyncio
    async def test_omits_image_block_when_vision_off(self, monkeypatch) -> None:
        """When vision is disabled, image placeholders are NOT injected —
        a ``<vision disabled>`` notice would be noise the model can't act on."""
        _patch_no_mcp_servers(monkeypatch)
        monkeypatch.setattr(pipeline.VllmConfig, "vision_enabled", False)
        monkeypatch.setattr(
            pipeline,
            "extract_image_data",
            lambda msg: [
                {"mime_type": "image/png", "base64": "b64", "name": "pic.png"}
            ],
        )
        monkeypatch.setattr(pipeline, "extract_file_paths", lambda msg: [])

        message = _mock_message(
            content="Look at this",
            command=None,
            thread_id="t1",
            elements=[],
        )

        prompt, meta = await pipeline.handle_message(message)

        assert "[Attached images]:" not in prompt
        assert "vision disabled" not in prompt
        assert "ARIA_VLLM_VISION_ENABLED" not in prompt

    @pytest.mark.asyncio
    async def test_no_image_block_when_no_images(self, monkeypatch) -> None:
        _patch_no_mcp_servers(monkeypatch)
        monkeypatch.setattr(pipeline, "extract_image_data", lambda msg: [])
        monkeypatch.setattr(pipeline, "extract_file_paths", lambda msg: [])

        message = _mock_message(
            content="Just text",
            command=None,
            thread_id="t1",
            elements=[],
        )

        prompt, meta = await pipeline.handle_message(message)

        assert "[Attached images]:" not in prompt
        assert "Thread ID" not in prompt
        assert meta == {}

    @pytest.mark.asyncio
    async def test_fallback_when_vision_api_fails(self, monkeypatch) -> None:
        _patch_no_mcp_servers(monkeypatch)
        monkeypatch.setattr(pipeline.VllmConfig, "vision_enabled", True)
        monkeypatch.setattr(
            pipeline,
            "extract_image_data",
            lambda msg: [
                {"mime_type": "image/png", "base64": "b64", "name": "fail.png"}
            ],
        )
        monkeypatch.setattr(pipeline, "extract_file_paths", lambda msg: [])
        monkeypatch.setattr(
            pipeline,
            "describe_image",
            AsyncMock(side_effect=Exception("connection refused")),
        )

        message = _mock_message(
            content="What's this?",
            command=None,
            thread_id="t3",
            elements=[],
        )

        prompt, meta = await pipeline.handle_message(message)

        assert "[Attached images]:" in prompt
        assert "<description unavailable>" in prompt


class TestAppendMcpBlock:
    """Tests for the per-turn connected-MCP-servers prompt injection."""

    def test_no_servers_leaves_prompt_unchanged(self, monkeypatch) -> None:
        from aria.tools import mcp_bridge

        monkeypatch.setattr(mcp_bridge, "connected_server_names", lambda: [])
        assert pipeline.append_mcp_block("hello") == "hello"

    def test_appends_server_names_only(self, monkeypatch) -> None:
        from aria.tools import mcp_bridge

        monkeypatch.setattr(
            mcp_bridge,
            "connected_server_names",
            lambda: ["github", "db"],
        )
        out = pipeline.append_mcp_block("hello")
        assert "[Connected MCP servers]" in out
        assert "- github" in out
        assert "- db" in out
        assert "list-repos" not in out
        assert 'command="call"' in out
        assert '"tool": "<exact tool name>"' in out

    @pytest.mark.asyncio
    async def test_handle_message_appends_mcp_block(self, monkeypatch) -> None:
        from aria.tools import mcp_bridge

        monkeypatch.setattr(pipeline, "extract_image_data", lambda msg: [])
        monkeypatch.setattr(pipeline, "extract_file_paths", lambda msg: [])
        monkeypatch.setattr(
            mcp_bridge,
            "connected_server_names",
            lambda: ["github"],
        )
        message = _mock_message(
            content="do something",
            command=None,
            thread_id="t1",
            elements=[],
        )
        prompt, meta = await pipeline.handle_message(message)
        assert "[Connected MCP servers]" in prompt
        assert "- github" in prompt
        assert meta == {}


class TestAppendFilesBlock:
    """Tests for append_files_block — [Uploaded files] prompt block."""

    @pytest.mark.asyncio
    async def test_no_block_when_no_files(self) -> None:
        """Empty file list leaves the prompt unchanged."""
        assert await pipeline.append_files_block("hello", []) == "hello"

    @pytest.mark.asyncio
    async def test_lists_file_paths(self) -> None:
        """Block contains each file path on its own line."""
        result = await pipeline.append_files_block(
            "prompt", ["/tmp/a.txt", "/tmp/b.pdf"]
        )
        assert "[Uploaded files]:" in result
        assert "/tmp/a.txt" in result
        assert "/tmp/b.pdf" in result

    @pytest.mark.asyncio
    async def test_no_routing_guidance(self) -> None:
        """Block does not contain agent-facing tool routing instructions."""
        result = await pipeline.append_files_block("p", ["/tmp/a.txt"])
        assert "read_file" not in result
        assert "ax documents" not in result
