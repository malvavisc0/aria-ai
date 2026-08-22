"""Chainlit webhook handlers for the Aria web UI.

This module provides callback handlers for Chainlit events including:
- Authentication (login/logout)
- Chat session lifecycle (start, resume, end)
- Data layer initialization

These handlers are invoked by Chainlit at various points in the app lifecycle.
"""

from __future__ import annotations

import audioop  # stdlib on 3.12; audioop-lts covers 3.13+
import io
import json
import re
import wave

import chainlit as cl
import numpy as np
from chainlit.types import ThreadDict
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from aria.config.api import Voice
from aria.config.database import SQLite as SQLiteConfig
from aria.config.folders import Storage as StorageConfig
from aria.db.auth import verify_password
from aria.db.layer import SQLiteSQLAlchemyDataLayer
from aria.db.local_storage_client import LocalStorageClient
from aria.db.models import User
from aria.server.voice import (
    get_kokoro_manager,
    get_whisper_manager,
    strip_non_speech_tags,
)
from aria.web.session import (
    drain_memory,
    restore_chat_history,
    wait_for_initialization,
)
from aria.web.state import _state


class _DataLayerCache:
    instance: SQLiteSQLAlchemyDataLayer | None = None


_cache = _DataLayerCache()


def reset_data_layer_cache() -> None:
    """Clear the cached data layer (called on shutdown)."""
    _cache.instance = None


def get_data_layer_handler() -> SQLiteSQLAlchemyDataLayer:
    """Return a cached SQLite data layer instance.

    The data layer is created once and reused for all subsequent calls.
    The database engine and tables are already initialized at startup
    by lifecycle.py, so no additional setup is needed here.

    Returns:
        SQLiteSQLAlchemyDataLayer: Configured data layer instance.
    """
    if _cache.instance is not None:
        return _cache.instance

    storage_client = LocalStorageClient(
        storage_path=StorageConfig.path, base_url="/storage"
    )
    _cache.instance = SQLiteSQLAlchemyDataLayer(
        conninfo=SQLiteConfig.conn_info,
        storage_provider=storage_client,
        show_logger=True,
    )
    return _cache.instance


async def auth_callback_handler(username: str, password: str) -> cl.User | None:
    """Authenticate a user with username and password.

    Called by Chainlit during login to verify user credentials
    against the database. Returns a Chainlit User object with
    metadata if authentication succeeds, None otherwise.

    Credential failures (unknown user, wrong password) return ``None`` so
    Chainlit shows a normal "invalid credentials" outcome.  Unexpected
    errors (database down, schema issues) are **not** masked as auth
    failures — they are logged at error level and re-raised so a backend
    outage is visible rather than indistinguishable from a bad password.

    Args:
        username: The user's identifier (login name).
        password: The user's password to verify.

    Returns:
        cl.User | None: Authenticated user object with metadata,
            or None if authentication fails.
    """
    try:
        with Session(_state.db_engine) as session:
            user = session.execute(
                select(User).where(User.identifier == username)
            ).scalar_one_or_none()

            if not user:
                logger.debug(f"User not found: {username}")
                return None

            user_password = str(user.password)
            if user_password and verify_password(password, user_password):
                metadata = json.loads(str(user.metadata_))
                logger.debug(f"User authenticated: {username}")
                return cl.User(
                    identifier=str(user.identifier),
                    metadata=metadata,
                )

            logger.debug(f"Invalid password for user: {username}")
            return None

    except Exception as e:
        # Backend failure — do not disguise it as an auth failure.
        logger.error(f"Authentication backend error for user {username}: {e}")
        raise


async def on_chat_start_handler() -> None:
    """Handle the start of a new chat session.

    Called by Chainlit when a new chat session begins. Drains and clears
    any stale memory from the previous thread (so its pending embedding
    work is not orphaned) and sets up custom commands available in the
    chat interface.
    """
    await drain_memory(cl.user_session.get("memory"))
    cl.user_session.set("memory", None)
    cl.user_session.set("thread_titled", False)
    logger.debug("Starting new chat session")
    await cl.context.emitter.set_commands(
        [
            {
                "id": "Knowledge",
                "icon": "book",
                "description": "Ground answer in your documents",
                "button": None,
                "persistent": True,
                "selected": False,
            },
            {
                "id": "Enhance",
                "icon": "wand-sparkles",
                "description": "Enhance Prompt",
                "button": None,
                "persistent": True,
                "selected": False,
            },
        ]
    )


async def on_chat_end_handler() -> None:
    """Handle the end of a chat session.

    Called by Chainlit when a chat session ends (user disconnects or
    starts a new chat).  Awaits any in-flight background memory flush so
    the embedding waterfall completes before the session's memory is
    discarded — without this, trimmed-off turns are never persisted to
    Chroma.  See ``docs/fix-chat-resume-freeze.md`` (Fix 1b).
    """
    from aria.web.supervisor import cancel_all_watchers

    cancel_all_watchers()
    memory = cl.user_session.get("memory")
    if memory is None:
        return
    await drain_memory(memory)
    cl.user_session.set("memory", None)


