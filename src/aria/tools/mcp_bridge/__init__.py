"""Bridge between connected MCP servers and the ``ax mcp`` family.

Routed via ax: the bridge does NOT add FunctionTools to the agent. It only
enumerates a server's tools (for ``ax mcp list``) and forwards a raw-dict
``call_tool`` invocation, persisting large results per AGENTS.md.
"""

from __future__ import annotations

from typing import Any

from mcp import ClientSession
from mcp.types import CallToolResult, TextContent

from aria.tools._output import write_tool_output
from aria.tools.utils import tool_response

_PERSIST_THRESHOLD = 2000  # chars


def _unwrap_client(entry: ClientSession | Any) -> ClientSession:
    """Extract the ``ClientSession`` from a chainlit ``McpSession`` wrapper."""
    try:
        from chainlit.session import McpSession
    except ImportError:
        return entry
    return entry.client if isinstance(entry, McpSession) else entry


def resolve_session(server: str) -> ClientSession | None:
    """Return the connected ClientSession for *server* in this chainlit session.

    Server names match case-insensitively (the exact name the user typed in
    the UI is not something the LLM can be trusted to reproduce).

    Returns None outside a chainlit session (workers, CLI) or when the
    named server is not connected. Uses ``context.session.mcp_sessions``
    (chainlit's in-memory, never-persisted store) rather than
    ``cl.user_session`` — storing live ``ClientSession`` objects in
    ``cl.user_session`` leaks them into thread metadata and breaks JSON
    serialization on resume.
    """
    sessions = _connected_sessions()
    if not sessions:
        return None
    if server in sessions:
        return _unwrap_client(sessions[server])
    lowered = server.lower()
    for name, entry in sessions.items():
        if name.lower() == lowered:
            return _unwrap_client(entry)
    return None


def _content_to_text(result: CallToolResult) -> str:
    parts: list[str] = []
    for block in result.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
        else:
            parts.append(repr(block))
    if result.isError:
        parts.insert(0, "[MCP tool returned isError=True]")
    return "\n".join(parts) or "[empty result]"


def _connected_sessions() -> dict[str, Any] | None:
    """Return the per-session map of connected MCP servers, or None.

    Each value is chainlit's ``McpSession`` wrapper (accessed via
    :func:`_unwrap_client`); the mapping itself lives on
    ``context.session.mcp_sessions`` — an in-memory struct chainlit never
    JSON-serializes.

    Returns None outside a chainlit session (workers, CLI, tests) —
    the lazy ``context`` proxy raises ``ChainlitContextException`` there.
    That's the documented degradation path for non-web contexts, not an
    error.
    """
    import chainlit as cl
    from chainlit.context import ChainlitContextException

    try:
        session = cl.context.session
    except ChainlitContextException:
        return None
    return getattr(session, "mcp_sessions", None)


def connected_server_names() -> list[str]:
    """Return the names of connected MCP servers in this session (sync, cheap).

    Reads only the session-store keys — no async ``list_tools`` round-trip.
    Used for the per-turn prompt nudge so the agent knows which servers exist
    without calling ``ax mcp list`` first.
    """
    sessions = _connected_sessions()
    if not sessions:
        return []
    return list(sessions.keys())


async def list_servers() -> str:
    """Return the connected-server index for ``ax mcp list`` (no server arg).

    Cheap one-liner per server (name + tool count) so a small model sees
    what's connected in a single call without pulling full schemas. This is
    the discovery entry point. Tool names are surfaced per turn by
    :func:`connected_tool_map`, so the index does not repeat them.
    """
    sessions = _connected_sessions()
    if not sessions:
        return tool_response(
            tool="ax",
            reason="mcp list",
            data={
                "servers": [],
                "hint": "No MCP servers connected in this session.",
            },
        )
    index = []
    for name, entry in sessions.items():
        try:
            tools = await _unwrap_client(entry).list_tools()
            index.append(
                {
                    "server": name,
                    "tools": len(tools.tools),
                }
            )
        except Exception as exc:
            index.append({"server": name, "error": str(exc)})
    return tool_response(tool="ax", reason="mcp list", data={"servers": index})


async def list_tools(server: str, client: ClientSession) -> str:
    """Enumerate tools on *server* for ``ax mcp list args={'server': ...}``."""
    try:
        result = await client.list_tools()
    except Exception as exc:
        return tool_response(
            tool="ax",
            reason="mcp list",
            data={
                "error": {
                    "code": "mcp_call_failed",
                    "message": f"Server '{server}' error: {exc}",
                }
            },
        )
    tools = [
        {
            "server": server,
            "name": t.name,
            "description": (t.description or "")[:200],
            "inputSchema": t.inputSchema,
        }
        for t in result.tools
    ]
    body = tool_response(
        tool="ax", reason="mcp list", data={"server": server, "tools": tools}
    )
    # Full schemas can be large (a 30-tool server is several KB) -- persist.
    if len(body) > _PERSIST_THRESHOLD:
        path = write_tool_output(tool="mcp", suffix=f"list_{server}", content=body)
        return tool_response(
            tool="ax",
            reason="mcp list",
            data={"server": server, "count": len(tools), "path": path},
        )
    return body


async def call_tool(
    server: str,
    client: ClientSession,
    name: str,
    arguments: dict[str, Any],
) -> str:
    """Forward a raw-dict call, persisting large results to a file."""
    try:
        result = await client.call_tool(name, arguments)
    except Exception as exc:
        return tool_response(
            tool="ax",
            reason=f"mcp call {server}.{name}",
            data={
                "error": {
                    "code": "mcp_call_failed",
                    "message": f"Server '{server}' error: {exc}",
                }
            },
        )
    text = _content_to_text(result)
    if len(text) > _PERSIST_THRESHOLD:
        path = write_tool_output(tool=f"mcp_{server}", suffix=name, content=text)
        return tool_response(
            tool="ax",
            reason=f"mcp call {server}.{name}",
            data={
                "server": server,
                "name": name,
                "path": path,
                "isError": result.isError,
            },
        )
    return tool_response(
        tool="ax",
        reason=f"mcp call {server}.{name}",
        data={
            "server": server,
            "name": name,
            "content": text,
            "isError": result.isError,
        },
    )
