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
    sanitized = _sanitize_chat_history(messages)
    if len(sanitized) != len(messages):
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
        repaired = _sanitize_chat_history(messages)
        if len(repaired) != len(messages):
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


async def _reset_memory_for_edit(
    thread_id: str,
) -> Memory:
    """Reset and rebuild memory after a message edit.

    Deletes the vector collection for the thread, creates fresh
    memory, and restores chat history from the persisted thread
    data (which Chainlit has already updated with the edited
    content).
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
    if thread:
        memory = await restore_chat_history(thread)
    else:
        logger.warning(f"No thread found for {thread_id} during edit reset")
    return memory


async def _describe_image(mime_type: str, base64_data: str, prompt: str) -> str:
    """Send an image to the vision endpoint and get a text description.

    Uses the same vLLM endpoint configured for the main chat model.
    Returns a concise description (~2-3 sentences) suitable for context.
    """
    image_url = f"data:{mime_type};base64,{base64_data}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{ChatConfig.api_url}/chat/completions",
            headers={"Authorization": f"Bearer {VllmConfig.api_key}"},
            json={
                "model": ChatConfig.model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt,
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": image_url},
                            },
                        ],
                    }
                ],
                "max_tokens": 256,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"] or ""


async def _handle_message(
    message: cl.Message,
) -> tuple[str, dict]:
    """Process and enhance a user message before agent execution.

    Handles prompt enhancement if requested via command, extracts
    file paths from uploaded files, and describes uploaded images
    via the vision API.

    Args:
        message: The incoming Chainlit message from the user.

    Returns:
        A ``(prompt, metadata)`` tuple where *prompt* is the
        processed prompt string and *metadata* is a dict of
        pipeline metadata to persist alongside the message.
    """
    prompt = message.content
    meta: dict = {}

    if message.command == "Enhance":
        if not _state.prompt_enhancer:
            logger.warning("Prompt enhancer not available, returning original prompt")
            return prompt, meta
        try:
            response = await asyncio.wait_for(
                _state.prompt_enhancer.run(user_msg=message.content),
                timeout=30.0,
            )
            results = response.structured_response
            if isinstance(results, dict):
                results = PromptEnhancementResult(**results)
            prompt = results.enhanced
            meta["prompt_enhanced"] = True
            logger.debug("Prompt enhancement completed successfully")
        except Exception as e:
            logger.error(f"Prompt enhancement failed: {e}")
            # Notify user so they know the original prompt was used
            await cl.ErrorMessage(
                content="Prompt enhancement failed, using original prompt.",
            ).send()

    # Deduplicate while preserving order (same file attached twice)
    file_paths = list(dict.fromkeys(extract_file_paths(message)))
    image_data = extract_image_data(message)

    if file_paths:
        meta["attachments"] = [Path(p).name for p in file_paths]

    # Non-image files → convert documents to markdown, pass metadata
    if file_paths:
        conversions = convert_documents_to_markdown(file_paths)
        file_lines = []
        for conv in conversions:
            if conv["markdown_path"]:
                file_lines.append(
                    f"- {conv['name']} (original: {conv['original_path']})\n"
                    f"  Converted to markdown: {conv['markdown_path']} "
                    f"({conv['lines']} lines, {conv['chars']} chars)"
                )
            elif conv["error"]:
                file_lines.append(
                    f"- {conv['name']}: {conv['original_path']} "
                    f"(conversion failed: {conv['error']})"
                )
            else:
                file_lines.append(f"- {conv['original_path']}")
        paths_block = "\n".join(file_lines)
        prompt = f"{prompt}\n\n[Uploaded files]:\n{paths_block}"
        logger.debug(f"Appended {len(file_paths)} file path(s) to prompt")

    # Images → vision description
    _IMAGE_DESCRIBE_PROMPT = "Describe this image concisely in 2-3 sentences."
    if image_data and VllmConfig.vision_enabled:
        descriptions = []
        for i, img in enumerate(image_data, 1):
            try:
                desc = await _describe_image(
                    img["mime_type"], img["base64"], _IMAGE_DESCRIBE_PROMPT
                )
                descriptions.append(f"[Image {i} ({img['name']})]: {desc}")
            except Exception as e:
                logger.warning(f"Vision description failed for {img['name']}: {e}")
                descriptions.append(
                    f"[Image {i} ({img['name']})]: <description unavailable>"
                )

        if descriptions:
            images_block = "\n".join(descriptions)
            prompt = f"{prompt}\n\n[Attached images]:\n{images_block}"
            logger.debug(f"Described {len(descriptions)} image(s) via vision API")
    elif image_data:
        # Vision disabled — mention images without describing them
        mentions = [
            f"[Image {i} ({img['name']})]: <vision disabled — enable ARIA_VLLM_VISION_ENABLED>"
            for i, img in enumerate(image_data, 1)
        ]
        prompt = f"{prompt}\n\n[Attached images]:\n" + "\n".join(mentions)

    # Inject thread context so Aria can pass --thread-id when spawning workers
    thread_id = message.thread_id
    if thread_id:
        prompt = f"{prompt}\n\n[Thread ID: {thread_id}]"
        logger.debug(f"Injected thread_id={thread_id} into prompt")

    return prompt, meta


async def _stream_agent_response(
    handler: WorkflowHandler,
    output: cl.Message,
) -> tuple[bool, dict]:
    """Stream agent events to the UI and return whether output was emitted.

    Iterates over the agent's streaming events, manages thinking-block
    rendering and tool-call steps.  Thinking content is detected via
    LlamaIndex's ``AgentStream.thinking_delta`` field (both XML-tag and
    structured-reasoning styles are handled upstream by the framework).

    Args:
        handler: The running agent workflow handler (with ``stream_events``
            and ``__await__``).
        output: The Chainlit message to stream tokens into.

    Returns:
        A ``(emitted, metadata)`` tuple where *emitted* indicates
        whether any visible content was streamed and *metadata*
        contains execution statistics.
    """
    current_step: cl.Step | None = None
    emitted = False
    thinking_opened = False
    tools_called: list[str] = []
    has_thinking = False

    async for event in handler.stream_events():
        if isinstance(event, ToolCall):
            tools_called.append(event.tool_name or "unknown")
            await maybe_remove_step(current_step)
            if thinking_opened:
                await output.stream_token(_BLOCKQUOTE_END)
                thinking_opened = False
            current_step = await send_tool_step(event)

        elif isinstance(event, AgentStream):
            # LlamaIndex separates thinking from content via thinking_delta
            if event.thinking_delta:
                has_thinking = True
                if not thinking_opened:
                    await maybe_remove_step(current_step)
                    current_step = None
                    await output.stream_token(_BLOCKQUOTE_PREFIX)
                    thinking_opened = True
                    emitted = True
                await output.stream_token(event.thinking_delta.replace("\n", "\n> "))
            elif event.delta:
                if thinking_opened:
                    await output.stream_token(_BLOCKQUOTE_END)
                    thinking_opened = False
                await output.stream_token(event.delta)
                emitted = True

        elif isinstance(event, AgentOutput):
            if not event.tool_calls:
                # Final output — clean up UI state
                if current_step is not None:
                    await maybe_remove_step(current_step)
                    current_step = None
                if thinking_opened:
                    await output.stream_token(_BLOCKQUOTE_END)
                    thinking_opened = False
            # Emit any text that wasn't already streamed
            if not emitted and event.response.content:
                await output.stream_token(event.response.content)
                emitted = True

    # Always await the handler to retrieve the final result and avoid
    # unawaited-coroutine warnings.
    try:
        handler_result = await handler
    except Exception:
        if thinking_opened:
            await output.stream_token(_BLOCKQUOTE_END)
            thinking_opened = False
        raise

    # Fallback — use the final result if nothing was streamed
    if not emitted:
        content = getattr(handler_result.response, "content", None) or ""
        if content:
            await output.stream_token(content)
            emitted = True

    if thinking_opened:
        await output.stream_token(_BLOCKQUOTE_END)

    if not emitted:
        logger.warning("No assistant output emitted for message.")
        await output.stream_token(
            "I wasn't able to generate a response. Please try rephrasing your request."
        )
        emitted = True

    stream_meta = {
        "tools_called": tools_called,
        "has_thinking": has_thinking,
    }
    return emitted, stream_meta


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
        logger.warning("Message received but agents_workflow is not configured")
        await cl.Message(
            content=(
                "The system is not fully initialized (LLM unavailable). "
                "Please check server logs and try again later."
            )
        ).send()
        return

    memory: Memory | None = None
    pipeline_meta: dict = {}
    try:
        _state.validate_initialized()
        prompt, pipeline_meta = await _handle_message(message)

        # --- Edit detection via metadata marker ---
        is_edit = bool(message.metadata and message.metadata.get(_PROCESSED_KEY))
        memory = cl.user_session.get("memory")
        # Reuse existing memory only if it belongs to the same thread;
        # Memory.session_id is set by create_memory() to the thread_id.
        if memory is None or memory.session_id != message.thread_id:
            memory = create_memory(message.thread_id)
            cl.user_session.set("memory", memory)
            logger.debug(f"Created new Memory for thread {message.thread_id}")

        if is_edit:
            logger.info(
                f"Edit detected for message {message.id}, "
                "resetting memory from persisted history"
            )
            memory = await _reset_memory_for_edit(
                message.thread_id,
            )
            cl.user_session.set("memory", memory)

        # Repair broken alternation left by a previous failed turn
        # before handing the memory to the workflow.
        await _sanitize_memory(memory)

        handler = _state.agents_workflow.run(
            user_msg=prompt,
            memory=memory,
            max_iterations=ChatConfig.max_iteration,
        )

        output = cl.Message(content="")
        _run_succeeded = False
        stream_meta: dict = {}
        try:
            _, stream_meta = await _stream_agent_response(handler, output)
            _run_succeeded = True
        finally:
            all_meta = {**pipeline_meta, **stream_meta}
            if _run_succeeded:
                await output.send()
                # Mark as processed only after successful completion
                # so failed runs don't falsely trigger edit detection
                # on retry/re-delivery.
                await _mark_message_processed(message, extra_metadata=all_meta)
            else:
                # Don't persist partial/incomplete assistant
                # content to the data layer — remove the
                # placeholder instead.
                await output.remove()

    except AppStateNotInitializedError as e:
        logger.error(f"App state not initialized: {e}")
        await _rollback_memory(memory)
        await _mark_message_processed(
            message,
            extra_metadata={**pipeline_meta, "error": str(e)},
            processed=False,
        )
        await cl.Message(
            content=(
                "The application is not fully initialized. "
                "Please wait a moment and try again."
            )
        ).send()

    except httpx.TimeoutException as e:
        logger.error(f"Request timed out: {e}")
        await _rollback_memory(memory)
        await _mark_message_processed(
            message,
            extra_metadata={**pipeline_meta, "error": str(e)},
            processed=False,
        )
        await cl.Message(
            content=("The model took too long to respond. Please try again.")
        ).send()

    except Exception as e:
        error_msg = str(e)
        logger.exception(f"Error processing message: {e}")
        await _rollback_memory(memory)
        await _mark_message_processed(
            message,
            extra_metadata={**pipeline_meta, "error": error_msg},
            processed=False,
        )

        if "maximum context length" in error_msg.lower():
            error_content = (
                "The conversation has grown too large for the "
                "model's context window. Please start a new "
                "conversation."
            )
        else:
            error_content = "An error occurred. Please try again."
        await cl.Message(content=error_content).send()
