"""Chainlit web UI entrypoint.

This module intentionally remains thin: it registers Chainlit decorators and
forwards all logic to focused modules under ``aria.web``.
"""

from __future__ import annotations

import chainlit as cl
from chainlit.types import ThreadDict

from aria.web.hooks import (
    auth_callback_handler,
    get_data_layer_handler,
    on_audio_chunk_handler,
    on_audio_end_handler,
    on_audio_start_handler,
    on_chat_end_handler,
    on_chat_resume_handler,
    on_chat_start_handler,
)
from aria.web.lifecycle import on_app_shutdown_handler, on_app_startup_handler
from aria.web.message_pipeline import on_message_handler
from aria.web.starters import set_starters as _set_starters


@cl.on_app_startup
async def on_app_startup() -> None:
    await on_app_startup_handler()


@cl.on_app_shutdown
async def on_app_shutdown() -> None:
    await on_app_shutdown_handler()


@cl.data_layer
def get_data_layer():
    return get_data_layer_handler()


@cl.password_auth_callback
async def auth_callback(username: str, password: str) -> cl.User | None:
    return await auth_callback_handler(username, password)


@cl.on_chat_start
async def on_chat_start() -> None:
    await on_chat_start_handler()


@cl.on_chat_end
async def on_chat_end() -> None:
    await on_chat_end_handler()


@cl.on_chat_resume
async def on_chat_resume(thread: ThreadDict) -> None:
    await on_chat_resume_handler(thread)


@cl.on_message
async def on_message(message: cl.Message) -> None:
    await on_message_handler(message)


@cl.on_audio_start
async def on_audio_start() -> bool:
    return await on_audio_start_handler()


@cl.on_audio_chunk
async def on_audio_chunk(chunk: cl.InputAudioChunk) -> None:
    await on_audio_chunk_handler(chunk)


@cl.on_audio_end
async def on_audio_end() -> None:
    await on_audio_end_handler()


@cl.set_starters
async def set_starters(user: cl.User | None, language: str | None) -> list[cl.Starter]:
    return _set_starters(user, language)
