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
    user_session: _UserSession,
) -> None:
    assert await hooks_mod.on_audio_start_handler() is True
    assert user_session.get("audio_chunks") == []
    assert user_session.get("is_speaking") is False
    assert user_session.get("silent_ms") == 0.0
    assert user_session.get("voice_processing") is False
    assert user_session.get("voice_task") is None


# ---------------------------------------------------------------------------
# on_audio_chunk — silence detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chunk_silence_timeout_triggers_process_audio(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silent chunks totalling > 1300 ms after speech arms process_audio."""
    await hooks_mod.on_audio_start_handler()
    monkeypatch.setattr(hooks_mod, "process_audio", AsyncMock())

    # isStart chunk arms is_speaking.
    await hooks_mod.on_audio_chunk_handler(_chunk(0.0, is_start=True))
    # 14 silent chunks x 100 ms = 1400 ms > 1300 ms threshold.
    for i in range(14):
        await hooks_mod.on_audio_chunk_handler(_chunk(float(i + 1) * 100.0))

    # process_audio was spawned as a task — await it.
    task = user_session.get("voice_task")
    assert task is not None
    await task
    assert user_session.get("is_speaking") is False


@pytest.mark.asyncio
async def test_chunk_skipped_while_processing(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await hooks_mod.on_audio_start_handler()
    user_session.set("voice_processing", True)
    process = AsyncMock()
    monkeypatch.setattr(hooks_mod, "process_audio", process)

    await hooks_mod.on_audio_chunk_handler(_chunk(100.0))

    process.assert_not_awaited()
    assert user_session.get("audio_chunks") == []


@pytest.mark.asyncio
async def test_multiturn_speech_resume_retriggers_process_audio(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After process_audio flips is_speaking=False, resumed speech must
    re-arm is_speaking so a subsequent silence fires process_audio again."""
    await hooks_mod.on_audio_start_handler()
    monkeypatch.setattr(hooks_mod, "process_audio", AsyncMock())

    # Turn 1: start + silence -> process_audio fires once.
    await hooks_mod.on_audio_chunk_handler(_chunk(0.0, is_start=True))
    for i in range(14):
        await hooks_mod.on_audio_chunk_handler(_chunk(float(i + 1) * 100.0))
    task1 = user_session.get("voice_task")
    assert task1 is not None
    await task1
    assert user_session.get("is_speaking") is False
    assert user_session.get("voice_processing") is False

    # User speaks again (loud chunks) -> is_speaking must re-arm.
    for i in range(5):
        await hooks_mod.on_audio_chunk_handler(_chunk(2000.0 + i * 100.0, loud=True))
    assert user_session.get("is_speaking") is True

    # Turn 2: silence -> process_audio fires a second time.
    for i in range(14):
        await hooks_mod.on_audio_chunk_handler(_chunk(3000.0 + i * 100.0))
    task2 = user_session.get("voice_task")
    assert task2 is not None
    await task2


# ---------------------------------------------------------------------------
# on_audio_end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_audio_end_noop_when_processing(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a silence-timeout turn is in flight, on_audio_end must not start
    a second one."""
    await hooks_mod.on_audio_start_handler()
    user_session.set("voice_processing", True)
    process = AsyncMock()
    monkeypatch.setattr(hooks_mod, "process_audio", process)
    user_session.set("audio_chunks", [b"fake"])

    await hooks_mod.on_audio_end_handler()
    process.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_audio_end_flushes_remaining(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pending chunks with no in-flight turn are flushed through process_audio."""
    await hooks_mod.on_audio_start_handler()
    process = AsyncMock()
    monkeypatch.setattr(hooks_mod, "process_audio", process)
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
    output.content = "And hello to you"
    monkeypatch.setattr(
        "aria.web.message_pipeline.on_message_handler", AsyncMock(return_value=output)
    )

    await hooks_mod.process_audio()

    # Transcription user message + assistant message with auto-play audio.
    user_msgs = [m for m in _Message.instances if m.get("type") == "user_message"]
    assert user_msgs[0]["content"] == "hello there"
    audio_msgs = [
        m
        for m in _Message.instances
        if m.get("elements") and m.get("type") != "user_message"
    ]
    assert audio_msgs[0]["elements"][0]["auto_play"] is True


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

    # Error path returns None -> no answer -> no TTS, no assistant message.
    monkeypatch.setattr(
        "aria.web.message_pipeline.on_message_handler", AsyncMock(return_value=None)
    )

    await hooks_mod.process_audio()

    tts.assert_not_awaited()
    # No message carries an auto-play audio element.
    auto_play_msgs = [
        m
        for m in _Message.instances
        if m.get("elements")
        and any(isinstance(e, dict) and e.get("auto_play") for e in m["elements"])
    ]
    assert auto_play_msgs == []


@pytest.mark.asyncio
async def test_process_audio_text_answer_sent_when_tts_fails(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch, patch_cl: None
) -> None:
    """When TTS returns empty bytes, the text answer must still be sent
    (TTS degrades to text-only, not a swallowed answer)."""
    await hooks_mod.on_audio_start_handler()
    for _ in range(10):
        await hooks_mod.on_audio_chunk_handler(_chunk(100.0))

    monkeypatch.setattr(hooks_mod, "_speech_to_text", AsyncMock(return_value="hello"))
    monkeypatch.setattr(hooks_mod, "_text_to_speech", AsyncMock(return_value=b""))

    output = MagicMock()
    output.content = "Hello to you"
    monkeypatch.setattr(
        "aria.web.message_pipeline.on_message_handler", AsyncMock(return_value=output)
    )

    await hooks_mod.process_audio()

    # Text answer was sent (no auto-play audio element).
    answer_msgs = [m for m in _Message.instances if m.get("content") == "Hello to you"]
    assert len(answer_msgs) == 1
    assert not answer_msgs[0].get("elements")


@pytest.mark.asyncio
async def test_process_audio_min_duration_skips_stt(
    user_session: _UserSession, monkeypatch: pytest.MonkeyPatch, patch_cl: None
) -> None:
    """Sub-MIN_AUDIO_DURATION_S audio must skip STT entirely."""
    await hooks_mod.on_audio_start_handler()
    # 1600 bytes = 800 samples = 800/16000 = 0.05s < 0.5s threshold.
    user_session.set(
        "audio_chunks", [hooks_mod.np.zeros(800, dtype=hooks_mod.np.int16)]
    )

    stt = AsyncMock(return_value="should not be called")
    monkeypatch.setattr(hooks_mod, "_speech_to_text", stt)

    await hooks_mod.process_audio()
    stt.assert_not_awaited()
