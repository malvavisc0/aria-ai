"""Tests for aria.tools.documents.functions.extract (image OCR routing)."""

import json
from pathlib import Path
from typing import Any

import pytest

import aria.tools.documents.functions as doc_functions
from aria.tools.documents.functions import extract


def _parse(result: str) -> dict[str, Any]:
    return json.loads(result)["data"]


def _image(tmp_path: Path, name: str) -> Path:
    fp = tmp_path / name
    fp.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    return fp


@pytest.fixture()
def image_file(tmp_path: Path) -> Path:
    return _image(tmp_path, "scan.png")


@pytest.fixture()
def fake_worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Pretend the docling shim + worker exist and conversion succeeds.

    Records the input paths each (mocked) worker invocation received.
    """
    shim = tmp_path / "docling"
    shim.write_text("#!/bin/sh\n")
    monkeypatch.setattr(doc_functions, "_worker_shim", lambda: shim)
    calls: list[list[Path]] = []

    def _convert(paths, **kwargs):
        calls.append(list(paths))
        return {
            "ok": True,
            "pages": len(paths),
            "duration_ms": 5,
            "files": [{"name": p.name, "pages": 1} for p in paths],
        }

    monkeypatch.setattr("aria.tools.documents._subprocess.convert", _convert)
    return calls


class TestRouting:
    @pytest.mark.asyncio
    async def test_image_routed_to_docling(self, image_file, fake_worker):
        result = await extract("test", action="extract", file_name=str(image_file))
        data = _parse(result)
        assert "error" not in data
        assert data["metadata"]["backend_used"] == "granite-docling"

    @pytest.mark.asyncio
    async def test_pdf_rejected_points_to_convert(self, tmp_path):
        fp = tmp_path / "doc.pdf"
        fp.write_bytes(b"%PDF-1.4")
        data = _parse(await extract("test", action="extract", file_name=str(fp)))
        assert data["error"]["code"] == "not_an_image"
        assert "convert" in data["error"]["how_to_fix"]

    @pytest.mark.asyncio
    async def test_gif_error_names_vision_summary(self, tmp_path):
        """Gif is vision-captioned but has no OCR path — the error must
        say so instead of pointing at another dead end."""
        fp = tmp_path / "anim.gif"
        fp.write_bytes(b"GIF89a")
        data = _parse(await extract("test", action="extract", file_name=str(fp)))
        assert data["error"]["code"] == "not_an_image"
        assert "gif" in data["error"]["how_to_fix"].lower()


class TestBatch:
    """Multiple images must reach the worker as ONE invocation — that is
    what amortizes the per-call model load."""

    @pytest.mark.asyncio
    async def test_list_input_single_invocation(self, tmp_path, fake_worker):
        a, b = _image(tmp_path, "a.png"), _image(tmp_path, "b.png")
        data = _parse(
            await extract("test", action="extract", file_name=[str(a), str(b)])
        )
        assert "error" not in data
        assert len(fake_worker) == 1
        assert [p.name for p in fake_worker[0]] == ["a.png", "b.png"]
        assert data["metadata"]["files"] == [
            {"name": "a.png", "pages": 1},
            {"name": "b.png", "pages": 1},
        ]

    @pytest.mark.asyncio
    async def test_single_path_is_one_invocation(self, image_file, fake_worker):
        await extract("test", action="extract", file_name=str(image_file))
        assert len(fake_worker) == 1
        assert fake_worker[0] == [image_file]


class TestNoFallback:
    """MarkItDown cannot OCR — worker problems must be hard errors."""

    @pytest.mark.asyncio
    async def test_missing_worker_is_error_not_fallback(self, monkeypatch, image_file):
        monkeypatch.setattr(
            doc_functions, "_worker_shim", lambda: Path("/nonexistent/docling")
        )
        data = _parse(
            await extract("test", action="extract", file_name=str(image_file))
        )
        assert data["error"]["code"] == "worker_not_installed"

    @pytest.mark.asyncio
    async def test_worker_failure_is_error_not_fallback(
        self, monkeypatch, tmp_path, image_file
    ):
        shim = tmp_path / "docling"
        shim.write_text("#!/bin/sh\n")
        monkeypatch.setattr(doc_functions, "_worker_shim", lambda: shim)
        monkeypatch.setattr(
            "aria.tools.documents._subprocess.convert",
            lambda paths, **kwargs: {"ok": False, "error": "VLM crashed"},
        )
        data = _parse(
            await extract("test", action="extract", file_name=str(image_file))
        )
        assert data["error"]["code"] == "vlm_failed"
        assert "VLM crashed" in data["error"]["message"]
