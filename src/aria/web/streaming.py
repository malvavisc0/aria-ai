"""Streaming event handling for the Aria web UI.

This module handles the translation of agent stream events into
Chainlit UI updates.
"""

from __future__ import annotations

import chainlit as cl
from llama_index.core.agent.workflow import AgentOutput, AgentStream, ToolCall
from loguru import logger

from aria.helpers.ui import maybe_remove_step, send_tool_step

_BLOCKQUOTE_PREFIX = "> "
_BLOCKQUOTE_END = "\n\n"


class _ThinkingBlock:
    """Render a markdown blockquote around reasoning tokens.

    Encapsulates the open/close bookkeeping so callers just call
    :meth:`open` before emitting thinking and :meth:`close` before
    emitting anything else (a tool step, a content token, final output,
    or on error).  Idempotent: opening twice or closing twice is a no-op.
    """

    def __init__(self, output: cl.Message) -> None:
        self._output = output
        self._open = False
        self.parts: list[str] = []

    async def open(self) -> None:
        if self._open:
            return
        await self._output.stream_token(_BLOCKQUOTE_PREFIX)
        self._open = True

    async def close(self) -> None:
        if not self._open:
            return
        await self._output.stream_token(_BLOCKQUOTE_END)
        self._open = False

    async def write(self, delta: str) -> None:
        await self.open()
        self.parts.append(delta)
        await self._output.stream_token(delta.replace("\n", "\n> "))

    def full_text(self) -> str:
        return "".join(self.parts).strip()


async def _handle_tool_call_event(
    event: ToolCall,
    current_step: cl.Step | None,
    thinking: _ThinkingBlock,
    tools_called: list[str],
) -> tuple[cl.Step | None, _ThinkingBlock]:
    tools_called.append(event.tool_name or "unknown")
    await maybe_remove_step(current_step)
    await thinking.close()
    new_step = await send_tool_step(event)
    return new_step, thinking


async def _handle_agent_stream_event(
    event: AgentStream,
    current_step: cl.Step | None,
    thinking: _ThinkingBlock,
    output: cl.Message,
    answer_parts: list[str],
) -> tuple[cl.Step | None, _ThinkingBlock, bool, bool]:
    """Returns (current_step, thinking, emitted, content_emitted)."""
    if event.thinking_delta:
        if current_step is not None:
            await maybe_remove_step(current_step)
            current_step = None
        await thinking.write(event.thinking_delta)
        return current_step, thinking, True, False
    if event.delta:
        if current_step is not None:
            await maybe_remove_step(current_step)
            current_step = None
        await thinking.close()
        await output.stream_token(event.delta)
        answer_parts.append(event.delta)
        return current_step, thinking, True, True
    return current_step, thinking, False, False


async def _handle_agent_output_event(
    event: AgentOutput,
    current_step: cl.Step | None,
    thinking: _ThinkingBlock,
    output: cl.Message,
    content_emitted: bool,
    answer_parts: list[str],
) -> bool:
    if not event.tool_calls:
        if current_step is not None:
            await maybe_remove_step(current_step)
            current_step = None
        await thinking.close()
    if content_emitted:
        return False
    final = event.response.content or ""
    if final.strip() and final.strip() != thinking.full_text():
        await output.stream_token(final)
        answer_parts.append(final)
        return True
    return False


async def _process_stream_event(
    event,
    current_step: cl.Step | None,
    thinking: _ThinkingBlock,
    tools_called: list[str],
    output: cl.Message,
    content_emitted: bool,
    answer_parts: list[str],
) -> tuple[cl.Step | None, _ThinkingBlock, bool, bool, bool]:
    """Process a single event. Returns (step, thinking, emitted, content_emitted, has_thinking)."""
    if isinstance(event, ToolCall):
        new_step, thinking = await _handle_tool_call_event(
            event, current_step, thinking, tools_called
        )
        return new_step, thinking, False, False, False

    if isinstance(event, AgentStream):
        step, thinking, emitted, ce = await _handle_agent_stream_event(
            event, current_step, thinking, output, answer_parts
        )
        return step, thinking, emitted, ce, bool(event.thinking_delta)

    if isinstance(event, AgentOutput):
        emitted = await _handle_agent_output_event(
            event, current_step, thinking, output, content_emitted, answer_parts
        )
        return current_step, thinking, emitted, emitted, False

    return current_step, thinking, False, False, False


async def _finalize_stream(
    output: cl.Message,
    thinking: _ThinkingBlock,
    handler_result,
    emitted: bool,
    content_emitted: bool,
    has_thinking: bool,
    answer_parts: list[str],
) -> tuple[bool, bool, bool]:
    if not content_emitted:
        final = getattr(handler_result.response, "content", None) or ""
        if final.strip() and final.strip() != thinking.full_text():
            await output.stream_token(final)
            answer_parts.append(final)
            emitted = True
            content_emitted = True
    await thinking.close()
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
    """
    thinking = _ThinkingBlock(output)
    tools_called: list[str] = []
    current_step: cl.Step | None = None
    emitted = False
    content_emitted = False
    has_thinking = False
    answer_parts: list[str] = []

    async for event in handler.stream_events():
        current_step, thinking, e, ce, ht = await _process_stream_event(
            event,
            current_step,
            thinking,
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
        await thinking.close()
        raise

    emitted, _content_emitted, has_thinking = await _finalize_stream(
        output,
        thinking,
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
