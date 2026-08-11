"""Persistent Kokoro TTS HTTP server.

Run under the kokoro tool's own Python interpreter so the 330 MB ONNX model
loads **once** at startup and subsequent syntheses take ~100-300 ms instead of
the ~16 s per-subprocess reload of the one-shot CLI. Uses only the standard
library (the kokoro tool env has no aiohttp/fastapi).

Contract:
    GET  /health     -> {"status": "ok"}
    POST /synthesize -> JSON body {"text","voice","lang","speed"} -> audio/wav

Usage:
    python kokoro_server.py --host 127.0.0.1 --port 9092 \
        --model <kokoro-v1.0.onnx> --voices <voices-v1.0.bin>

This script imports ``kokoro_onnx`` lazily inside a factory so the module is
importable from the main project venv (for tests) without the dependency.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

KOKORO_CONTENT_TYPE = "audio/wav"


def _build_handler(kokoro: Any) -> type[BaseHTTPRequestHandler]:
    """Return a request-handler class closing over a loaded Kokoro instance.

    Kept as a factory so the lazy ``kokoro_onnx`` import (see ``_load_kokoro``)
    can be mocked in tests without importing the dependency.

    Args:
        kokoro: A loaded ``kokoro_onnx.Kokoro`` instance.

    Returns:
        A ``BaseHTTPRequestHandler`` subclass handling ``/health`` and
        ``/synthesize``.
    """

    class _KokoroHandler(BaseHTTPRequestHandler):
        # Silence default stderr request logging (the manager captures stderr;
        # per-request noise obscures model-load messages).
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, V105
            return

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            if self.path == "/health":
                body = json.dumps({"status": "ok"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_error(404, "Not Found")

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            if self.path != "/synthesize":
                self.send_error(404, "Not Found")
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length))
                text = str(payload.get("text", "")).strip()
                voice = str(payload.get("voice", "af_heart"))
                lang = str(payload.get("lang", "en-us"))
                speed = float(payload.get("speed", 1.0))
            except (ValueError, TypeError) as exc:
                self._send_error(400, f"bad request: {exc}")
                return

            if not text:
                self._send_error(400, "empty text")
                return

            try:
                samples, sample_rate = kokoro.create(
                    text, voice=voice, speed=speed, lang=lang
                )
            except Exception as exc:  # synthesis failure -> 500, no crash
                self._send_error(500, f"synthesis failed: {exc}")
                return

            wav_bytes = _encode_wav(samples, sample_rate)
            self.send_response(200)
            self.send_header("Content-Type", KOKORO_CONTENT_TYPE)
            self.send_header("Content-Length", str(len(wav_bytes)))
            self.end_headers()
            self.wfile.write(wav_bytes)

        def _send_error(self, code: int, message: str) -> None:
            body = json.dumps({"error": message}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _KokoroHandler


def _encode_wav(samples: Any, sample_rate: int) -> bytes:
    """Encode a float32 sample array to 16-bit PCM mono WAV bytes.

    Args:
        samples: 1-D float32 numpy array (from ``Kokoro.create``).
        sample_rate: Sample rate (kokoro emits 24000 Hz).

    Returns:
        WAV file bytes.
    """
    import soundfile as sf  # type: ignore[import-not-found]  # kokoro tool env only

    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _load_kokoro(model_path: Path, voices_path: Path) -> Any:
    """Load the Kokoro ONNX model (lazy import of kokoro_onnx).

    Args:
        model_path: Path to ``kokoro-v1.0.onnx``.
        voices_path: Path to ``voices-v1.0.bin``.

    Returns:
        A ``kokoro_onnx.Kokoro`` instance.

    Raises:
        RuntimeError: If the dependency is missing or the model fails to load.
    """
    try:
        from kokoro_onnx import Kokoro  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "kokoro_onnx is not installed in this interpreter. Run this "
            "script under the kokoro tool's Python."
        ) from exc
    return Kokoro(str(model_path), str(voices_path))


def main(argv: list[str] | None = None) -> int:
    """Parse args, load the model once, and serve until interrupted."""
    parser = argparse.ArgumentParser(description="Persistent Kokoro TTS HTTP server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9092)
    parser.add_argument("--model", required=True, help="Path to kokoro-v1.0.onnx")
    parser.add_argument("--voices", required=True, help="Path to voices-v1.0.bin")
    args = parser.parse_args(argv)

    model_path = Path(args.model)
    voices_path = Path(args.voices)
    if not model_path.exists():
        print(f"Model not found: {model_path}", file=sys.stderr)
        return 1
    if not voices_path.exists():
        print(f"Voices file not found: {voices_path}", file=sys.stderr)
        return 1

    print(f"Loading Kokoro model: {model_path}", file=sys.stderr)
    try:
        kokoro = _load_kokoro(model_path, voices_path)
    except RuntimeError as exc:
        print(f"Failed to load Kokoro model: {exc}", file=sys.stderr)
        return 1
    print("Kokoro model loaded", file=sys.stderr)

    handler = _build_handler(kokoro)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"kokoro server listening on {args.host}:{args.port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
