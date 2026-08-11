"""Tests for [`aria.server.voice`](../voice.py) managers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from aria.server import voice as voice_mod
from aria.server.voice import KokoroManager, WhisperCppManager

pytestmark = pytest.mark.voice


class _FakeAsyncClient:
    """Minimal double for httpx.AsyncClient used by transcribe()/synthesize()."""

    def __init__(
        self,
        payload: dict | None = None,
        status: int = 200,
        content: bytes = b"",
    ) -> None:
        self._payload = payload or {"text": "hello world"}
        self._status = status
        self._content = content
        self.post = AsyncMock(
            return_value=MagicMock(
                status_code=self._status,
                content=self._content,
                raise_for_status=MagicMock(),
                json=lambda: self._payload,
            )
        )
        self.aclose = AsyncMock()


class TestWhisperCppManager:
    def _manager(self) -> WhisperCppManager:
        return WhisperCppManager(
            binary_path=Path("/bin/whisper-server"),
            model_path=Path("/models/ggml-small.en.bin"),
            port=9091,
        )

    @pytest.mark.asyncio
    async def test_transcribe_posts_wav_to_inference(self) -> None:
        mgr = self._manager()
        fake = _FakeAsyncClient()
        mgr._client = fake  # type: ignore[assignment]
        result = await mgr.transcribe(b"\x00\x01")
        assert result == "hello world"
        args, kwargs = fake.post.call_args
        assert args[0] == "http://127.0.0.1:9091/inference"
        assert kwargs["files"]["file"][0] == "audio.wav"
        assert kwargs["data"] == {"response_format": "json"}

    @pytest.mark.asyncio
    async def test_transcribe_returns_empty_when_not_running(self) -> None:
        mgr = self._manager()
        assert await mgr.transcribe(b"\x00\x01") == ""

    @pytest.mark.asyncio
    async def test_transcribe_returns_empty_on_http_error(self) -> None:
        mgr = self._manager()
        fake = _FakeAsyncClient()
        fake.post.side_effect = httpx.ConnectError("boom")
        mgr._client = fake  # type: ignore[assignment]
        assert await mgr.transcribe(b"\x00\x01") == ""

    @pytest.mark.asyncio
    async def test_start_builds_correct_command(self) -> None:
        mgr = self._manager()
        with (
            patch.object(voice_mod.subprocess, "Popen") as mock_popen,
            patch.object(mgr, "_wait_for_health", AsyncMock(return_value=True)),
            patch.object(
                voice_mod.httpx, "AsyncClient", return_value=_FakeAsyncClient()
            ),
            patch.object(voice_mod.logger, "info"),
        ):
            assert await mgr.start() is True
        cmd = mock_popen.call_args[0][0]
        assert cmd == [
            "/bin/whisper-server",
            "--host",
            "127.0.0.1",
            "--port",
            "9091",
            "--model",
            "/models/ggml-small.en.bin",
        ]

    @pytest.mark.asyncio
    async def test_start_fails_and_cleans_up_when_unhealthy(self) -> None:
        mgr = self._manager()
        with (
            patch.object(voice_mod.subprocess, "Popen") as mock_popen,
            patch.object(mgr, "_wait_for_health", AsyncMock(return_value=False)),
            patch.object(mgr, "_cleanup_process") as mock_cleanup,
            patch.object(voice_mod.logger, "error"),
        ):
            assert await mgr.start() is False
        mock_popen.assert_called_once()
        mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_closes_client(self) -> None:
        mgr = self._manager()
        fake = _FakeAsyncClient()
        mgr._client = fake  # type: ignore[assignment]
        mgr._process = MagicMock()
        await mgr.stop()
        fake.aclose.assert_awaited_once()
        assert mgr._client is None

    def test_cleanup_process_terminates(self) -> None:
        mgr = self._manager()
        proc = MagicMock()
        mgr._process = proc
        mgr._cleanup_process()
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once()
        assert mgr._process is None


class TestKokoroManager:
    def _manager(self) -> KokoroManager:
        return KokoroManager(
            server_script=Path("/app/scripts/kokoro_server.py"),
            model_path=Path("/models/kokoro/kokoro-v1.0.onnx"),
            voices_path=Path("/models/kokoro/voices-v1.0.bin"),
            python_exe=Path("/kokoro/bin/python"),
            port=9092,
            voice="af_heart",
            lang="en-us",
        )

    @pytest.mark.asyncio
    async def test_start_fails_when_python_missing(self, tmp_path: Path) -> None:
        mgr = KokoroManager(
            server_script=Path("/app/scripts/kokoro_server.py"),
            model_path=Path("/models/kokoro/kokoro-v1.0.onnx"),
            voices_path=Path("/models/kokoro/voices-v1.0.bin"),
            python_exe=tmp_path / "nonexistent-python",
            port=9092,
            voice="af_heart",
            lang="en-us",
        )
        assert await mgr.start() is False

    @pytest.mark.asyncio
    async def test_synthesize_posts_json_to_synthesize(self) -> None:
        mgr = self._manager()
        fake = _FakeAsyncClient(content=b"RIFFwav")
        mgr._client = fake  # type: ignore[assignment]
        result = await mgr.synthesize("Hello")
        assert result == b"RIFFwav"
        args, kwargs = fake.post.call_args
        assert args[0] == "http://127.0.0.1:9092/synthesize"
        assert kwargs["json"] == {
            "text": "Hello",
            "voice": "af_heart",
            "lang": "en-us",
            "speed": 1.0,
        }

    @pytest.mark.asyncio
    async def test_synthesize_blank_text_returns_empty(self) -> None:
        mgr = self._manager()
        assert await mgr.synthesize("   ") == b""

    @pytest.mark.asyncio
    async def test_synthesize_returns_empty_when_not_running(self) -> None:
        mgr = self._manager()
        assert await mgr.synthesize("Hello") == b""

    @pytest.mark.asyncio
    async def test_synthesize_returns_empty_on_http_error(self) -> None:
        mgr = self._manager()
        fake = _FakeAsyncClient()
        fake.post.side_effect = httpx.ConnectError("boom")
        mgr._client = fake  # type: ignore[assignment]
        assert await mgr.synthesize("Hello") == b""

    @pytest.mark.asyncio
    async def test_start_builds_correct_command(self) -> None:
        mgr = self._manager()
        with (
            patch.object(voice_mod.subprocess, "Popen") as mock_popen,
            patch.object(mgr, "_wait_for_health", AsyncMock(return_value=True)),
            patch.object(
                voice_mod.httpx, "AsyncClient", return_value=_FakeAsyncClient()
            ),
            patch.object(voice_mod.logger, "info"),
            patch.object(Path, "exists", return_value=True),
        ):
            assert await mgr.start() is True
        cmd = mock_popen.call_args[0][0]
        assert cmd == [
            "/kokoro/bin/python",
            "/app/scripts/kokoro_server.py",
            "--host",
            "127.0.0.1",
            "--port",
            "9092",
            "--model",
            "/models/kokoro/kokoro-v1.0.onnx",
            "--voices",
            "/models/kokoro/voices-v1.0.bin",
        ]

    @pytest.mark.asyncio
    async def test_start_fails_and_cleans_up_when_unhealthy(self) -> None:
        mgr = self._manager()
        with (
            patch.object(voice_mod.subprocess, "Popen") as mock_popen,
            patch.object(mgr, "_wait_for_health", AsyncMock(return_value=False)),
            patch.object(mgr, "_cleanup_process") as mock_cleanup,
            patch.object(voice_mod.logger, "error"),
            patch.object(Path, "exists", return_value=True),
        ):
            assert await mgr.start() is False
        mock_popen.assert_called_once()
        mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_closes_client(self) -> None:
        mgr = self._manager()
        fake = _FakeAsyncClient()
        mgr._client = fake  # type: ignore[assignment]
        mgr._process = MagicMock()
        await mgr.stop()
        fake.aclose.assert_awaited_once()
        assert mgr._client is None
