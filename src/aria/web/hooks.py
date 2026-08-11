"""Chainlit webhook handlers for the Aria web UI.

This module provides callback handlers for Chainlit events including:
- Authentication (login/logout)
- Chat session lifecycle (start, resume, end)
- Data layer initialization

These handlers are invoked by Chainlit at various points in the app lifecycle.
"""

from __future__ import annotations

import asyncio
import audioop  # stdlib on 3.12; audioop-lts covers 3.13+
import io
import json
import wave
from typing import Any

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
from aria.server.voice import get_kokoro_manager, get_whisper_manager
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

        memory = await restore_chat_history(thread)
        cl.user_session.set("memory", memory)
    except Exception as e:
        logger.exception(f"Failed to restore chat history: {e}")


async def on_mcp_connect_handler(connection: Any, client_session: Any) -> None:
    """Register a connected MCP server's ClientSession on the user session."""
    sessions: dict = cl.user_session.get("_mcp_sessions") or {}
    sessions[connection.name] = client_session
    cl.user_session.set("_mcp_sessions", sessions)
    logger.info(f"MCP server connected: {connection.name}")


async def on_mcp_disconnect_handler(name: str, client_session: Any) -> None:
    """Drop a disconnected MCP server from the user session."""
    sessions: dict = cl.user_session.get("_mcp_sessions") or {}
    sessions.pop(name, None)
    cl.user_session.set("_mcp_sessions", sessions)
    logger.info(f"MCP server disconnected: {name}")


MIN_AUDIO_DURATION_S = 0.5


@cl.step(type="tool")
async def _speech_to_text(wav_bytes: bytes) -> str:
    """Transcribe WAV bytes via the whisper.cpp server."""
    whisper = get_whisper_manager()
    if whisper is None:
        return ""
    return await whisper.transcribe(wav_bytes)


@cl.step(type="tool")
async def _text_to_speech(text: str) -> bytes:
    """Synthesize text to WAV bytes via the kokoro TTS server."""
    kokoro = get_kokoro_manager()
    if kokoro is None:
        return b""
    return await kokoro.synthesize(text)


async def on_audio_start_handler() -> bool:
    """Return True to accept the microphone stream (start of a turn)."""
    cl.user_session.set("audio_chunks", [])
    cl.user_session.set("is_speaking", False)
    cl.user_session.set("silent_ms", 0.0)
    cl.user_session.set("last_elapsed_time", None)
    cl.user_session.set("voice_processing", False)
    cl.user_session.set("voice_task", None)
    return True


async def on_audio_chunk_handler(chunk: cl.InputAudioChunk) -> None:
    """Accumulate PCM chunks; on silence timeout, spawn process_audio."""
    if cl.user_session.get("voice_processing"):
        return
    chunks = list(cl.user_session.get("audio_chunks") or [])
    chunks.append(np.frombuffer(chunk.data, dtype=np.int16))
    cl.user_session.set("audio_chunks", chunks)

    if chunk.isStart:
        cl.user_session.set("is_speaking", True)
        cl.user_session.set("last_elapsed_time", chunk.elapsedTime)
        return

    # Silence timing via chunk timestamps (robust to arrival jitter).
    last_elapsed = cl.user_session.get("last_elapsed_time")
    if last_elapsed is None:
        last_elapsed = chunk.elapsedTime
    time_diff_ms = chunk.elapsedTime - last_elapsed
    cl.user_session.set("last_elapsed_time", chunk.elapsedTime)

    rms = audioop.rms(chunk.data, 2)  # 16-bit = 2 bytes/sample
    if rms < Voice.rms_threshold:
        silent_ms = float(cl.user_session.get("silent_ms", 0.0) or 0.0)
        silent_ms += time_diff_ms
        cl.user_session.set("silent_ms", silent_ms)
        if silent_ms >= Voice.silence_threshold_ms and cl.user_session.get(
            "is_speaking"
        ):
            cl.user_session.set("is_speaking", False)
            cl.user_session.set("voice_processing", True)
            task = asyncio.create_task(_run_process_audio())
            cl.user_session.set("voice_task", task)
    else:
        cl.user_session.set("silent_ms", 0.0)
        if not cl.user_session.get("is_speaking"):
            cl.user_session.set("is_speaking", True)


async def on_audio_end_handler() -> None:
    """Flush any remaining audio when the mic stream ends.

    If a silence-timeout turn is already in flight, it completes on its own.
    Otherwise, any buffered chunks are flushed through process_audio. This
    hook also ensures ``init_thread("audio")`` has run before the first
    message is constructed (see design report §6.4).
    """
    if cl.user_session.get("voice_processing"):
        return
    chunks = cl.user_session.get("audio_chunks") or []
    if not chunks:
        return
    cl.user_session.set("voice_processing", True)
    await _run_process_audio()


async def _run_process_audio() -> None:
    """Run process_audio and clear the processing flag + task reference."""
    try:
        await process_audio()
    except Exception as e:
        logger.exception(f"process_audio failed: {e}")
    finally:
        cl.user_session.set("voice_processing", False)
        cl.user_session.set("voice_task", None)


async def process_audio() -> None:
    """STT -> existing message pipeline -> TTS -> auto-play audio."""
    chunks = list(cl.user_session.get("audio_chunks", []) or [])
    cl.user_session.set("audio_chunks", [])
    if not chunks:
        return
    pcm = np.concatenate(chunks).tobytes()

    sample_rate = Voice.audio_sample_rate
    duration_s = len(pcm) / (2 * sample_rate)  # 2 bytes/sample
    if duration_s < MIN_AUDIO_DURATION_S:
        logger.debug(f"Audio too short ({duration_s:.2f}s), skipping STT")
        return

    # Wrap raw PCM in a WAV (mono, 16-bit — sample rate from config).
    wav = io.BytesIO()
    with wave.open(wav, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(pcm)
    wav_bytes = wav.getvalue()

    transcription = await _speech_to_text(wav_bytes)
    if not transcription.strip():
        return

    # Show the transcription as the user's message (echo the captured audio).
    input_audio = cl.Audio(content=wav_bytes, name="input.wav", mime="audio/wav")
    await cl.Message(
        content=transcription,
        author="You",
        type="user_message",
        elements=[input_audio],
    ).send()

    # Reuse the full text pipeline (memory, tools, streaming, error handling).
    from aria.web.message_pipeline import on_message_handler

    output = await on_message_handler(cl.Message(content=transcription))
    answer = getattr(output, "answer_text", "") if output else ""
    if not answer.strip():
        return

    # Always send the text answer; attach auto-play audio when TTS succeeds.
    audio_bytes = await _text_to_speech(answer)
    if audio_bytes:
        await cl.Message(
            content=answer,
            elements=[
                cl.Audio(
                    content=audio_bytes,
                    auto_play=True,
                    name="answer.wav",
                    mime="audio/wav",
                )
            ],
        ).send()
    else:
        await cl.Message(content=answer).send()
