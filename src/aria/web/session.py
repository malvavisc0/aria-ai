"""Session management for the Aria web UI.

This module provides functions for:
- Creating and managing conversation memory per thread
- Waiting for application initialization
- Extracting file paths from uploaded files
- Restoring chat history when resuming a session

These utilities support the Chainlit chat interface by managing
persistent conversation state across messages and sessions.
"""

from __future__ import annotations

import base64
import io
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path

import chainlit as cl
from chainlit.types import ThreadDict
from llama_index.core.base.llms.types import (
    ChatMessage,
    MessageRole,
    ToolCallBlock,
)
from loguru import logger
from PIL import Image

from aria.config.folders import Workspace as WorkspaceConfig
from aria.config.models import Embeddings as EmbeddingsConfig
from aria.llm import get_default_memory
from aria.llm.memory import BackgroundFlushMemory, wrap_memory
from aria.web.state import ROOT_MESSAGE_TYPES, _state

# Maximum dimension (width or height) for images sent to the vision API.
# Larger images are resized to prevent processor failures in vLLM
# (e.g. Qwen3VLProcessor crashing on 3840×2160 images).
_MAX_VISION_DIMENSION = 1024

# Fraction of the memory queue budget used when restoring history on
# resume.  Filling the budget exactly would make the very next message
# cross the waterfall threshold and re-embed turns that are already
# stored, so the restored tail is deliberately kept below it.
_RESUME_BUDGET_HEADROOM = 0.9

# Image MIME types and extensions for detection
_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/tiff",
}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}

# Extension → MIME mapping for image uploads.  Required because naive
# ``image/{ext}`` synthesis produces unregistered types such as
# ``image/jpg`` and ``image/tif`` which some vision endpoints reject.
_IMAGE_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def _mime_for_image(mime: str, ext: str) -> str:
    """Resolve a MIME type for an image element.

    Prefers the element's declared MIME, then a known extension mapping,
    then falls back to ``image/{ext}`` only for extensions we don't map.
    """
    if mime:
        return mime
    return _IMAGE_MIME_BY_EXT.get(ext, f"image/{ext.lstrip('.')}")


class _ElementInfo:
    """Normalised view of a Chainlit file element.

    Centralises the mime/extension/image-detection logic shared by
    :func:`extract_image_data` and :func:`extract_file_paths` so the two
    don't drift apart.
    """

    __slots__ = ("path", "mime", "name", "ext")

    def __init__(self, element) -> None:
        self.path = str(getattr(element, "path", None) or "")
        self.mime = getattr(element, "mime", "") or ""
        name = getattr(element, "name", "") or ""
        self.name = name
        self.ext = Path(name).suffix.lower() if name else Path(self.path).suffix.lower()

    @property
    def is_image(self) -> bool:
        return (self.mime in _IMAGE_MIME_TYPES) or (self.ext in _IMAGE_EXTENSIONS)


def create_memory(thread_id: str) -> BackgroundFlushMemory:
    """Create a new conversation memory instance for a thread.

    Returns a :class:`BackgroundFlushMemory` wrapper that delegates
    every ``Memory`` call but runs the embedding waterfall
    (``_manage_queue``) as a background task so live turns never
    block on the ~18s/batch flush cost.  See
    ``aria.web.memory_flush`` and ``docs/fix-chat-resume-freeze.md``.

    Args:
        thread_id: Unique identifier for the conversation thread.

    Returns:
        Memory instance for the thread.

    Raises:
        ValueError: If thread_id is None or empty.
    """
    if not thread_id:
        raise ValueError("thread_id cannot be None or empty")

    vector_db = _state.vector_db
    assert vector_db is not None
    embed_model = _state.embeddings
    assert embed_model is not None
    return wrap_memory(
        get_default_memory(
            vector_db=vector_db,
            thread_id=thread_id,
            embed_model=embed_model,
            token_limit=EmbeddingsConfig.token_limit,
        )
    )


async def drain_memory(memory: BackgroundFlushMemory | None) -> None:
    """Await outstanding background flush work before discarding *memory*.

    Must be called every time a memory instance is dropped or replaced
    (session end, thread switch, edit reset).  Without it the in-flight
    ``_manage_queue`` task is orphaned and those turns are never
    embedded into Chroma, so they are lost once the trimmed history no
    longer contains them.

    Never raises: a failed drain must not break the surrounding
    lifecycle event.
    """
    if memory is None:
        return
    try:
        await memory.drain()
    except Exception:
        logger.warning("Failed to drain background memory flush", exc_info=True)


