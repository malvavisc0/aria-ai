"""Tests for the voice audio hooks in [`aria.web.hooks`](../hooks.py)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aria.web import hooks as hooks_mod

pytestmark = pytest.mark.voice


class _UserSession:
    """In-memory fake for cl.user_session.get/set."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value


class _Message:
    """Records construction and send() calls for cl.Message."""

    instances: list[dict[str, Any]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.kwargs = kwargs
        _Message.instances.append(kwargs)

    async def send(self) -> None:
        return None


@pytest.fixture
def patch_cl(monkeypatch: pytest.MonkeyPatch) -> None:
    _Message.instances = []
    monkeypatch.setattr(hooks_mod.cl, "Message", _Message)
    monkeypatch.setattr(hooks_mod.cl, "Audio", lambda **kw: kw)


@pytest.fixture
def user_session(monkeypatch: pytest.MonkeyPatch) -> _UserSession:
    session = _UserSession()
    monkeypatch.setattr(hooks_mod.cl, "user_session", session)
    return session


def _chunk(
    elapsed_ms: float,
    is_start: bool = False,
    loud: bool = False,
    bytes_per_chunk: int = 3200,
) -> Any:
    """Build an InputAudioChunk with a given elapsedTime."""
    data = b"\xff\x7f" * (bytes_per_chunk // 2) if loud else b"\x00" * bytes_per_chunk
    return hooks_mod.cl.InputAudioChunk(
        isStart=is_start,
        mimeType="audio/pcm",
        elapsedTime=elapsed_ms,
        data=data,
    )


# ---------------------------------------------------------------------------
# on_audio_start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_audio_start_initialises_session(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aria.config.service import Server

    monkeypatch.setattr(Server, "host", "localhost")
    assert await hooks_mod.on_audio_start_handler() is True
    assert user_session.get("audio_chunks") == []
    assert user_session.get("is_speaking") is False
    assert user_session.get("silent_ms") == 0.0


@pytest.mark.asyncio
async def test_on_audio_start_rejects_non_loopback(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-loopback bind must reject the stream (no secure context)."""
    from aria.config.service import Server

    monkeypatch.setattr(Server, "host", "192.168.1.220")
    assert await hooks_mod.on_audio_start_handler() is False
    assert user_session.get("audio_chunks") is None


# ---------------------------------------------------------------------------
# on_audio_chunk — silence detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chunk_silence_timeout_triggers_process_audio(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silent chunks totalling > 1300 ms after speech trigger process_audio."""
    await hooks_mod.on_audio_start_handler()
    process = AsyncMock()
    monkeypatch.setattr(hooks_mod, "process_audio", process)

    await hooks_mod.on_audio_chunk_handler(_chunk(0.0, is_start=True))
    for i in range(14):
        await hooks_mod.on_audio_chunk_handler(_chunk(float(i + 1) * 100.0))

    process.assert_awaited_once()
    assert user_session.get("is_speaking") is False


@pytest.mark.asyncio
async def test_multiturn_speech_resume_retriggers_process_audio(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After process_audio, resumed speech re-arms so a subsequent silence
    fires process_audio again."""
    await hooks_mod.on_audio_start_handler()
    process = AsyncMock()
    monkeypatch.setattr(hooks_mod, "process_audio", process)

    # Turn 1: start + silence -> process_audio fires once.
    await hooks_mod.on_audio_chunk_handler(_chunk(0.0, is_start=True))
    for i in range(14):
        await hooks_mod.on_audio_chunk_handler(_chunk(float(i + 1) * 100.0))
    assert process.await_count == 1

    # User speaks again (loud chunks) -> is_speaking re-arms.
    for i in range(5):
        await hooks_mod.on_audio_chunk_handler(_chunk(2000.0 + i * 100.0, loud=True))
    assert user_session.get("is_speaking") is True

    # Turn 2: silence -> process_audio fires a second time.
    for i in range(14):
        await hooks_mod.on_audio_chunk_handler(_chunk(3000.0 + i * 100.0))
    assert process.await_count == 2


# ---------------------------------------------------------------------------
# on_audio_end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_audio_end_flushes_remaining(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pending chunks with is_speaking=True are flushed through process_audio."""
    await hooks_mod.on_audio_start_handler()
    process = AsyncMock()
    monkeypatch.setattr(hooks_mod, "process_audio", process)
    user_session.set("is_speaking", True)
    user_session.set("audio_chunks", [hooks_mod.np.zeros(10, dtype=hooks_mod.np.int16)])

    await hooks_mod.on_audio_end_handler()
    process.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_audio_end_noop_when_no_chunks(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await hooks_mod.on_audio_start_handler()
    process = AsyncMock()
    monkeypatch.setattr(hooks_mod, "process_audio", process)

    await hooks_mod.on_audio_end_handler()
    process.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_audio_end_noop_when_not_speaking(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await hooks_mod.on_audio_start_handler()
    process = AsyncMock()
    monkeypatch.setattr(hooks_mod, "process_audio", process)
    user_session.set("audio_chunks", [hooks_mod.np.zeros(10, dtype=hooks_mod.np.int16)])
    user_session.set("is_speaking", False)

    await hooks_mod.on_audio_end_handler()
    process.assert_not_awaited()


# ---------------------------------------------------------------------------
# process_audio
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_audio_full_flow(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch, patch_cl: None
) -> None:
    await hooks_mod.on_audio_start_handler()
    for _ in range(10):
        await hooks_mod.on_audio_chunk_handler(_chunk(100.0))

    monkeypatch.setattr(
        hooks_mod, "_speech_to_text", AsyncMock(return_value="hello there")
    )
    monkeypatch.setattr(
        hooks_mod, "_text_to_speech", AsyncMock(return_value=b"RIFFaudio")
    )

    output = MagicMock()
    output.update = AsyncMock()
    output.answer_text = "And hello to you"
    monkeypatch.setattr(
        "aria.web.message_pipeline.on_message_handler", AsyncMock(return_value=output)
    )

    await hooks_mod.process_audio()

    user_msgs = [m for m in _Message.instances if m.get("type") == "user_message"]
    assert user_msgs[0]["content"] == "hello there"
    assert not user_msgs[0].get("elements")
    assert isinstance(output.elements, list)
    assert output.elements[0].get("auto_play") is True
    output.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_audio_skips_tts_when_no_output(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch, patch_cl: None
) -> None:
    await hooks_mod.on_audio_start_handler()
    for _ in range(10):
        await hooks_mod.on_audio_chunk_handler(_chunk(100.0))

    monkeypatch.setattr(
        hooks_mod, "_speech_to_text", AsyncMock(return_value="hello there")
    )
    tts = AsyncMock(return_value=b"RIFFaudio")
    monkeypatch.setattr(hooks_mod, "_text_to_speech", tts)

    monkeypatch.setattr(
        "aria.web.message_pipeline.on_message_handler", AsyncMock(return_value=None)
    )

    await hooks_mod.process_audio()

    tts.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_audio_skips_tts_when_empty_answer(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch, patch_cl: None
) -> None:
    """Empty answer text from the pipeline skips TTS entirely."""
    await hooks_mod.on_audio_start_handler()
    for _ in range(10):
        await hooks_mod.on_audio_chunk_handler(_chunk(100.0))

    monkeypatch.setattr(hooks_mod, "_speech_to_text", AsyncMock(return_value="hi"))
    tts = AsyncMock(return_value=b"RIFFaudio")
    monkeypatch.setattr(hooks_mod, "_text_to_speech", tts)

    output = MagicMock()
    output.update = AsyncMock()
    output.answer_text = "   "
    monkeypatch.setattr(
        "aria.web.message_pipeline.on_message_handler", AsyncMock(return_value=output)
    )

    await hooks_mod.process_audio()

    tts.assert_not_awaited()
    output.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_audio_attaches_audio_to_streamed_output(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch, patch_cl: None
) -> None:
    """TTS audio must attach to the streamed assistant message, not a new one."""
    await hooks_mod.on_audio_start_handler()
    for _ in range(10):
        await hooks_mod.on_audio_chunk_handler(_chunk(100.0))

    monkeypatch.setattr(hooks_mod, "_speech_to_text", AsyncMock(return_value="hi"))
    monkeypatch.setattr(
        hooks_mod, "_text_to_speech", AsyncMock(return_value=b"RIFFaudio")
    )

    output = MagicMock()
    output.update = AsyncMock()
    output.answer_text = "Hello to you"
    monkeypatch.setattr(
        "aria.web.message_pipeline.on_message_handler", AsyncMock(return_value=output)
    )

    await hooks_mod.process_audio()

    assert isinstance(output.elements, list)
    assert output.elements[0].get("auto_play") is True
    output.update.assert_awaited_once()
    assistant_msgs = [
        m
        for m in _Message.instances
        if m.get("content") == "Hello to you" and m.get("type") != "user_message"
    ]
    assert assistant_msgs == []


@pytest.mark.asyncio
async def test_process_audio_min_duration_skips_stt(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch, patch_cl: None
) -> None:
    """Sub-MIN_AUDIO_DURATION_S audio must skip STT entirely."""
    await hooks_mod.on_audio_start_handler()
    user_session.set(
        "audio_chunks", [hooks_mod.np.zeros(800, dtype=hooks_mod.np.int16)]
    )

    stt = AsyncMock(return_value="should not be called")
    monkeypatch.setattr(hooks_mod, "_speech_to_text", stt)

    await hooks_mod.process_audio()
    stt.assert_not_awaited()


# ---------------------------------------------------------------------------
# _strip_markdown_for_tts
# ---------------------------------------------------------------------------


def test_strip_markdown_removes_emphasis() -> None:
    assert hooks_mod._strip_markdown_for_tts("**bold** and _italic_") == (
        "bold and italic"
    )


def test_strip_markdown_removes_headers_and_lists() -> None:
    src = "# Title\n- item one\n- item two\n1. first"
    assert hooks_mod._strip_markdown_for_tts(src) == "Title item one item two first"


def test_strip_markdown_unwraps_links_and_code() -> None:
    src = "See [docs](https://x.io) and `code` here"
    assert hooks_mod._strip_markdown_for_tts(src) == "See docs and code here"


def test_strip_markdown_drops_fenced_code() -> None:
    src = "Before\n```python\nprint(1)\n```\nAfter"
    assert hooks_mod._strip_markdown_for_tts(src) == "Before After"


def test_strip_markdown_collapses_whitespace() -> None:
    assert hooks_mod._strip_markdown_for_tts("a\n\n  b   c") == "a b c"


@pytest.mark.asyncio
async def test_process_audio_strips_markdown_before_tts(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch, patch_cl: None
) -> None:
    """TTS must receive markdown-stripped text, not raw syntax."""
    await hooks_mod.on_audio_start_handler()
    for _ in range(10):
        await hooks_mod.on_audio_chunk_handler(_chunk(100.0))

    monkeypatch.setattr(hooks_mod, "_speech_to_text", AsyncMock(return_value="hi"))
    tts = AsyncMock(return_value=b"RIFFaudio")
    monkeypatch.setattr(hooks_mod, "_text_to_speech", tts)

    output = MagicMock()
    output.update = AsyncMock()
    output.answer_text = "**Hello** there"
    monkeypatch.setattr(
        "aria.web.message_pipeline.on_message_handler", AsyncMock(return_value=output)
    )

    await hooks_mod.process_audio()
    tts.assert_awaited_once_with("Hello there")
