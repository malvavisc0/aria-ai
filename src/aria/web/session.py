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
from pathlib import Path

import chainlit as cl
from chainlit.types import ThreadDict
from llama_index.core.base.llms.types import (
    ChatMessage,
    MessageRole,
    ToolCallBlock,
)
from llama_index.core.memory import Memory
from loguru import logger
from PIL import Image

from aria.config.folders import Uploads as UploadsConfig
from aria.config.folders import Workspace as WorkspaceConfig
from aria.config.models import Embeddings as EmbeddingsConfig
from aria.llm import get_default_memory
from aria.web.state import ROOT_MESSAGE_TYPES, _state

# Maximum dimension (width or height) for images sent to the vision API.
# Larger images are resized to prevent processor failures in vLLM
# (e.g. Qwen3VLProcessor crashing on 3840×2160 images).
_MAX_VISION_DIMENSION = 1024

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


def create_memory(thread_id: str) -> Memory:
    """Create a new conversation memory instance for a thread.

    Initializes memory with vector database and embeddings model
    for storing conversation history.

    Args:
        thread_id: Unique identifier for the conversation thread.

    Returns:
        Memory: Configured memory instance for the thread.

    Raises:
        ValueError: If thread_id is None or empty.
    """
    if not thread_id:
        raise ValueError("thread_id cannot be None or empty")

    vector_db = _state.vector_db
    assert vector_db is not None
    embed_model = _state.embeddings
    assert embed_model is not None
    return get_default_memory(
        vector_db=vector_db,
        thread_id=thread_id,
        embed_model=embed_model,
        token_limit=EmbeddingsConfig.token_limit,
        llm=_state.llm,
    )


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

    UploadsConfig.path.mkdir(parents=True, exist_ok=True)

    paths = []
    for element in message.elements:
        info = _ElementInfo(element)
        if not info.path or info.is_image:
            continue

        src = Path(info.path)
        dest_name = info.name or src.name
        thread_id = getattr(message, "thread_id", None) or "thread"
        dest = UploadsConfig.path / (
            f"{thread_id}_{uuid.uuid4().hex}_{Path(dest_name).name}"
        )

        try:
            shutil.copy2(info.path, dest)
            paths.append(str(dest))
        except OSError:
            logger.warning(f"Failed to copy uploaded file {info.path} to {dest}")
            paths.append(info.path)
    return paths


# MIME types / extensions supported by MarkItDown for document conversion
_MARKITDOWN_MIME_TYPES = {
    # Documents
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    # Structured data & markup
    "text/csv",
    "text/html",
    "application/json",
    "application/xml",
    "text/xml",
    "application/x-yaml",
    "text/yaml",
    "text/x-yaml",
    "application/toml",
    # Plain text & code
    "text/plain",
    "text/markdown",
    "text/x-python",
    "text/x-script",
}
_MARKITDOWN_EXTENSIONS = {
    # Documents
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    # Structured data & markup
    ".csv",
    ".html",
    ".htm",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".toml",
    # Plain text & code
    ".txt",
    ".md",
    ".rst",
    ".py",
    ".js",
    ".ts",
    ".sh",
    ".log",
    ".ini",
    ".cfg",
}


