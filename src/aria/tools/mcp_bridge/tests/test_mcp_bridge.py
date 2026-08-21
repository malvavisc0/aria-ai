"""Tests for the MCP bridge (``ax mcp`` family).

Covers the pure-logic branches of ``mcp_bridge``: the connected-server
index, per-server tool enumeration, raw-dict ``call_tool`` forwarding, and
the content-to-text mapping. The chainlit ``ClientSession`` is faked with
``AsyncMock`` so no real MCP server or network is involved.
"""

from __future__ import annotations

import json
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from chainlit.context import ChainlitContextException
from mcp.types import (
    CallToolResult,
    ImageContent,
    ListToolsResult,
    TextContent,
    Tool,
)

from aria.tools import mcp_bridge
from aria.tools.mcp_bridge import (
    _content_to_text,
    call_tool,
    connected_server_names,
    connected_tool_map,
    list_servers,
    list_tools,
    resolve_session,
)


def _decode(result: str) -> dict:
    return json.loads(result)


@pytest.fixture(autouse=True)
def _chainlit_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = ModuleType("chainlit")
    monkeypatch.setitem(sys.modules, "chainlit", module)
    return module


def _make_client(
    tools: list[Tool] | None = None, call_result: CallToolResult | None = None
):
    client = AsyncMock()
    client.list_tools.return_value = ListToolsResult(tools=tools or [])
    client.call_tool.return_value = call_result or CallToolResult(content=[])
    return client


def _make_tool(
    name: str, description: str = "desc", schema: dict | None = None
) -> Tool:
    return Tool(name=name, description=description, inputSchema=schema or {})


class TestListServers:
    """``ax mcp list`` with no server arg — connected-server index."""

    @pytest.mark.asyncio
    async def test_no_sessions_returns_empty_index(self, monkeypatch):
        monkeypatch.setattr(mcp_bridge, "_connected_sessions", lambda: None)
        data = _decode(await list_servers())["data"]
        assert data["servers"] == []
        assert "No MCP servers" in data["hint"]

    @pytest.mark.asyncio
    async def test_empty_sessions_returns_empty_index(self, monkeypatch):
        monkeypatch.setattr(mcp_bridge, "_connected_sessions", lambda: {})
        data = _decode(await list_servers())["data"]
        assert data["servers"] == []

    @pytest.mark.asyncio
    async def test_index_lists_servers_with_tool_counts(self, monkeypatch):
        client = _make_client(tools=[_make_tool("a"), _make_tool("b")])
        monkeypatch.setattr(
            mcp_bridge, "_connected_sessions", lambda: {"github": client}
        )
        data = _decode(await list_servers())["data"]
        assert len(data["servers"]) == 1
        entry = data["servers"][0]
        assert entry["server"] == "github"
        assert entry["tools"] == 2

    @pytest.mark.asyncio
    async def test_index_records_server_error(self, monkeypatch):
        client = _make_client()
        client.list_tools.side_effect = RuntimeError("boom")
        monkeypatch.setattr(mcp_bridge, "_connected_sessions", lambda: {"db": client})
        data = _decode(await list_servers())["data"]
        assert data["servers"][0] == {"server": "db", "error": "boom"}


class TestListTools:
    """``ax mcp list args={'server': ...}`` — per-server tool enumeration."""

    @pytest.mark.asyncio
    async def test_small_list_returned_inline(self):
        client = _make_client(tools=[_make_tool("a", "alpha"), _make_tool("b", "beta")])
        body = _decode(await list_tools("srv", client))
        tools = body["data"]["tools"]
        assert [t["name"] for t in tools] == ["a", "b"]
        assert tools[0]["description"] == "alpha"

    @pytest.mark.asyncio
    async def test_description_truncated_to_200(self):
        long = "x" * 500
        client = _make_client(tools=[_make_tool("a", long)])
        tools = _decode(await list_tools("srv", client))["data"]["tools"]
        assert len(tools[0]["description"]) == 200

    @pytest.mark.asyncio
    async def test_large_list_persisted_to_file(self):
        big_schema = {
            "properties": {"x": {"type": "string", "description": "y" * 3000}}
        }
        client = _make_client(
            tools=[
                _make_tool("a", schema=big_schema),
                _make_tool("b", schema=big_schema),
            ]
        )
        with patch(
            "aria.tools.mcp_bridge.write_tool_output",
            return_value="/tmp/mcp_list_srv.txt",
        ) as mock_write:
            data = _decode(await list_tools("srv", client))["data"]
        assert data["count"] == 2
        assert data["path"] == "/tmp/mcp_list_srv.txt"
        assert mock_write.call_count == 1

    @pytest.mark.asyncio
    async def test_call_failure_returns_error_response(self):
        client = _make_client()
        client.list_tools.side_effect = RuntimeError("disconnected")
        data = _decode(await list_tools("srv", client))["data"]
        assert data["error"]["code"] == "mcp_call_failed"
        assert "disconnected" in data["error"]["message"]


