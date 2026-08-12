"""Streaming event handling for the Aria web UI.

This module handles the translation of agent stream events into
Chainlit UI updates.
"""

from __future__ import annotations

from typing import Any

import chainlit as cl
from llama_index.core.agent.workflow import (
    AgentOutput,
    AgentStream,
    ToolCall,
    ToolCallResult,
)
from loguru import logger

from aria.helpers.ui import send_thinking_step, send_tool_step


async def _finalize_thinking_step(step: cl.Step | None) -> cl.Step | None:
    """Persist a finished thinking segment and clear the reference."""
    if step is not None:
        await step.update()
    return None


async def _handle_tool_call_event(
    event: ToolCall,
    thinking_step: cl.Step | None,
    tools_called: list[str],
) -> tuple[cl.Step | None, cl.Step | None]:
    """Finalize any open thinking segment, then emit a persisted tool step.

    Tool steps are never removed — each stays visible (collapsed) so the
    full per-turn hierarchy (Thinking ▸ tool ▸ Thinking ▸ tool ▸ answer)
    remains in the UI and in the persisted history. The step's ``input``
    is populated from the tool-call kwargs; its ``output`` is filled later
    when the matching :class:`ToolCallResult` arrives.
    """
    tools_called.append(event.tool_name or "unknown")
    thinking_step = await _finalize_thinking_step(thinking_step)
    tool_step = await send_tool_step(event)
    return thinking_step, tool_step


def _tool_output(tool_output: Any) -> str | dict:
    """Extract a renderable value from a llama_index ``ToolOutput``.

    Returns a parsed dict when the output is a JSON object (so Chainlit
    renders it as formatted, syntax-highlighted JSON), else the raw string.
    """
    import json

    blocks = getattr(tool_output, "blocks", None) or []
    texts = [getattr(b, "text", None) for b in blocks]
    text = "".join(t for t in texts if isinstance(t, str))
    if not text:
        text = str(getattr(tool_output, "raw_output", "") or "")
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
    if isinstance(parsed, dict):
        return parsed
    return text


async def _handle_tool_call_result_event(
    event: ToolCallResult,
    tool_step: cl.Step | None,
) -> cl.Step | None:
    """Populate a tool step's output from its result and finalize it.

    Matches the pending tool step by ``tool_id``; if the IDs align, sets
    ``step.output`` to the tool result text and persists via ``update()``.
    Returns ``None`` either way (the step is now complete).
    """
    if tool_step is None:
        return None
    if (
        event.tool_id
        and getattr(tool_step, "metadata", {}).get("tool_id") != event.tool_id
    ):
        logger.debug(
            f"ToolCallResult tool_id {event.tool_id} does not match pending "
            f"step; finalizing step without output."
        )
        await tool_step.update()
        return None
    tool_step.output = _tool_output(event.tool_output)
    await tool_step.update()
    return None


async def _handle_agent_stream_event(
    event: AgentStream,
    thinking_step: cl.Step | None,
    thinking_parts: list[str],
    output: cl.Message,
    answer_parts: list[str],
) -> tuple[cl.Step | None, bool, bool]:
    """Returns (thinking_step, emitted, content_emitted)."""
    if event.thinking_delta:
        if thinking_step is None:
            thinking_step = await send_thinking_step()
        await thinking_step.stream_token(event.thinking_delta)
        thinking_parts.append(event.thinking_delta)
        return thinking_step, True, False
    if event.delta:
        thinking_step = await _finalize_thinking_step(thinking_step)
        await output.stream_token(event.delta)
        answer_parts.append(event.delta)
        return thinking_step, True, True
    return thinking_step, False, False


async def _handle_agent_output_event(
    event: AgentOutput,
    thinking_step: cl.Step | None,
    thinking_parts: list[str],
    output: cl.Message,
    content_emitted: bool,
    answer_parts: list[str],
) -> tuple[cl.Step | None, bool]:
    """Returns (thinking_step, emitted)."""
    thinking_step = await _finalize_thinking_step(thinking_step)
    if content_emitted:
        return thinking_step, False
    final = event.response.content or ""
    if final.strip() and final.strip() != "".join(thinking_parts).strip():
        await output.stream_token(final)
        answer_parts.append(final)
        return thinking_step, True
    return thinking_step, False