def convert_documents_to_markdown(
    file_paths: list[str],
) -> list[dict]:
    """Convert uploaded documents to markdown using MarkItDown.

    For each file path, attempts conversion via MarkItDown and saves
    the resulting markdown file into the agent workspace
    (``~/.aria/workspace/uploads/``).

    Args:
        file_paths: List of uploaded file paths to convert.

    Returns:
        A list of dicts with keys:
            - original_path: str (path to the uploaded file)
            - markdown_path: str | None (path to converted .md, or None on failure)
            - name: str (original filename)
            - lines: int (line count of converted file)
            - chars: int (character count of converted file)
            - error: str | None (error message if conversion failed)
    """
    if not file_paths:
        return []

    workspace_uploads = WorkspaceConfig.path / "uploads"
    workspace_uploads.mkdir(parents=True, exist_ok=True)

    try:
        from markitdown import MarkItDown

        converter = MarkItDown()
    except Exception as e:
        logger.warning(f"MarkItDown unavailable, skipping conversion: {e}")
        converter = None

    results = []
    for file_path in file_paths:
        src = Path(file_path)
        ext = src.suffix.lower()

        # Check if file is convertible
        if ext not in _MARKITDOWN_EXTENSIONS:
            results.append(
                {
                    "original_path": file_path,
                    "markdown_path": None,
                    "name": src.name,
                    "lines": 0,
                    "chars": 0,
                    "error": None,
                }
            )
            continue

        if converter is None:
            results.append(
                {
                    "original_path": file_path,
                    "markdown_path": None,
                    "name": src.name,
                    "lines": 0,
                    "chars": 0,
                    "error": "MarkItDown unavailable",
                }
            )
            continue

        try:
            result = converter.convert(file_path)
            md_content = result.text_content or ""

            md_name = f"{src.stem}.md"
            md_dest = workspace_uploads / md_name
            # Avoid collisions
            if md_dest.exists():
                md_dest = workspace_uploads / f"{src.stem}_{uuid.uuid4().hex[:8]}.md"

            md_dest.write_text(md_content, encoding="utf-8")

            line_count = len(md_content.splitlines())
            results.append(
                {
                    "original_path": file_path,
                    "markdown_path": str(md_dest),
                    "name": src.name,
                    "lines": line_count,
                    "chars": len(md_content),
                    "error": None,
                }
            )
            logger.debug(
                f"Converted {src.name} to markdown: {md_dest} "
                f"({line_count} lines, {len(md_content)} chars)"
            )
        except Exception as e:
            logger.warning(f"MarkItDown conversion failed for {src.name}: {e}")
            results.append(
                {
                    "original_path": file_path,
                    "markdown_path": None,
                    "name": src.name,
                    "lines": 0,
                    "chars": 0,
                    "error": str(e),
                }
            )

    return results


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


async def restore_chat_history(thread: ThreadDict) -> Memory:
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
        Memory: Memory instance populated with conversation history.

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

    # Include ALL user/assistant messages regardless of parentId.
    # get_thread() returns the raw tree where assistant messages are
    # children of user messages (parentId != None), so filtering on
    # parentId == None would silently drop every assistant reply.
    conversation_steps = [m for m in chat_steps if m.get("type") in ROOT_MESSAGE_TYPES]
    conversation_steps.sort(
        key=lambda message_step: (
            message_step.get("createdAt") or message_step.get("created_at") or "",
            message_step.get("id") or "",
        )
    )
    logger.debug(f"Found {len(conversation_steps)} conversation messages")

    memory = create_memory(thread_id)

    raw_history: list[ChatMessage] = []
    for message_step in conversation_steps:
        content = message_step.get("output", "")
        message_type = message_step.get("type")

        if not content:
            continue

        role = (
            MessageRole.USER
            if message_type == "user_message"
            else MessageRole.ASSISTANT
        )
        raw_history.append(ChatMessage(role=role, content=content))

    chat_history = _sanitize_chat_history(raw_history, drop_trailing_user=False)
    if len(raw_history) != len(chat_history):
        logger.debug(
            f"Sanitised chat history: {len(raw_history)} → {len(chat_history)} "
            f"messages (removed non-alternating roles)"
        )

    # Use aput_messages instead of aset to enforce token_limit.
    # aset() bypasses _manage_queue() and dumps ALL messages unbounded.
    # aput_messages() triggers the waterfall logic: when the buffer
    # exceeds token_limit * chat_history_token_ratio, oldest messages
    # are flushed to memory blocks (FactExtraction, Vector).
    if chat_history:
        await memory.aput_messages(chat_history)

    logger.info(f"Restored {len(chat_history)} messages for thread {thread_id}")
    return memory
