"""Voice assistant server managers: whisper.cpp (STT) and kokoro-tts (TTS).

``WhisperCppManager`` follows the ``LightpandaManager`` pattern (persistent
serve-mode subprocess, health poll, graceful stop). STT is performed by a
direct multipart POST to the server's ``/inference`` endpoint (whisper.cpp's
prebuilt server does not expose the OpenAI-compatible route). ``KokoroManager``
launches a persistent Kokoro HTTP server (``scripts/kokoro_server.py``) under
the kokoro tool's Python so the 330 MB ONNX model loads once per session,
reducing per-synthesis latency from ~16 s (per-subprocess reload) to ~300 ms.

Both managers run a port preflight before spawning: if a stale process from
a crashed aria instance is still holding the port, it is killed automatically
so the new server can bind cleanly.  stdout/stderr are redirected to log
files (``logs/whisper.log``, ``logs/kokoro.log``) so startup failures are
diagnosable without pipe-buffer deadlocks.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

from aria.config.folders import Debug as DebugConfig


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Return True if *port* already has a listener on *host."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        return sock.connect_ex((host, port)) == 0
    finally:
        sock.close()


def _pids_on_port(port: int) -> list[int]:
    """Return PIDs of processes listening on *port* (via ``lsof``).

    Returns an empty list when ``lsof`` is unavailable or finds nothing.
    Only works on POSIX systems where ``lsof`` is installed.
    """
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [int(p) for p in result.stdout.strip().split() if p.strip()]


def _preflight_port(port: int, name: str) -> None:
    """Kill any stale process holding *port* before starting *name*.

    When a previous aria instance was killed (SIGKILL, OOM, crash), its
    voice child processes survive as orphans — holding the target port.
    Starting a new server alongside produces a confusing bind failure or,
    worse, the health check passes against the orphan while the new
    process silently dies.

    This check runs before spawning:

    1. If the port is free, return immediately (the common case).
    2. If the port is occupied, identify the PID(s) via ``lsof`` and
       kill them (SIGTERM → SIGKILL).
    3. If the port is still in use after killing, raise so the caller
       can log a clear error.
    """
    if not _port_in_use(port):
        return

    pids = _pids_on_port(port)
    if not pids:
        raise RuntimeError(
            f"Port {port} is already in use by an unknown process. "
            f"Stop it manually before starting {name}:\n"
            f"  lsof -ti :{port} | xargs kill"
        )

    logger.warning(
        f"Port {port} is in use by PID(s) {pids} — "
        f"killing stale {name} process(es) before starting fresh..."
    )
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            continue

    time.sleep(1)

    if _port_in_use(port):
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                continue
        time.sleep(1)

    if _port_in_use(port):
        raise RuntimeError(
            f"Port {port} is still in use after killing stale {name} "
            f"process(es) (PID(s) {pids})."
        )

    logger.info(f"Port {port} is now free after cleaning up stale {name}.")


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
    ``whisper-server --host --port --model -fa`` (no subcommand) and exposes
    a multipart ``/inference`` endpoint plus a ``/health`` probe. ``-fa``
    enables flash attention (~13% faster, lower VRAM); GPU offload is
    automatic when the binary was built with a GPU backend (CUDA/Metal) —
    there is no runtime layer-offload flag (do not pass ``-ng``, which
    *disables* the GPU).
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
        self._log_file: Path | None = None

    async def start(self) -> bool:
        """Start the whisper.cpp server and wait for it to become healthy."""
        try:
            _preflight_port(self._port, "whisper.cpp")
            cmd = [
                str(self._binary),
                "--host",
                "127.0.0.1",
                "--port",
                str(self._port),
                "--model",
                str(self._model),
                "-fa",
            ]
            self._log_file = DebugConfig.logs_path.parent / "whisper.log"
            logger.debug(f"Starting whisper.cpp: {' '.join(cmd)}")
            logger.debug(f"  stderr → {self._log_file}")
            log_fh = open(self._log_file, "w")
            self._process = subprocess.Popen(
                cmd,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            log_fh.close()
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
        if not isinstance(self._process, subprocess.Popen):
            self._process = None
            return
        try:
            os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
            self._process.wait(timeout=5)
        except (subprocess.TimeoutExpired, ProcessLookupError, OSError):
            with contextlib.suppress(Exception):
                self._process.kill()
                self._process.wait()
        self._process = None

    async def _wait_for_health(self) -> bool:
        """Poll the /health endpoint until it responds."""
        url = f"{self._base_url}/health"
        loop = asyncio.get_running_loop()
        start = loop.time()
        while loop.time() - start < self.HEALTH_TIMEOUT:
            if self._process is not None and self._process.poll() is not None:
                return False
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
        self._log_file: Path | None = None

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
            _preflight_port(self._port, "kokoro")
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
            self._log_file = DebugConfig.logs_path.parent / "kokoro.log"
            logger.debug(f"Starting kokoro server: {' '.join(cmd)}")
            logger.debug(f"  stderr → {self._log_file}")
            log_fh = open(self._log_file, "w")
            self._process = subprocess.Popen(
                cmd,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            log_fh.close()
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
        if not isinstance(self._process, subprocess.Popen):
            self._process = None
            return
        try:
            os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
            self._process.wait(timeout=5)
        except (subprocess.TimeoutExpired, ProcessLookupError, OSError):
            with contextlib.suppress(Exception):
                self._process.kill()
                self._process.wait()
        self._process = None

    async def _wait_for_health(self) -> bool:
        """Poll the /health endpoint until it responds."""
        url = f"{self._base_url}/health"
        loop = asyncio.get_running_loop()
        start = loop.time()
        while loop.time() - start < self.HEALTH_TIMEOUT:
            if self._process is not None and self._process.poll() is not None:
                return False
            try:
                await loop.run_in_executor(
                    None, lambda: urllib.request.urlopen(url, timeout=2)
                )
                return True
            except Exception:
                pass
            await asyncio.sleep(0.3)
        return False
