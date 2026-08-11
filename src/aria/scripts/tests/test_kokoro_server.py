"""Tests for the persistent Kokoro TTS server script."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aria.scripts import kokoro_server as server_mod

pytestmark = pytest.mark.voice


def _make_handler(kokoro: Any, path: str, body: bytes = b"") -> Any:
    """Create a handler instance (skipping BaseHTTPRequestHandler.__init__)
    with the minimum attributes needed to exercise do_GET/do_POST."""
    handler_cls = server_mod._build_handler(kokoro)
    h = handler_cls.__new__(handler_cls)  # type: ignore[arg-type]
    h.path = path  # type: ignore[attr-defined]
    h.headers = {"Content-Length": str(len(body))}  # type: ignore[attr-defined]
    h.rfile = io.BytesIO(body)  # type: ignore[attr-defined]
    h.wfile = io.BytesIO()  # type: ignore[attr-defined]
    h._response_code: int | None = None  # type: ignore[attr-defined]
    h._headers: dict[str, str] = {}  # type: ignore[attr-defined]

    def _send_response(code: int) -> None:
        h._response_code = code  # type: ignore[attr-defined]

    def _send_header(key: str, value: str) -> None:
        h._headers[key] = value  # type: ignore[attr-defined]

    def _end_headers() -> None:
        pass

    def _send_error(code: int, message: str) -> None:
        h._response_code = code  # type: ignore[attr-defined]
        h._headers["Content-Type"] = "application/json"  # type: ignore[attr-defined]
        h.wfile.write(json.dumps({"error": message}).encode())  # type: ignore[attr-defined]

    h.send_response = _send_response  # type: ignore[assignment,method-assign]
    h.send_header = _send_header  # type: ignore[assignment,method-assign]
    h.end_headers = _end_headers  # type: ignore[assignment,method-assign]
    h.send_error = _send_error  # type: ignore[assignment,method-assign]
    return h


class TestHealthEndpoint:
    def test_health_returns_ok(self) -> None:
        h = _make_handler(MagicMock(), "/health")
        h.do_GET()
        assert h._response_code == 200
        assert json.loads(h.wfile.getvalue()) == {"status": "ok"}

    def test_unknown_path_returns_404(self) -> None:
        h = _make_handler(MagicMock(), "/unknown")
        h.do_GET()
        assert h._response_code == 404


class TestSynthesizeEndpoint:
    def test_synthesize_returns_wav(self) -> None:
        kokoro = MagicMock()
        kokoro.create.return_value = ([0.0, 0.1, 0.2], 24000)
        body = json.dumps(
            {"text": "hello", "voice": "af_heart", "lang": "en-us", "speed": 1.0}
        ).encode()
        h = _make_handler(kokoro, "/synthesize", body)

        with patch.object(server_mod, "_encode_wav", return_value=b"RIFFwav"):
            h.do_POST()

        assert h._response_code == 200
        assert h.wfile.getvalue() == b"RIFFwav"
        kokoro.create.assert_called_once_with(
            "hello", voice="af_heart", speed=1.0, lang="en-us"
        )

    def test_synthesize_empty_text_returns_400(self) -> None:
        body = json.dumps({"text": "  "}).encode()
        h = _make_handler(MagicMock(), "/synthesize", body)
        h.do_POST()
        assert h._response_code == 400

    def test_synthesize_bad_json_returns_400(self) -> None:
        h = _make_handler(MagicMock(), "/synthesize", b"not json")
        h.do_POST()
        assert h._response_code == 400

    def test_synthesize_failure_returns_500(self) -> None:
        kokoro = MagicMock()
        kokoro.create.side_effect = RuntimeError("model error")
        body = json.dumps({"text": "hello"}).encode()
        h = _make_handler(kokoro, "/synthesize", body)
        h.do_POST()
        assert h._response_code == 500

    def test_unknown_post_path_returns_404(self) -> None:
        h = _make_handler(MagicMock(), "/unknown", b"")
        h.do_POST()
        assert h._response_code == 404


class TestLoadKokoro:
    def test_load_kokoro_raises_without_dependency(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins

        real_import = builtins.__import__

        def _block_kokoro(
            name: str,
            globals: dict[str, object] | None = None,
            locals: dict[str, object] | None = None,
            fromlist: list[str] | None = None,
            level: int = 0,
        ) -> Any:
            if name == "kokoro_onnx":
                raise ImportError("not found")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", _block_kokoro)
        with pytest.raises(RuntimeError, match="kokoro_onnx is not installed"):
            server_mod._load_kokoro(tmp_path / "model.onnx", tmp_path / "voices.bin")