async def _process_stream_event(
    event,
    thinking_step: cl.Step | None,
    tool_step: cl.Step | None,
    thinking_parts: list[str],
    tools_called: list[str],
    output: cl.Message,
    content_emitted: bool,
    answer_parts: list[str],
) -> tuple[cl.Step | None, cl.Step | None, bool, bool, bool]:
    """Process a single event.

    Returns (thinking_step, tool_step, emitted, content_emitted, has_thinking).
    """
    if isinstance(event, ToolCall):
        thinking_step, new_tool_step = await _handle_tool_call_event(
            event, thinking_step, tools_called
        )
        return thinking_step, new_tool_step, False, False, False

    if isinstance(event, ToolCallResult):
        tool_step = await _handle_tool_call_result_event(event, tool_step)
        return thinking_step, tool_step, False, False, False

    if isinstance(event, AgentStream):
        thinking_step, emitted, ce = await _handle_agent_stream_event(
            event, thinking_step, thinking_parts, output, answer_parts
        )
        return thinking_step, tool_step, emitted, ce, bool(event.thinking_delta)

    if isinstance(event, AgentOutput):
        thinking_step, emitted = await _handle_agent_output_event(
            event,
            thinking_step,
            thinking_parts,
            output,
            content_emitted,
            answer_parts,
        )
        return thinking_step, tool_step, emitted, emitted, False

    return thinking_step, tool_step, False, False, False


async def _finalize_stream(
    output: cl.Message,
    thinking_step: cl.Step | None,
    tool_step: cl.Step | None,
    thinking_parts: list[str],
    handler_result,
    emitted: bool,
    content_emitted: bool,
    has_thinking: bool,
    answer_parts: list[str],
) -> tuple[bool, bool, bool]:
    await _finalize_thinking_step(thinking_step)
    if tool_step is not None:
        await tool_step.update()
    if not content_emitted:
        final = getattr(handler_result.response, "content", None) or ""
        if final.strip() and final.strip() != "".join(thinking_parts).strip():
            await output.stream_token(final)
            answer_parts.append(final)
            emitted = True
            content_emitted = True
    if not emitted:
        logger.warning("No assistant output emitted for message.")
        fallback = (
            "I wasn't able to generate a response. Please try rephrasing your request."
        )
        await output.stream_token(fallback)
        answer_parts.append(fallback)
        emitted = True
    return emitted, content_emitted, has_thinking


async def stream_agent_response(
    handler,
    output: cl.Message,
) -> tuple[bool, dict, str]:
    """Stream agent events to the UI and return (emitted, meta, answer_text).

    ``answer_text`` is the clean answer only (thinking/reasoning tokens
    excluded) — used by the voice pipeline for TTS so Aria never narrates
    its own internal reasoning.

    Tool steps are persisted (collapsed) and never removed, so the full
    hierarchy — Thinking ▸ tool ▸ Thinking ▸ tool ▸ answer — stays visible.
    Each tool step is populated with ``input`` (tool kwargs) on the
    ``ToolCall`` and ``output`` (tool result) on the matching
    ``ToolCallResult``, following Chainlit's standard step pattern.
    """
    tools_called: list[str] = []
    thinking_step: cl.Step | None = None
    tool_step: cl.Step | None = None
    thinking_parts: list[str] = []
    emitted = False
    content_emitted = False
    has_thinking = False
    answer_parts: list[str] = []

    async for event in handler.stream_events():
        thinking_step, tool_step, e, ce, ht = await _process_stream_event(
            event,
            thinking_step,
            tool_step,
            thinking_parts,
            tools_called,
            output,
            content_emitted,
            answer_parts,
        )
        emitted |= e
        content_emitted |= ce
        has_thinking |= ht

    try:
        handler_result = await handler
    except Exception:
        await _finalize_thinking_step(thinking_step)
        if tool_step is not None:
            await tool_step.update()
        raise

    emitted, _content_emitted, has_thinking = await _finalize_stream(
        output,
        thinking_step,
        tool_step,
        thinking_parts,
        handler_result,
        emitted,
        content_emitted,
        has_thinking,
        answer_parts,
    )

    answer_text = "".join(answer_parts).strip()
    return (
        emitted,
        {"tools_called": tools_called, "has_thinking": has_thinking},
        answer_text,
    )
