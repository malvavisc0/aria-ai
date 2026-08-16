"""Tests for aria.tools.voice.functions.transcribe (fake whisper manager)."""

import json
from pathlib import Path
from typing import Any

import pytest

import aria.tools.voice.functions as voice_functions
from aria.tools.voice.functions import transcribe

_WAV = b"RIFF" + b"\x00" * 16


class _FakeWhisper:
    def __init__(self, text: str = "Hello world."):
        self._text = text
        self.last_bytes: bytes = b""
        self.last_timeout: float | None = None

    async def transcribe(self, wav_bytes: bytes, timeout: float | None = None) -> str:
        self.last_bytes = wav_bytes
        self.last_timeout = timeout
        return self._text


@pytest.fixture()
def make_manager(monkeypatch: pytest.MonkeyPatch):
    def _make(text: str = "Hello world.") -> _FakeWhisper:
        manager = _FakeWhisper(text)
        monkeypatch.setattr(voice_functions, "get_whisper_manager", lambda: manager)
        return manager

    return _make


@pytest.fixture()
def wav_file(tmp_path: Path) -> Path:
    fp = tmp_path / "sample.wav"
    fp.write_bytes(_WAV)
    return fp


def _parse(result: str) -> dict[str, Any]:
    return json.loads(result)["data"]


class TestUnavailable:
    @pytest.mark.asyncio
    async def test_manager_none_returns_stt_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, wav_file: Path
    ):
        monkeypatch.setattr(voice_functions, "get_whisper_manager", lambda: None)
        result = await transcribe("test", file=str(wav_file))
        data = _parse(result)
        assert data["error"]["code"] == "stt_unavailable"


class TestPathValidation:
    @pytest.mark.asyncio
    async def test_relative_path_rejected(self, make_manager: Any):
        make_manager()
        data = _parse(await transcribe("test", file="relative.wav"))
        assert data["error"]["code"] == "path_error"

    @pytest.mark.asyncio
    async def test_missing_file_rejected(self, make_manager: Any, tmp_path: Path):
        make_manager()
        data = _parse(await transcribe("test", file=str(tmp_path / "nope.wav")))
        assert data["error"]["code"] == "path_error"

    @pytest.mark.asyncio
    async def test_directory_rejected(self, make_manager: Any, tmp_path: Path):
        make_manager()
        data = _parse(await transcribe("test", file=str(tmp_path)))
        assert data["error"]["code"] == "path_error"


class TestWavPath:
    @pytest.mark.asyncio
    async def test_happy_path_inlines_text(self, make_manager: Any, wav_file: Path):
        manager = make_manager()
        data = _parse(await transcribe("test", file=str(wav_file)))
        assert data["text"] == "Hello world."
        assert data["chars"] == len("Hello world.")
        assert manager.last_bytes == _WAV
        assert manager.last_timeout == 300.0

    @pytest.mark.asyncio
    async def test_blank_audio_is_no_speech(self, make_manager: Any, wav_file: Path):
        make_manager(" [BLANK_AUDIO] ")
        data = _parse(await transcribe("test", file=str(wav_file)))
        assert data["text"] == ""
        assert "note" in data

    @pytest.mark.asyncio
    async def test_no_speech_is_success_not_error(
        self, make_manager: Any, wav_file: Path
    ):
        make_manager(" [SILENCE] ")
        result = await transcribe("test", file=str(wav_file))
        assert json.loads(result)["status"] == "success"


class TestNonWav:
    @pytest.mark.asyncio
    async def test_ffmpeg_missing(
        self,
        make_manager: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        make_manager()
        mp3 = tmp_path / "sample.mp3"
        mp3.write_bytes(b"\x00")
        monkeypatch.setattr(voice_functions.shutil, "which", lambda name: None)
        data = _parse(await transcribe("test", file=str(mp3)))
        assert data["error"]["code"] == "ffmpeg_missing"


class TestPersistence:
    @pytest.mark.asyncio
    async def test_at_threshold_stays_inline(self, make_manager: Any, wav_file: Path):
        make_manager("a" * 2000)
        data = _parse(await transcribe("test", file=str(wav_file)))
        assert "text" in data
        assert "file_path" not in data

    @pytest.mark.asyncio
    async def test_long_transcript_persisted(
        self,
        make_manager: Any,
        wav_file: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from aria.config.folders import Workspace

        monkeypatch.setattr(Workspace, "path", tmp_path)
        text = "w" * 3500  # above _PERSIST_THRESHOLD
        make_manager(text)
        data = _parse(await transcribe("test", file=str(wav_file)))
        assert data["chars"] == len(text)
        dest = Path(data["file_path"])
        assert dest.parent == tmp_path / "transcripts"
        assert dest.suffix == ".txt"
        assert dest.read_text(encoding="utf-8") == text
        assert "read_file" in data["note"]