async def on_chat_resume_handler(thread: ThreadDict) -> None:
    """Resume an existing chat session with conversation history.

    Called by Chainlit when resuming a previous chat session.
    Restores the chat memory from the thread history so the
    conversation can continue from where it left off.

    Args:
        thread: Thread dictionary containing conversation history
            and metadata from the previous session.
    """
    cl.user_session.set("thread_titled", True)
    try:
        if not _state.is_initialized():
            logger.info(
                "AppState not yet initialized, waiting for startup to complete..."
            )
            if not await wait_for_initialization():
                logger.warning(
                    "AppState initialization timed out after 30s. "
                    "Continuing with empty memory."
                )
                return

        cl.context.session.thread_id = thread["id"]
        memory = await restore_chat_history(thread)
        cl.user_session.set("memory", memory)
        from aria.web.supervisor import ensure_watching

        await ensure_watching(thread["id"], elements=thread.get("elements"))
    except Exception as e:
        logger.exception(f"Failed to restore chat history: {e}")


MIN_AUDIO_DURATION_S = 0.5

# Markdown → plain-text reductions for TTS narration. Kokoro reads every
# character literally, so ``**bold**`` would be spoken as "asterisk asterisk
# bold asterisk asterisk". Order matters: strip fenced code before inline,
# images before links, lists before emphasis.
_MD_REDUCTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"```.*?```", re.DOTALL), " "),  # fenced code blocks
    (re.compile(r"`([^`]*)`"), r"\1"),  # inline code
    (re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"\1"),  # images -> alt text
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),  # links -> text
    (re.compile(r"https?://\S+"), " "),  # bare URLs
    (
        re.compile(
            r"(?:~/|/)\S+\."
            r"(?:md|txt|rst|py|js|ts|json|csv|html?|css|ya?ml|toml|xml|log|sh|tex"
            r"|sql|go|rs|c|cpp|java|rb"
            r"|png|jpe?g|gif|webp|svg|pdf|wav|mp3|mp4)"
            r"(?:\b|(?=\s))"
        ),
        " ",
    ),  # file paths
    (re.compile(r"^#{1,6}\s+", re.MULTILINE), ""),  # headers
    (re.compile(r"^\s{0,3}>\s?", re.MULTILINE), ""),  # blockquotes
    (re.compile(r"^\s{0,3}[-*+]\s+", re.MULTILINE), ""),  # bullet lists
    (re.compile(r"^\s{0,3}\d+\.\s+", re.MULTILINE), ""),  # numbered lists
    (re.compile(r"^\s{0,3}[-*_]{3,}\s*$", re.MULTILINE), ""),  # horizontal rules
    (re.compile(r"\*{1,3}([^*]+)\*{1,3}"), r"\1"),  # *emphasis*
    (re.compile(r"_{1,3}([^_]+)_{1,3}"), r"\1"),  # _emphasis_
    (re.compile(r"\|"), " "),  # table pipes
]


def _strip_markdown_for_tts(text: str) -> str:
    """Reduce markdown to plain text so TTS narrates words, not syntax.

    Args:
        text: Markdown answer text from the agent.

    Returns:
        Whitespace-collapsed plain text with markdown syntax removed.
    """
    for pattern, repl in _MD_REDUCTIONS:
        text = pattern.sub(repl, text)
    return re.sub(r"\s+", " ", text).strip()


async def _speech_to_text(wav_bytes: bytes) -> str:
    """Transcribe WAV bytes via the whisper.cpp server.

    Returns an empty string for non-speech segments (silence, noise, music)
    that whisper.cpp reports as a bracketed tag instead of real text.
    """
    whisper = get_whisper_manager()
    if whisper is None:
        return ""
    transcription = await whisper.transcribe(wav_bytes)
    return strip_non_speech_tags(transcription)


async def _text_to_speech(text: str) -> bytes:
    """Synthesize text to WAV bytes via the kokoro TTS server."""
    kokoro = get_kokoro_manager()
    if kokoro is None:
        return b""
    return await kokoro.synthesize(text)


async def on_audio_start_handler() -> bool:
    """Return True to accept the microphone stream (start of a turn).

    Returns False (rejecting the stream) when voice is disabled via
    ``ARIA_VOICE_ENABLED=false``, or when the server is not bound to a
    loopback address — ``getUserMedia`` requires a secure context, so
    audio cannot work over a LAN HTTP origin. The Chainlit config flag
    hides the mic button in that case; the loopback guard is a safety net.
    """
    if not Voice.enabled:
        logger.info("Audio stream rejected: voice disabled (ARIA_VOICE_ENABLED=false)")
        return False

    from aria.config.service import Server, is_loopback_host

    if not is_loopback_host(Server.host):
        logger.info(
            f"Audio stream rejected: {Server.host} is not a loopback host "
            "(voice requires a secure context)"
        )
        return False
    logger.info("Audio stream started")
    cl.user_session.set("audio_chunks", [])
    cl.user_session.set("is_speaking", False)
    cl.user_session.set("silent_ms", 0.0)
    cl.user_session.set("last_elapsed_time", None)
    cl.user_session.set("voice_processing", False)
    return True