class TestCallTool:
    """``ax mcp call`` — raw-dict forwarding + content mapping."""

    @pytest.mark.asyncio
    async def test_text_content_returned_inline(self):
        result = CallToolResult(content=[TextContent(type="text", text="hello")])
        client = _make_client(call_result=result)
        data = _decode(await call_tool("srv", client, "greet", {}))["data"]
        assert data["content"] == "hello"
        assert data["isError"] is False

    @pytest.mark.asyncio
    async def test_non_text_content_repr(self):
        result = CallToolResult(
            content=[
                TextContent(type="text", text="t"),
                ImageContent(type="image", data="b64", mimeType="image/png"),
            ]
        )
        client = _make_client(call_result=result)
        content = _decode(await call_tool("srv", client, "img", {}))["data"]["content"]
        assert "t" in content
        assert "ImageContent" in content

    @pytest.mark.asyncio
    async def test_is_error_prefix(self):
        result = CallToolResult(
            content=[TextContent(type="text", text="fail")], isError=True
        )
        client = _make_client(call_result=result)
        data = _decode(await call_tool("srv", client, "bad", {}))["data"]
        assert data["content"].startswith("[MCP tool returned isError=True]")
        assert data["isError"] is True

    @pytest.mark.asyncio
    async def test_empty_result(self):
        client = _make_client(call_result=CallToolResult(content=[]))
        content = _decode(await call_tool("srv", client, "noop", {}))["data"]["content"]
        assert content == "[empty result]"

    @pytest.mark.asyncio
    async def test_large_content_persisted_to_file(self):
        result = CallToolResult(content=[TextContent(type="text", text="z" * 5000)])
        client = _make_client(call_result=result)
        with patch(
            "aria.tools.mcp_bridge.write_tool_output",
            return_value="/tmp/mcp_srv_tool.txt",
        ) as mock_write:
            data = _decode(await call_tool("srv", client, "tool", {}))["data"]
        assert data["path"] == "/tmp/mcp_srv_tool.txt"
        assert mock_write.call_count == 1

    @pytest.mark.asyncio
    async def test_call_failure_returns_error_response(self):
        client = _make_client()
        client.call_tool.side_effect = RuntimeError("timeout")
        data = _decode(await call_tool("srv", client, "tool", {}))["data"]
        assert data["error"]["code"] == "mcp_call_failed"
        assert "timeout" in data["error"]["message"]


class TestContentToText:
    """``_content_to_text`` — pure mapping of ``CallToolResult`` content."""

    def test_text_only(self):
        result = CallToolResult(
            content=[
                TextContent(type="text", text="a"),
                TextContent(type="text", text="b"),
            ]
        )
        assert _content_to_text(result) == "a\nb"

    def test_non_text_repr(self):
        result = CallToolResult(
            content=[ImageContent(type="image", data="d", mimeType="image/png")]
        )
        out = _content_to_text(result)
        assert "ImageContent" in out

    def test_is_error_prefix(self):
        result = CallToolResult(
            content=[TextContent(type="text", text="x")], isError=True
        )
        assert _content_to_text(result).startswith("[MCP tool returned isError=True]")

    def test_empty(self):
        result = CallToolResult(content=[])
        assert _content_to_text(result) == "[empty result]"


