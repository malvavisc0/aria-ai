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
from typing import Any

import chainlit as cl
import httpx
from loguru import logger

from aria.config.models import Chat as ChatConfig
from aria.llm.memory import BackgroundFlushMemory
from aria.web.hooks import get_data_layer_handler
from aria.web.prompt_builder import handle_message
from aria.web.rendering import create_render_elements, extract_renderable_items
from aria.web.session import (
    _EditThreadMissingError,
    _reset_memory_for_edit,
    _rollback_memory,
    _sanitize_memory,
    create_memory,
    drain_memory,
)
from aria.web.state import AppStateNotInitializedError, _state
from aria.web.streaming import stream_agent_response
from aria.web.thread_titler import maybe_title_thread

# Metadata key used to mark messages as processed (for edit detection)
_PROCESSED_KEY = "processed"

# keys so downstream consumers can rely on a stable schema.
_DEFAULT_METADATA: dict[str, Any] = {
    "tools_called": [],
    "has_thinking": False,
    "processed": False,
    "prompt_enhanced": False,
    "attachments": [],
    "error": "",
}


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


async def _workflow_init(
    message: cl.Message,
) -> tuple[BackgroundFlushMemory, str, dict, bool]:
    """Prepare memory + handler for a workflow run.

    Returns ``(memory, prompt, pipeline_meta, is_edit)``.
    """
    prompt, pipeline_meta = await handle_message(message)
    is_edit = bool(message.metadata and message.metadata.get(_PROCESSED_KEY))
    cl.user_session.set("thread_id", message.thread_id)
    memory = cl.user_session.get("memory")
    if memory is None or memory.session_id != message.thread_id:
        await drain_memory(memory)
        memory = create_memory(message.thread_id)
        cl.user_session.set("memory", memory)
        logger.debug(f"Created new Memory for thread {message.thread_id}")

    if is_edit:
        logger.info(
            f"Edit detected for message {message.id}, "
            "resetting memory from persisted history"
        )
        await drain_memory(memory)
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
    memory: BackgroundFlushMemory,
) -> dict:
    handler = _state.agents_workflow.run(  # type: ignore[union-attr]
        user_msg=prompt,
        memory=memory,
        max_iterations=ChatConfig.max_iteration,
    )
    _run_succeeded = False
    stream_meta: dict = {}
    answer_text = ""
    try:
        _, stream_meta, answer_text = await stream_agent_response(handler, output)
        _run_succeeded = True
    finally:
        if _run_succeeded:
            output.answer_text = answer_text  # type: ignore[attr-defined]
            elements = create_render_elements(*extract_renderable_items(answer_text))
            if elements:
                output.elements = elements
            await output.update()
            await _mark_message_processed(
                message, extra_metadata={**pipeline_meta, **stream_meta}
            )
        else:
            await output.remove()
    return stream_meta


async def _fail_turn(
    *,
    message: cl.Message,
    memory: BackgroundFlushMemory | None,
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


def _maybe_rename_thread(message: cl.Message, output: cl.Message) -> None:
    """Fire a background title-generation task on the first turn only.

    Uses a per-session flag (set in ``on_chat_start`` / ``on_chat_resume``)
    so titles are generated exactly once per thread and never on resumed
    conversations.  The task is fire-and-forget — failures are logged
    inside :func:`maybe_title_thread` and never reach the user.
    """
    if cl.user_session.get("thread_titled"):
        return
    cl.user_session.set("thread_titled", True)
    task = asyncio.create_task(
        maybe_title_thread(
            thread_id=message.thread_id,
            user_message=message.content,
            assistant_reply=output.content,
        )
    )
    cl.user_session.set("_pending_title_task", task)


async def on_message_handler(message: cl.Message) -> cl.Message | None:
    """Handle incoming user messages and execute the agent workflow.

    This is the main entry point for processing user messages. It:
    1. Validates app state is initialized
    2. Processes the message (enhancement, file extraction)
    3. Gets or creates memory for the thread
    4. Runs the agent workflow with streaming response
    5. Handles errors and sends appropriate feedback to user

    Returns the assistant ``cl.Message`` on the success path (used by the
    voice pipeline to capture the final text for TTS), or ``None`` on error.

    Args:
        message: The incoming Chainlit message from the user.
    """
    if not _state.agents_workflow:
        await _warn_not_initialized()
        return None

    memory: BackgroundFlushMemory | None = None
    pipeline_meta: dict = {}
    try:
        _state.validate_initialized()
        memory, prompt, pipeline_meta, _is_edit = await _workflow_init(message)

        output = await _send_empty_placeholder()
        await _stream_and_finalize(message, output, pipeline_meta, prompt, memory)

        _maybe_rename_thread(message, output)
        return output

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