async def wait_for_initialization(timeout: float = 30.0) -> bool:
    """Wait for the application state to be fully initialized.

    Args:
        timeout: Maximum time to wait in seconds (default: 30.0).

    Returns:
        bool: True if initialization completed, False if timeout reached.
    """
    import asyncio

    try:
        await asyncio.wait_for(_state.startup_event.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False


def _resize_image_for_vision(
    image_bytes: bytes, max_dim: int = _MAX_VISION_DIMENSION
) -> bytes:
    """Resize an image if it exceeds *max_dim* on either side.

    Maintains the original aspect ratio.  Returns the (possibly resized)
    image bytes as JPEG.  If the image is already within bounds the
    original bytes are returned unchanged.

    Args:
        image_bytes: Raw image file bytes.
        max_dim: Maximum allowed width or height in pixels.

    Returns:
        Image bytes, resized if necessary.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
    except Exception:
        # Cannot open — return original bytes and let the API decide.
        return image_bytes

    w, h = img.size
    if w <= max_dim and h <= max_dim:
        return image_bytes

    ratio = min(max_dim / w, max_dim / h)
    new_size = (int(w * ratio), int(h * ratio))
    img = img.resize(new_size, Image.Resampling.LANCZOS)
    logger.debug(
        f"Resized image from {w}×{h} to {new_size[0]}×{new_size[1]} "
        f"for vision API (max {max_dim}px)"
    )

    buf = io.BytesIO()
    # Preserve original format; fall back to JPEG.
    fmt = img.format or "JPEG"
    if fmt.upper() == "JPEG":
        img.save(buf, format=fmt, quality=85)
    else:
        img.save(buf, format=fmt)
    return buf.getvalue()


def extract_image_data(message: cl.Message) -> list[dict]:
    """Extract base64-encoded image data from uploaded file elements.

    Images larger than ``_MAX_VISION_DIMENSION`` on either side are
    resized before encoding to prevent processor failures in the vision
    model (e.g. Qwen3VLProcessor crashing on 3840×2160 images).

    Returns a list of dicts with keys:
        - mime_type: str (e.g. "image/jpeg")
        - base64: str (base64-encoded image data)
        - name: str (original filename)
    """
    if not message.elements:
        return []

    images = []
    for element in message.elements:
        info = _ElementInfo(element)
        if not info.path or not info.is_image:
            continue

        try:
            with open(info.path, "rb") as f:
                raw = f.read()
            raw = _resize_image_for_vision(raw)
            data = base64.b64encode(raw).decode("utf-8")
            images.append(
                {
                    "mime_type": _mime_for_image(info.mime, info.ext),
                    "base64": data,
                    "name": info.name,
                }
            )
        except OSError as e:
            logger.warning(f"Failed to read image {info.path}: {e}")

    return images


def extract_file_paths(message: cl.Message) -> list[str]:
    """Extract file paths from uploaded file elements in a message.

    Skips image files — those are handled separately by extract_image_data().
    """
    if not message.elements:
        return []

    uploads = WorkspaceConfig.path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)

    paths = []
    for element in message.elements:
        info = _ElementInfo(element)
        if not info.path or info.is_image:
            continue

        src = Path(info.path)
        dest_name = info.name or src.name
        thread_id = getattr(message, "thread_id", None) or "thread"
        safe_thread = Path(thread_id).name
        dest = uploads / f"{safe_thread}_{uuid.uuid4().hex}_{Path(dest_name).name}"

        try:
            shutil.copy2(info.path, dest)
            paths.append(str(dest))
        except OSError:
            logger.warning(f"Failed to copy uploaded file {info.path} to {dest}")
            paths.append(info.path)
    return paths


def _message_tool_call_count(msg: ChatMessage) -> int:
    """Return the number of tool calls advertised by an assistant message.

    LlamaIndex carries tool calls in two places (mirroring
    ``to_openai_message_dict``'s precedence): ``ToolCallBlock`` objects in
    ``msg.blocks`` (modern path) or ``additional_kwargs["tool_calls"]``
    (legacy/streaming path).  Blocks take precedence; the kwargs list is
    only consulted when no blocks are present.
    """
    block_calls = sum(1 for block in msg.blocks if isinstance(block, ToolCallBlock))
    if block_calls:
        return block_calls
    kwarg_calls = msg.additional_kwargs.get("tool_calls")
    if kwarg_calls:
        return len(kwarg_calls)
    return 0


def _is_tool_message(msg: ChatMessage) -> bool:
    """True if *msg* is a tool-result message (``role == TOOL``)."""
    return msg.role == MessageRole.TOOL


def _deduplicate_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Step 1: Collapse consecutive duplicate roles (keep last of each run).

    Never collapse tool messages or assistant-with-tool-call messages.
    """
    deduplicated: list[ChatMessage] = []
    for msg in messages:
        prev = deduplicated[-1] if deduplicated else None
        can_collapse = (
            prev is not None
            and prev.role == msg.role
            and not _is_tool_message(msg)
            and _message_tool_call_count(prev) == 0
            and _message_tool_call_count(msg) == 0
        )
        if can_collapse:
            deduplicated[-1] = msg  # replace — keep latest
        else:
            deduplicated.append(msg)
    return deduplicated


def _validate_tool_groups(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Step 2: Validate tool groups.

    Keep an assistant tool-call message only if exactly N matching tool
    messages follow it; drop orphan tool messages.
    """
    validated: list[ChatMessage] = []
    i = 0
    n = len(messages)
    while i < n:
        msg = messages[i]

        if _is_tool_message(msg):
            # Orphan tool message — drop.
            i += 1
            continue

        call_count = _message_tool_call_count(msg)
        if call_count > 0:
            # Gather the immediately following tool messages.
            j = i + 1
            tool_msgs: list[ChatMessage] = []
            while j < n and _is_tool_message(messages[j]):
                tool_msgs.append(messages[j])
                j += 1

            if len(tool_msgs) >= call_count:
                # Keep the assistant message plus exactly call_count tool
                # responses.
                validated.append(msg)
                validated.extend(tool_msgs[:call_count])
            # else: dangling/partial group — drop.
            i = j
            continue

        validated.append(msg)
        i += 1

    return validated


def _trim_history(
    messages: list[ChatMessage], drop_trailing_user: bool
) -> list[ChatMessage]:
    """Steps 3 & 4: Trim leading non-user and trailing incomplete.

    Drop leading messages until history starts with user.
    Drop trailing assistant with unfulfilled tool calls.
    Drop trailing user when drop_trailing_user is True.
    """
    # Step 3: Ensure it starts with a user message.
    while messages and messages[0].role != MessageRole.USER:
        messages.pop(0)

    # Step 4: Ensure it ends on a clean boundary.
    while messages:
        last = messages[-1]
        if _message_tool_call_count(last) > 0:
            messages.pop()
        elif drop_trailing_user and last.role == MessageRole.USER:
            messages.pop()
        else:
            break

    return messages


def _sanitize_chat_history(
    chat_history: list[ChatMessage],
    *,
    drop_trailing_user: bool = True,
) -> list[ChatMessage]:
    """Repair chat history so it is valid for the OpenAI/Mistral API.

    Mistral's chat template enforces a strict invariant: every assistant
    message that advertises ``N`` tool calls must be immediately followed
    by exactly ``N`` ``tool`` (result) messages, otherwise it raises
    ``InvalidMessageStructureException: Not the same number of function
    calls and responses``.  The OpenAI-compatible API additionally
    requires alternating ``user``/``assistant`` roles for plain turns.

    This helper enforces both invariants while being **tool-call aware**:

    1. Collapse consecutive duplicate roles (keep last of each run) — but
       never collapse ``tool`` messages (parallel tool calls legitimately
       produce several consecutive ``tool`` messages) and never collapse
       an assistant message that carries tool calls into an adjacent
       assistant message.
    2. Validate tool groups: for each assistant message advertising ``N``
       tool calls, consume the next ``N`` consecutive ``tool`` messages.
       If fewer than ``N`` follow (dangling/partial group left by a failed
       turn), drop the whole group.  Drop orphan ``tool`` messages that
       have no preceding assistant tool-call.
    3. Drop leading messages until the history starts with a ``user``
       message (without splitting a tool group).
    4. Drop a trailing incomplete tool group so the history ends on a
       clean boundary (assistant final answer or user message).  When
       *drop_trailing_user* is True (the pre-run path, where a new user
       message is about to be appended), a trailing ``user`` message is
       also removed so the next turn maintains alternation.  When False
       (the resume/restore path), a trailing ``user`` is kept so the
       user's last message is not silently lost from context.

    Args:
        chat_history: Raw chat messages (may have consecutive duplicates
            and/or unbalanced tool sequences).
        drop_trailing_user: If True, drop a trailing ``user`` message so
            the next appended user message alternates correctly.  Pass
            False when restoring history for resume, where there is no
            immediate follow-up user message.

    Returns:
        A sanitised list whose tool-call/response counts are balanced and
        whose plain turns alternate ``user → assistant``.
    """
    if not chat_history:
        return chat_history

    # Process through the pipeline
    step1 = _deduplicate_messages(chat_history)
    step2 = _validate_tool_groups(step1)
    step3 = _trim_history(step2, drop_trailing_user)

    return step3


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


async def _sanitize_memory(memory: BackgroundFlushMemory) -> None:
    """Ensure memory chat history has valid user/assistant alternation.

    After a failed live turn the ``Memory`` chat store may contain a
    trailing user message with no matching assistant reply (or other
    alternation violations).  This normalises the history so the next
    model invocation sees strictly alternating roles.

    Reads via ``memory.aget_all()`` (raw chat store, no injected vector
    context) and writes via ``memory.aset()`` (replaces without running
    the token-limit waterfall).  Both are required: ``aget`` would
    splice the retrieved block output into the last user message and a
    subsequent ``set`` would persist that injected blob permanently.
    """
    messages = await memory.aget_all()
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
        await memory.aset(sanitized)


async def _rollback_memory(memory: BackgroundFlushMemory | None) -> None:
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
        messages = await memory.aget_all()
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
            await memory.aset(repaired)
    except Exception:
        logger.warning("Failed to rollback memory", exc_info=True)


class _EditThreadMissingError(RuntimeError):
    """Raised when a thread cannot be found while applying a message edit."""


async def _reset_memory_for_edit(
    thread_id: str,
) -> BackgroundFlushMemory:
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
    from aria.web.hooks import get_data_layer_handler

    try:
        if _state.vector_db is not None:
            _state.vector_db.delete_collection(thread_id)
    except Exception:
        logger.debug(
            f"Could not delete vector collection for {thread_id}",
            exc_info=True,
        )

    data_layer = get_data_layer_handler()
    thread = await data_layer.get_thread(thread_id)
    if not thread:
        raise _EditThreadMissingError(
            f"Thread {thread_id} not found; cannot apply edit to a thread "
            "that no longer exists."
        )
    return await restore_chat_history(thread)


def _last_user_assistant_pair(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Return the last ``user`` message and whatever follows it.

    Used as a fallback by ``_trim_to_budget`` when the budget is so
    small that the backward walk only collected assistant messages
    (which are then dropped to enforce the user-first constraint).
    Guarantees at least one turn survives so resume never leaves
    memory empty.
    """
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == MessageRole.USER:
            return messages[i : i + 2]
    return messages[-1:] if messages else []


def _trim_to_budget(
    messages: list[ChatMessage],
    budget: int,
    token_counter: Callable[[ChatMessage], int],
) -> list[ChatMessage]:
    """Keep only the newest tail of *messages* that fits within *budget* tokens.

    Walks from the newest message backwards and keeps messages whose
    cumulative token count stays within *budget*.  Two constraints from
    ``Memory._manage_queue`` are enforced so the result is safe to feed
    straight into ``Memory.aset``:

    1. The returned list must start with a ``user`` message.
    2. The trailing ``user → assistant`` pair is kept even when it
       pushes the tail over the budget, so the newest user turn is
       never silently lost.

    A single message larger than the budget is kept so nothing
    disappears.

    *token_counter* should be the live memory's ``_estimate_token_count``
    so no second tokenizer is constructed.

    Returns a fresh list; *messages* is not mutated.
    """
    tail: list[ChatMessage] = []
    running = 0
    for msg in reversed(messages):
        msg_tok = token_counter(msg)
        if running + msg_tok > budget and tail:
            break
        running += msg_tok
        tail.append(msg)
    if not tail:
        return []

    # Drop trailing non-user messages so the result starts with a user turn.
    while tail and tail[-1].role != MessageRole.USER:
        tail.pop()
    if not tail:
        # The newest messages were all assistant and exceeded the budget.
        # Force-include the last user→assistant pair so the newest turn
        # is never silently lost, even if it exceeds the budget.
        return _last_user_assistant_pair(messages)

    return list(reversed(tail))


def _collect_conversation_steps(chat_steps: list) -> list:
    conversation = [m for m in chat_steps if m.get("type") in ROOT_MESSAGE_TYPES]
    conversation.sort(
        key=lambda message_step: (
            message_step.get("createdAt") or message_step.get("created_at") or "",
            message_step.get("id") or "",
        )
    )
    return conversation


def _step_to_chat_message(step) -> ChatMessage | None:
    content = step.get("output", "")
    if not content:
        return None
    role = (
        MessageRole.USER
        if step.get("type") == "user_message"
        else MessageRole.ASSISTANT
    )
    return ChatMessage(role=role, content=content)


async def restore_chat_history(thread: ThreadDict) -> BackgroundFlushMemory:
    """Restore conversation history from a thread dictionary.

    Creates memory for the thread and populates it with messages
    from the thread's history.

    Steps are collected regardless of their ``parentId`` because
    ``get_thread()`` returns the raw parent-child structure where
    assistant messages are children of user messages (not root-level).
    The history is then sanitised to guarantee strictly alternating
    ``user → assistant`` roles required by the LLM API.

    Args:
        thread: Thread dictionary containing conversation steps.

    Returns:
        Populated memory instance for the thread.

    Raises:
        ValueError: If thread does not contain a valid 'id' field.
    """
    thread_id = thread.get("id")
    if not thread_id:
        raise ValueError("Thread dictionary must contain a valid 'id' field")

    thread_name = thread.get("name", "Unnamed")
    logger.debug(f"Restoring chat history for thread {thread_id} ({thread_name})")

    chat_steps = thread.get("steps", [])
    logger.debug(f"Thread contains {len(chat_steps)} total steps")

    conversation_steps = _collect_conversation_steps(chat_steps)
    logger.debug(f"Found {len(conversation_steps)} conversation messages")

    memory = create_memory(thread_id)

    raw_history: list[ChatMessage] = [
        msg
        for msg in (_step_to_chat_message(step) for step in conversation_steps)
        if msg is not None
    ]

    chat_history = _sanitize_chat_history(raw_history, drop_trailing_user=False)
    if len(raw_history) != len(chat_history):
        logger.debug(
            f"Sanitised chat history: {len(raw_history)} → {len(chat_history)} "
            f"messages (removed non-alternating roles)"
        )

    # Trim to the memory queue budget so the first aput stays free.
    # Without trimming, the full history exceeds the token budget and
    # triggers the embedding waterfall (~18s) on every resume.  The
    # headroom keeps the restored tail just below the threshold so the
    # first new message does not immediately re-cross it.
    budget = int(
        EmbeddingsConfig.token_limit
        * EmbeddingsConfig.chat_history_token_ratio
        * _RESUME_BUDGET_HEADROOM
    )
    trimmed = _trim_to_budget(chat_history, budget, memory._estimate_token_count)
    dropped = chat_history[: len(chat_history) - len(trimmed)]
    logger.debug(
        f"Trimmed chat history: {len(chat_history)} → {len(trimmed)} "
        f"messages (budget={budget} tok, {len(dropped)} dropped)"
    )
    if trimmed:
        await memory.aset(trimmed)

    # The dropped turns must still be retrievable.  They are only in
    # Chroma if a previous session flushed them, which is not guaranteed
    # if that session was killed before it could drain.  Re-embedding is
    # idempotent (content-hashed node IDs), so replaying them costs
    # nothing when they are already stored.
    memory.schedule_embed(dropped)

    logger.info(f"Restored {len(trimmed)} messages for thread {thread_id}")
    return memory
