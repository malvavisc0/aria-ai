"""Voice assistant server managers: whisper.cpp (STT) and kokoro-tts (TTS).

``WhisperCppManager`` follows the ``LightpandaManager`` pattern (persistent
serve-mode subprocess, health poll, graceful stop). STT is performed by a
direct multipart POST to the server's ``/inference`` endpoint (whisper.cpp's
prebuilt server does not expose the OpenAI-compatible route). ``KokoroManager``
launches a persistent Kokoro HTTP server (``scripts/kokoro_server.py``) under
the kokoro tool's Python so the 330 MB ONNX model loads once per session,
reducing per-synthesis latency from ~16 s (per-subprocess reload) to ~300 ms.
"""

from __future__ import annotations

import asyncio
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger


class _VoiceManagerHolder:
    whisper: Optional["WhisperCppManager"] = None
    kokoro: Optional["KokoroManager"] = None


_holder = _VoiceManagerHolder()


def get_whisper_manager() -> Optional["WhisperCppManager"]:
    return _holder.whisper


def set_whisper_manager(m: Optional["WhisperCppManager"]) -> None:
    _holder.whisper = m


def get_kokoro_manager() -> Optional["KokoroManager"]:
    return _holder.kokoro


def set_kokoro_manager(m: Optional["KokoroManager"]) -> None:
    _holder.kokoro = m


class WhisperCppManager:
    """Manages a persistent whisper.cpp server (STT).

    Started during ``on_app_startup`` if ``Voice.is_available()``, stopped
    during ``on_app_shutdown``. The server is launched with
    ``whisper-server --host --port --model`` (no subcommand) and exposes a
    multipart ``/inference`` endpoint plus a ``/health`` probe.
    """

    HEALTH_TIMEOUT = 30.0
    INFERENCE_PATH = "/inference"

    def __init__(self, binary_path: Path, model_path: Path, port: int):
        self._binary = binary_path
        self._model = model_path
        self._port = port
        self._process: subprocess.Popen | None = None
        self._base_url = f"http://127.0.0.1:{port}"
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> bool:
        """Start the whisper.cpp server and wait for it to become healthy."""
        try:
            cmd = [
                str(self._binary),
                "--host",
                "127.0.0.1",
                "--port",
                str(self._port),
                "--model",
                str(self._model),
            ]
            logger.debug(f"Starting whisper.cpp: {' '.join(cmd)}")
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if not await self._wait_for_health():
                logger.error("whisper.cpp /health did not become ready")
                self._cleanup_process()
                return False
            self._client = httpx.AsyncClient(timeout=60.0)
            logger.info(f"whisper.cpp started on port {self._port}")
            return True
        except Exception as e:
            logger.error(f"Failed to start whisper.cpp: {e}")
            await self.stop()
            return False

    async def transcribe(self, wav_bytes: bytes) -> str:
        """POST wav_bytes to /inference and return the transcript."""
        if self._client is None:
            return ""
        try:
            response = await self._client.post(
                f"{self._base_url}{self.INFERENCE_PATH}",
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                data={"response_format": "json"},
            )
            response.raise_for_status()
            return response.json().get("text", "")
        except httpx.HTTPError as e:
            logger.error(f"whisper.cpp transcription failed: {e}")
            return ""

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._cleanup_process()
        logger.info("whisper.cpp stopped")

    def _cleanup_process(self) -> None:
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            except Exception as e:
                logger.warning(f"Error terminating whisper.cpp: {e}")
            finally:
                self._process = None

    async def _wait_for_health(self) -> bool:
        """Poll the /health endpoint until it responds."""
        url = f"{self._base_url}/health"
        loop = asyncio.get_running_loop()
        start = loop.time()
        while loop.time() - start < self.HEALTH_TIMEOUT:
            try:
                await loop.run_in_executor(
                    None, lambda: urllib.request.urlopen(url, timeout=2)
                )
                return True
            except Exception:
                pass
            await asyncio.sleep(0.3)
        return False


class KokoroManager:
    """Manages a persistent Kokoro TTS HTTP server (one model load per session).

    Launches ``scripts/kokoro_server.py`` under the kokoro tool's Python so the
    ONNX model loads once at startup; subsequent ``synthesize()`` calls POST to
    ``/synthesize`` and return WAV bytes in ~300 ms (vs ~16 s per-subprocess
    reload of the one-shot CLI). Mirrors ``WhisperCppManager``: persistent
    subprocess + health poll + httpx client + graceful stop.
    """

    HEALTH_TIMEOUT = 30.0
    SYNTHESIS_TIMEOUT = 30.0
    SYNTHESIZE_PATH = "/synthesize"

    def __init__(
        self,
        server_script: Path,
        model_path: Path,
        voices_path: Path,
        python_exe: Path,
        port: int,
        voice: str,
        lang: str,
    ):
        self._server_script = server_script
        self._model_path = model_path
        self._voices_path = voices_path
        self._python = python_exe
        self._port = port
        self._voice = voice
        self._lang = lang
        self._process: subprocess.Popen | None = None
        self._base_url = f"http://127.0.0.1:{port}"
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> bool:
        """Start the kokoro server and wait for it to become healthy.

        Returns:
            True if the server started and passed the health probe, False
            otherwise (missing interpreter, load failure, or health timeout).
        """
        if not self._python.exists():
            logger.warning(
                f"kokoro Python interpreter not found at {self._python} — "
                "TTS disabled. Run 'aria voice download' to install kokoro-tts."
            )
            return False
        try:
            cmd = [
                str(self._python),
                str(self._server_script),
                "--host",
                "127.0.0.1",
                "--port",
                str(self._port),
                "--model",
                str(self._model_path),
                "--voices",
                str(self._voices_path),
            ]
            logger.debug(f"Starting kokoro server: {' '.join(cmd)}")
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if not await self._wait_for_health():
                logger.error("kokoro server /health did not become ready")
                self._cleanup_process()
                return False
            self._client = httpx.AsyncClient(timeout=self.SYNTHESIS_TIMEOUT)
            logger.info(f"kokoro TTS server started on port {self._port}")
            return True
        except Exception as e:
            logger.error(f"Failed to start kokoro server: {e}")
            await self.stop()
            return False

    async def synthesize(self, text: str) -> bytes:
        """POST text to /synthesize and return WAV bytes.

        Args:
            text: Text to synthesize.

        Returns:
            WAV bytes, or ``b""`` if synthesis fails or the server is down.
        """
        if self._client is None or not text.strip():
            return b""
        try:
            response = await self._client.post(
                f"{self._base_url}{self.SYNTHESIZE_PATH}",
                json={
                    "text": text,
                    "voice": self._voice,
                    "lang": self._lang,
                    "speed": 1.0,
                },
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as e:
            logger.error(f"kokoro synthesis failed: {e}")
            return b""

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._cleanup_process()
        logger.info("kokoro TTS server stopped")

    def _cleanup_process(self) -> None:
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            except Exception as e:
                logger.warning(f"Error terminating kokoro server: {e}")
            finally:
                self._process = None

    async def _wait_for_health(self) -> bool:
        """Poll the /health endpoint until it responds."""
        url = f"{self._base_url}/health"
        loop = asyncio.get_running_loop()
        start = loop.time()
        while loop.time() - start < self.HEALTH_TIMEOUT:
            try:
                await loop.run_in_executor(
                    None, lambda: urllib.request.urlopen(url, timeout=2)
                )
                return True
            except Exception:
                pass
            await asyncio.sleep(0.3)
        return False
