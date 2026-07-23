"""Message processing pipeline for the Aria web UI.

This module handles incoming user messages and orchestrates the agent workflow:
- Prompt enhancement (optional)
- File path extraction from uploaded files
- Memory management per thread
- Agent workflow execution with streaming responses
- Error handling and user feedback

The main entry point is `on_message_handler` which is called by Chainlit
whenever a user sends a message.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import chainlit as cl
import httpx
from llama_index.core.agent.workflow import AgentOutput, AgentStream, ToolCall
from llama_index.core.memory import Memory
from loguru import logger
from workflows.handler import WorkflowHandler

from aria.agents.prompt_enhancer import PromptEnhancementResult
from aria.config.api import Vllm as VllmConfig
from aria.config.models import Chat as ChatConfig
from aria.helpers.ui import maybe_remove_step, send_tool_step
from aria.web.hooks import get_data_layer_handler
from aria.web.session import (
    _sanitize_chat_history,
    convert_documents_to_markdown,
    create_memory,
    extract_file_paths,
    extract_image_data,
    restore_chat_history,
)
from aria.web.state import AppStateNotInitializedError, _state

# Metadata key used to mark messages as processed (for edit detection)
_PROCESSED_KEY = "processed"

# Default metadata — every persisted message will contain all these
# keys so downstream consumers can rely on a stable schema.
_DEFAULT_METADATA: dict[str, Any] = {
    "tools_called": [],
    "has_thinking": False,
    "processed": False,
    "prompt_enhanced": False,
    "attachments": [],
    "error": "",
}

# Markdown formatting for thinking/reasoning content (blockquote style)
_BLOCKQUOTE_PREFIX = "> "
_BLOCKQUOTE_END = "\n\n"


def _history_fingerprint(messages: list) -> int:
    """Stable hash of a chat-history list for change detection.

    Comparing fingerprints (instead of ``len``) catches in-place rewrites
    that preserve message count — a length-only check would silently skip
    a repair in that case.
    """
    h = 0
    for m in messages:
        role = getattr(m, "role", None)
        role_name = getattr(role, "value", role)
        content = getattr(m, "content", "") or ""
        h ^= hash((role_name, content))
    return h


async def _sanitize_memory(memory: Memory) -> None:
    """Ensure memory chat history has valid user/assistant alternation.

    After a failed live turn the ``Memory`` chat store may contain a
    trailing user message with no matching assistant reply (or other
    alternation violations).  This normalises the history so the next
    model invocation sees strictly alternating roles.

    Uses ``memory.set()`` (bypasses token-limit waterfall) because this
    is a corrective rewrite, not a new-message insertion.
    """
    messages = await memory.aget()
    if not messages:
        return
    before = _history_fingerprint(messages)
    sanitized = _sanitize_chat_history(messages)
    after = _history_fingerprint(sanitized)
    if before != after:
        logger.debug(
            f"Sanitized memory chat history: {len(messages)} → "
            f"{len(sanitized)} messages (repaired alternation)"
        )
        memory.set(sanitized)


async def _rollback_memory(memory: Memory | None) -> None:
    """Repair dangling state left by a failed workflow run.

    When an LLM/infrastructure error occurs after ``AgentWorkflow.run()``
    has begun persisting a turn, the memory may end with:

    * a dangling user message (no assistant reply), breaking alternation; or
    * an assistant message advertising tool calls whose matching ``tool``
      responses are missing (or only partially present), breaking
      Mistral's "same number of function calls and responses" invariant.

    Routing through :func:`_sanitize_chat_history` repairs all of these in
    one pass so the next turn sees a structurally valid history.
    """
    if memory is None:
        return
    try:
        messages = await memory.aget()
        if not messages:
            return
        before = _history_fingerprint(messages)
        repaired = _sanitize_chat_history(messages)
        after = _history_fingerprint(repaired)
        if before != after:
            logger.debug(
                "Rolling back dangling/partial turn from memory "
                f"({len(messages)} → {len(repaired)} messages)"
            )
            memory.set(repaired)
    except Exception:
        logger.warning("Failed to rollback memory", exc_info=True)


async def _mark_message_processed(
    message: cl.Message,
    extra_metadata: dict | None = None,
    *,
    processed: bool = True,
) -> None:
    """Persist message metadata to the DB.

    By default sets ``processed: True`` so that future deliveries
    of the same message (i.e. edits) can be detected.  Error paths
    should pass ``processed=False`` so that re-delivery after a
    failure is treated as a retry, not an edit.

    All default metadata keys are always present; *extra_metadata*
    overrides individual defaults.
    """
    try:
        data_layer = get_data_layer_handler()
        step_dict = message.to_dict()
        step_dict["metadata"] = {
            **(message.metadata or {}),
            **_DEFAULT_METADATA,
            **(extra_metadata or {}),
            _PROCESSED_KEY: processed,
        }
        await data_layer.create_step(step_dict)
    except Exception:
        logger.warning(
            f"Failed to mark message {message.id} as processed",
            exc_info=True,
        )


class _EditThreadMissingError(RuntimeError):
    """Raised when a thread cannot be found while applying a message edit."""


async def _reset_memory_for_edit(
    thread_id: str,
) -> Memory:
    """Reset and rebuild memory after a message edit.

    Deletes the vector collection for the thread, creates fresh
    memory, and restores chat history from the persisted thread
    data (which Chainlit has already updated with the edited
    content).

    Raises:
        _EditThreadMissingError: If the thread no longer exists in the
            data layer.  An edit against a missing thread would silently
            wipe the conversation's memory, so we abort instead.
    """
    try:
        if _state.vector_db is not None:
            _state.vector_db.delete_collection(thread_id)
    except Exception:
        logger.debug(
            f"Could not delete vector collection for {thread_id}",
            exc_info=True,
        )

    memory = create_memory(thread_id)
    data_layer = get_data_layer_handler()
    thread = await data_layer.get_thread(thread_id)
    if not thread:
        raise _EditThreadMissingError(
            f"Thread {thread_id} not found; cannot apply edit to a thread "
            "that no longer exists."
        )
    memory = await restore_chat_history(thread)
    return memory


_IMAGE_DESCRIBE_PROMPT = "Describe this image concisely in 2-3 sentences."


async def _describe_image(
    client: httpx.AsyncClient,
    mime_type: str,
    base64_data: str,
    prompt: str = _IMAGE_DESCRIBE_PROMPT,
) -> str:
    """Send an image to the vision endpoint and return a text description."""
    image_url = f"data:{mime_type};base64,{base64_data}"
    response = await client.post(
        f"{ChatConfig.api_url}/chat/completions",
        headers={"Authorization": f"Bearer {VllmConfig.api_key}"},
        json={
            "model": ChatConfig.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url},
                        },
                    ],
                }
            ],
            # Disable thinking for vision description: the reasoning block
            # otherwise consumes the entire token budget and `content` comes
            # back null (finish_reason="length"). Image captioning is a
            # short, deterministic task — chain-of-thought is pure waste.
            "chat_template_kwargs": {"enable_thinking": False},
            "max_tokens": 1024,
        },
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"] or ""


async def _enhance_prompt(message: cl.Message, prompt: str) -> tuple[str, dict]:
    """Apply prompt enhancement when the "Enhance" command is active.

    Returns the (possibly enhanced) prompt and a metadata dict.  On
    enhancement failure the original prompt is kept and the user is
    notified; the pipeline continues rather than aborting.
    """
    if message.command != "Enhance":
        return prompt, {}
    if not _state.prompt_enhancer:
        logger.warning("Prompt enhancer not available, returning original prompt")
        return prompt, {}
    try:
        response = await asyncio.wait_for(
            _state.prompt_enhancer.run(user_msg=message.content),
            timeout=30.0,
        )
        results = response.structured_response
        if isinstance(results, dict):
            results = PromptEnhancementResult(**results)
        logger.debug("Prompt enhancement completed successfully")
        return results.enhanced, {"prompt_enhanced": True}
    except Exception as e:
        logger.error(f"Prompt enhancement failed: {e}")
        await cl.ErrorMessage(
            content="Prompt enhancement failed, using original prompt.",
        ).send()
        return prompt, {}


async def _append_files_block(prompt: str, file_paths: list[str]) -> str:
    """Append an ``[Uploaded files]`` block describing converted docs."""
    if not file_paths:
        return prompt
    conversions = await asyncio.to_thread(convert_documents_to_markdown, file_paths)
    lines: list[str] = []
    for conv in conversions:
        if conv["markdown_path"]:
            lines.append(
                f"- {conv['name']} (original: {conv['original_path']})\n"
                f"  Converted to markdown: {conv['markdown_path']} "
                f"({conv['lines']} lines, {conv['chars']} chars)"
            )
        elif conv["error"]:
            lines.append(
                f"- {conv['name']}: {conv['original_path']} "
                f"(conversion failed: {conv['error']})"
            )
        else:
            lines.append(f"- {conv['original_path']}")
    logger.debug(f"Appended {len(file_paths)} file path(s) to prompt")
    return f"{prompt}\n\n[Uploaded files]:\n" + "\n".join(lines)


async def _append_images_block(prompt: str, image_data: list[dict]) -> str:
    """Append an ``[Attached images]`` block with vision descriptions.

    When vision is disabled the block is omitted entirely — injecting a
    placeholder like ``<vision disabled>`` would only add noise the model
    cannot act on.
    """
    if not image_data or not VllmConfig.vision_enabled:
        return prompt

    async with httpx.AsyncClient(timeout=30.0) as client:

        async def _describe(i: int, img: dict) -> str:
            try:
                desc = await _describe_image(client, img["mime_type"], img["base64"])
                return f"[Image {i} ({img['name']})]: {desc}"
            except Exception as e:
                logger.warning(f"Vision description failed for {img['name']}: {e}")
                return f"[Image {i} ({img['name']})]: <description unavailable>"

        descriptions = list(
            await asyncio.gather(
                *[_describe(i, img) for i, img in enumerate(image_data, 1)]
            )
        )

    logger.debug(f"Described {len(descriptions)} image(s) via vision API")
    return f"{prompt}\n\n[Attached images]:\n" + "\n".join(descriptions)


async def _handle_message(
    message: cl.Message,
) -> tuple[str, dict]:
    """Process and enhance a user message before agent execution.

    Orchestrates, in order: prompt enhancement, uploaded-file extraction
    & conversion, image vision description, and thread-id tagging.  Each
    step is handled by a dedicated helper so this function reads as a
    straight-line pipeline.

    File extraction (disk I/O) and document conversion (CPU-bound MarkItDown
    parsing) run off the event loop via ``asyncio.to_thread`` so a large
    upload doesn't stall active sessions.
    """
    prompt, enhance_meta = await _enhance_prompt(message, message.content)

    # Deduplicate while preserving order (same file attached twice).
    file_paths = list(
        dict.fromkeys(await asyncio.to_thread(extract_file_paths, message))
    )
    image_data = await asyncio.to_thread(extract_image_data, message)

    meta: dict = dict(enhance_meta)
    if file_paths:
        meta["attachments"] = [Path(p).name for p in file_paths]

    prompt = await _append_files_block(prompt, file_paths)
    prompt = await _append_images_block(prompt, image_data)

    # Inject thread context so Aria can pass --thread-id when spawning workers
    thread_id = message.thread_id
    if thread_id:
        prompt = f"{prompt}\n\n[Thread ID: {thread_id}]"
        logger.debug(f"Injected thread_id={thread_id} into prompt")

    return prompt, meta


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

    @property
    def is_open(self) -> bool:
        return self._open

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
        return current_step, thinking, True, True
    return current_step, thinking, False, False


async def _handle_agent_output_event(
    event: AgentOutput,
    current_step: cl.Step | None,
    thinking: _ThinkingBlock,
    output: cl.Message,
    content_emitted: bool,
) -> bool:
    if not event.tool_calls:
        if current_step is not None:
            await maybe_remove_step(current_step)
            current_step = None
        await thinking.close()
    if content_emitted:
        return False
    return await _emit_final(output, event.response.content or "", thinking)


async def _emit_final(
    output: cl.Message, content: str, thinking: _ThinkingBlock
) -> bool:
    """Stream the final answer once, skipping empty or thinking-duplicate text.

    Returns True if content was streamed.
    """
    if not content.strip() or content.strip() == thinking.full_text():
        return False
    await output.stream_token(content)
    return True


async def _process_stream_event(
    event,
    current_step: cl.Step | None,
    thinking: _ThinkingBlock,
    tools_called: list[str],
    output: cl.Message,
    content_emitted: bool,
) -> tuple[cl.Step | None, _ThinkingBlock, bool, bool, bool]:
    """Process a single event. Returns (step, thinking, emitted, content_emitted, has_thinking)."""
    if isinstance(event, ToolCall):
        new_step, thinking = await _handle_tool_call_event(
            event, current_step, thinking, tools_called
        )
        return new_step, thinking, False, False, False

    if isinstance(event, AgentStream):
        step, thinking, emitted, ce = await _handle_agent_stream_event(
            event, current_step, thinking, output
        )
        return step, thinking, emitted, ce, bool(event.thinking_delta)

    if isinstance(event, AgentOutput):
        emitted = await _handle_agent_output_event(
            event, current_step, thinking, output, content_emitted
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
) -> tuple[bool, bool, bool]:
    if not content_emitted:
        final = getattr(handler_result.response, "content", None) or ""
        if await _emit_final(output, final, thinking):
            emitted = True
            content_emitted = True
    await thinking.close()
    if not emitted:
        logger.warning("No assistant output emitted for message.")
        await output.stream_token(
            "I wasn't able to generate a response. Please try rephrasing your request."
        )
        emitted = True
    return emitted, content_emitted, has_thinking


async def _stream_agent_response(
    handler: WorkflowHandler,
    output: cl.Message,
) -> tuple[bool, dict]:
    """Stream agent events to the UI and return whether output was emitted."""
    thinking = _ThinkingBlock(output)
    tools_called: list[str] = []
    current_step: cl.Step | None = None
    emitted = False
    content_emitted = False
    has_thinking = False

    async for event in handler.stream_events():
        current_step, thinking, e, ce, ht = await _process_stream_event(
            event, current_step, thinking, tools_called, output, content_emitted
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
        output, thinking, handler_result, emitted, content_emitted, has_thinking
    )

    return emitted, {"tools_called": tools_called, "has_thinking": has_thinking}


async def _fail_turn(
    *,
    message: cl.Message,
    memory: Memory | None,
    pipeline_meta: dict,
    error: BaseException,
    user_message: str,
    log_level: str = "error",
) -> None:
    """Shared cleanup for a failed message turn.

    Rolls back dangling memory, marks the user message as *not* processed
    (so re-delivery is treated as a retry, not an edit), and sends a
    user-facing explanation.  Every error path in :func:`on_message_handler`
    routes here so the bookkeeping can't drift between branches.
    """
    getattr(logger, log_level)(f"Turn failed: {error}")
    await _rollback_memory(memory)
    await _mark_message_processed(
        message,
        extra_metadata={**pipeline_meta, "error": str(error)},
        processed=False,
    )
    await cl.Message(content=user_message).send()


async def _workflow_init(message: cl.Message) -> tuple[Memory, str, dict, bool]:
    """Prepare memory + handler for a workflow run.

    Returns ``(memory, prompt, pipeline_meta, is_edit)``.
    """
    prompt, pipeline_meta = await _handle_message(message)
    is_edit = bool(message.metadata and message.metadata.get(_PROCESSED_KEY))
    memory = cl.user_session.get("memory")
    if memory is None or memory.session_id != message.thread_id:
        memory = create_memory(message.thread_id)
        cl.user_session.set("memory", memory)
        logger.debug(f"Created new Memory for thread {message.thread_id}")

    if is_edit:
        logger.info(
            f"Edit detected for message {message.id}, "
            "resetting memory from persisted history"
        )
        memory = await _reset_memory_for_edit(message.thread_id)
        cl.user_session.set("memory", memory)

    await _sanitize_memory(memory)
    return memory, prompt, pipeline_meta, is_edit


async def _send_empty_placeholder() -> cl.Message:
    output = cl.Message(content="")
    await output.send()
    return output


async def _warn_not_initialized() -> None:
    logger.warning("Message received but agents_workflow is not configured")
    await cl.Message(
        content=(
            "The system is not fully initialized (LLM unavailable). "
            "Please check server logs and try again later."
        )
    ).send()


async def _stream_and_finalize(
    message: cl.Message,
    output: cl.Message,
    pipeline_meta: dict,
    prompt: str,
    memory: Memory,
) -> dict:
    handler = _state.agents_workflow.run(  # type: ignore[union-attr]
        user_msg=prompt,
        memory=memory,
        max_iterations=ChatConfig.max_iteration,
    )
    _run_succeeded = False
    stream_meta: dict = {}
    try:
        _, stream_meta = await _stream_agent_response(handler, output)
        _run_succeeded = True
    finally:
        if _run_succeeded:
            await output.update()
            await _mark_message_processed(
                message, extra_metadata={**pipeline_meta, **stream_meta}
            )
        else:
            await output.remove()
    return stream_meta


def _context_overflow_message() -> str:
    return (
        "The conversation has grown too large for the "
        "model's context window. Please start a new "
        "conversation."
    )


def _generic_error_message() -> str:
    return "An error occurred. Please try again."


def _route_pipeline_error(error_msg: str) -> str:
    if "maximum context length" in error_msg.lower():
        return _context_overflow_message()
    return _generic_error_message()


async def on_message_handler(message: cl.Message) -> None:
    """Handle incoming user messages and execute the agent workflow.

    This is the main entry point for processing user messages. It:
    1. Validates app state is initialized
    2. Processes the message (enhancement, file extraction)
    3. Gets or creates memory for the thread
    4. Runs the agent workflow with streaming response
    5. Handles errors and sends appropriate feedback to user

    Args:
        message: The incoming Chainlit message from the user.
    """
    if not _state.agents_workflow:
        await _warn_not_initialized()
        return

    memory: Memory | None = None
    pipeline_meta: dict = {}
    try:
        _state.validate_initialized()
        memory, prompt, pipeline_meta, _is_edit = await _workflow_init(message)

        output = await _send_empty_placeholder()
        await _stream_and_finalize(message, output, pipeline_meta, prompt, memory)

    except AppStateNotInitializedError as e:
        await _fail_turn(
            message=message,
            memory=memory,
            pipeline_meta=pipeline_meta,
            error=e,
            user_message=(
                "The application is not fully initialized. "
                "Please wait a moment and try again."
            ),
        )

    except _EditThreadMissingError as e:
        await _fail_turn(
            message=message,
            memory=memory,
            pipeline_meta=pipeline_meta,
            error=e,
            user_message=(
                "This conversation could not be found, so the edit could not "
                "be applied. The thread may have been deleted."
            ),
        )

    except httpx.TimeoutException as e:
        await _fail_turn(
            message=message,
            memory=memory,
            pipeline_meta=pipeline_meta,
            error=e,
            user_message="The model took too long to respond. Please try again.",
        )

    except Exception as e:
        await _fail_turn(
            message=message,
            memory=memory,
            pipeline_meta=pipeline_meta,
            error=e,
            user_message=_route_pipeline_error(str(e)),
            log_level="exception",
        )