class TestResolveSession:
    """``resolve_session`` — ``cl.user_session`` lookup."""

    @pytest.fixture
    def _fake_user_session(self, monkeypatch, _chainlit_module):
        store = MagicMock()
        monkeypatch.setattr(_chainlit_module, "user_session", store, raising=False)
        return store

    def test_no_sessions_returns_none(self, _fake_user_session):
        _fake_user_session.get.return_value = None
        assert resolve_session("any") is None

    def test_missing_server_returns_none(self, _fake_user_session):
        _fake_user_session.get.return_value = {"other": object()}
        assert resolve_session("missing") is None

    def test_found_returns_session(self, _fake_user_session):
        session = object()
        _fake_user_session.get.return_value = {"github": session}
        assert resolve_session("github") is session

    def test_case_insensitive_match(self, _fake_user_session):
        """The LLM is not trusted to reproduce the user's exact casing."""
        session = object()
        _fake_user_session.get.return_value = {"Whatsapp": session}
        assert resolve_session("whatsapp") is session
        assert resolve_session("WHATSAPP") is session

    def test_no_chainlit_context_returns_none(self, monkeypatch, _chainlit_module):
        """Outside a chainlit session (workers/CLI/tests) the lazy ``context``
        proxy raises ``ChainlitContextException`` — degrade to None, not an
        unhandled exception. This is the documented worker/CLI path (§11).
        """
        fake_session = MagicMock()
        fake_session.get.side_effect = ChainlitContextException
        monkeypatch.setattr(
            _chainlit_module, "user_session", fake_session, raising=False
        )
        assert resolve_session("any") is None


class TestConnectedServerNames:
    """``connected_server_names`` — cheap sync index for the per-turn nudge."""

    def test_no_sessions_returns_empty(self, monkeypatch):
        monkeypatch.setattr(mcp_bridge, "_connected_sessions", lambda: None)
        assert connected_server_names() == []

    def test_empty_sessions_returns_empty(self, monkeypatch):
        monkeypatch.setattr(mcp_bridge, "_connected_sessions", lambda: {})
        assert connected_server_names() == []

    def test_returns_server_keys(self, monkeypatch):
        monkeypatch.setattr(
            mcp_bridge,
            "_connected_sessions",
            lambda: {"github": object(), "db": object()},
        )
        assert sorted(connected_server_names()) == ["db", "github"]

    def test_no_chainlit_context_returns_empty(self, monkeypatch, _chainlit_module):
        fake_session = MagicMock()
        fake_session.get.side_effect = ChainlitContextException
        monkeypatch.setattr(
            _chainlit_module, "user_session", fake_session, raising=False
        )
        assert connected_server_names() == []


class TestConnectedToolMap:
    """``connected_tool_map`` — per-server tool names for the per-turn nudge."""

    @pytest.mark.asyncio
    async def test_no_sessions_returns_empty(self, monkeypatch):
        monkeypatch.setattr(mcp_bridge, "_connected_sessions", lambda: None)
        assert await connected_tool_map() == {}

    @pytest.mark.asyncio
    async def test_empty_sessions_returns_empty(self, monkeypatch):
        monkeypatch.setattr(mcp_bridge, "_connected_sessions", lambda: {})
        assert await connected_tool_map() == {}

    @pytest.mark.asyncio
    async def test_returns_names_and_descriptions(self, monkeypatch):
        client = _make_client(
            tools=[
                _make_tool("groups-list", "List groups"),
                _make_tool("chats-list", "List chats"),
            ]
        )
        monkeypatch.setattr(
            mcp_bridge, "_connected_sessions", lambda: {"whatsapp": client}
        )
        out = await connected_tool_map()
        assert sorted(out) == ["whatsapp"]
        assert [t["name"] for t in out["whatsapp"]] == ["groups-list", "chats-list"]
        assert out["whatsapp"][0]["description"] == "List groups"

    @pytest.mark.asyncio
    async def test_description_truncated_and_stripped(self, monkeypatch):
        client = _make_client(tools=[_make_tool("a", "  desc with trailing spaces  ")])
        monkeypatch.setattr(mcp_bridge, "_connected_sessions", lambda: {"srv": client})
        out = await connected_tool_map()
        assert out["srv"][0]["description"] == "desc with trailing spaces"

    @pytest.mark.asyncio
    async def test_server_error_is_skipped(self, monkeypatch):
        client = _make_client()
        client.list_tools.side_effect = RuntimeError("disconnected")
        monkeypatch.setattr(
            mcp_bridge, "_connected_sessions", lambda: {"broken": client}
        )
        assert await connected_tool_map() == {}