async def on_audio_chunk_handler(chunk: cl.InputAudioChunk) -> None:
    """Accumulate PCM chunks; on silence timeout, run process_audio.

    Each chunk is dispatched by Chainlit as its own ``asyncio.create_task``
    (fire-and-forget), so chunk handlers for the *same* audio stream can
    overlap with an in-flight ``process_audio()`` call. While a turn is
    being processed (STT -> agent -> TTS), incoming chunks are dropped
    rather than appended: appending into a list that ``process_audio()``
    is concurrently swapping out would either lose audio (appended to the
    stale list reference) or bleed the tail of the assistant's own
    playback into the next turn. The ``voice_processing`` guard also
    prevents a second concurrent ``process_audio()`` call from being
    triggered while one is already running.
    """
    if cl.user_session.get("voice_processing"):
        return

    chunks = cl.user_session.get("audio_chunks")
    if chunks is not None:
        chunks.append(np.frombuffer(chunk.data, dtype=np.int16))

    if chunk.isStart:
        cl.user_session.set("last_elapsed_time", chunk.elapsedTime)
        cl.user_session.set("is_speaking", True)
        return

    last_elapsed = cl.user_session.get("last_elapsed_time")
    if last_elapsed is None:
        last_elapsed = chunk.elapsedTime
    time_diff_ms = chunk.elapsedTime - last_elapsed
    cl.user_session.set("last_elapsed_time", chunk.elapsedTime)

    rms = audioop.rms(chunk.data, 2)
    if rms < Voice.rms_threshold:
        silent_ms = float(cl.user_session.get("silent_ms", 0.0) or 0.0)
        silent_ms += time_diff_ms
        cl.user_session.set("silent_ms", silent_ms)
        if silent_ms >= Voice.silence_threshold_ms and cl.user_session.get(
            "is_speaking"
        ):
            cl.user_session.set("is_speaking", False)
            cl.user_session.set("voice_processing", True)
            try:
                await process_audio()
            finally:
                cl.user_session.set("voice_processing", False)
    else:
        cl.user_session.set("silent_ms", 0.0)
        if not cl.user_session.get("is_speaking"):
            cl.user_session.set("is_speaking", True)


async def on_audio_end_handler() -> None:
    """Flush any remaining audio when the mic stream ends."""
    logger.info("Audio stream ended")
    if cl.user_session.get("voice_processing"):
        return
    chunks = cl.user_session.get("audio_chunks") or []
    if chunks and cl.user_session.get("is_speaking"):
        cl.user_session.set("is_speaking", False)
        cl.user_session.set("voice_processing", True)
        try:
            await process_audio()
        finally:
            cl.user_session.set("voice_processing", False)


async def process_audio() -> None:
    """STT -> existing message pipeline -> TTS -> auto-play audio.

    Callers must hold the ``voice_processing`` guard for the duration of
    this call so no concurrently-scheduled chunk handler can hold a stale
    reference to the ``audio_chunks`` list across the swap below.
    """
    chunks = list(cl.user_session.get("audio_chunks", []) or [])
    cl.user_session.set("audio_chunks", [])
    if not chunks:
        return
    pcm = np.concatenate(chunks).tobytes()

    sample_rate = Voice.audio_sample_rate
    duration_s = len(pcm) / (2 * sample_rate)
    if duration_s < MIN_AUDIO_DURATION_S:
        logger.debug(f"Audio too short ({duration_s:.2f}s), skipping STT")
        return

    wav = io.BytesIO()
    with wave.open(wav, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(pcm)
    wav_bytes = wav.getvalue()

    transcription = await _speech_to_text(wav_bytes)
    if not transcription.strip():
        logger.debug("STT returned empty transcription, skipping")
        return

    logger.info(f"Transcription: {transcription}")

    echo = cl.Message(
        content=transcription,
        author="You",
        type="user_message",
        metadata={"voice": True},
    )
    await echo.send()

    from aria.web.message_pipeline import on_message_handler

    output = await on_message_handler(echo)
    answer = getattr(output, "answer_text", "") if output else ""
    if not answer.strip():
        logger.warning("No answer text from message pipeline")
        return

    audio_bytes = await _text_to_speech(_strip_markdown_for_tts(answer))
    if audio_bytes and output is not None:
        existing = list(output.elements or [])
        existing.append(
            cl.Audio(  # type: ignore[arg-type]
                content=audio_bytes,
                auto_play=True,
                mime="audio/wav",
            )
        )
        output.elements = existing  # type: ignore[attr-defined]
        await output.update()
