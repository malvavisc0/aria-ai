from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import chainlit as cl
import pytest

from aria.web.rendering import create_render_elements, extract_renderable_items


class TestExtractRenderableItems:
    def test_extracts_backtick_path(self, tmp_path: Path) -> None:
        f = tmp_path / "report.md"
        f.write_text("# Report")
        text = f"I saved it to `{f}` for you"
        paths, urls = extract_renderable_items(text)
        assert paths == [str(f)]
        assert urls == []

    def test_extracts_standalone_path_on_own_line(self, tmp_path: Path) -> None:
        f = tmp_path / "report.md"
        f.write_text("# Report")
        text = f"Here's the summary.\n{f}"
        paths, urls = extract_renderable_items(text)
        assert paths == [str(f)]

    def test_extracts_standalone_path_with_label(self, tmp_path: Path) -> None:
        f = tmp_path / "report.md"
        f.write_text("# Report")
        text = f"Done!\nFile: {f}"
        paths, urls = extract_renderable_items(text)
        assert paths == [str(f)]

    def test_extracts_multiple_backtick_paths(self, tmp_path: Path) -> None:
        f1 = tmp_path / "code.py"
        f1.write_text("print(1)")
        f2 = tmp_path / "data.json"
        f2.write_text("{}")
        text = f"Files: `{f1}` and `{f2}`"
        paths, urls = extract_renderable_items(text)
        assert str(f1) in paths
        assert str(f2) in paths

    def test_extracts_path_from_markdown_link(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.txt"
        f.write_text("notes")
        text = f"See [the notes]({f}) for details"
        paths, urls = extract_renderable_items(text)
        assert paths == [str(f)]

    def test_extracts_backtick_url(self) -> None:
        text = "Image: `https://example.com/cat.png`"
        paths, urls = extract_renderable_items(text)
        assert paths == []
        assert urls == ["https://example.com/cat.png"]

    def test_extracts_standalone_url(self) -> None:
        text = "Here's the chart:\nhttps://example.com/chart.pdf"
        paths, urls = extract_renderable_items(text)
        assert urls == ["https://example.com/chart.pdf"]

    def test_ignores_bare_path_in_prose(self, tmp_path: Path) -> None:
        """Bare paths embedded in prose must not be rendered."""
        f = tmp_path / "report.md"
        f.write_text("# Report")
        text = f"The config at {f} needs editing"
        paths, urls = extract_renderable_items(text)
        assert paths == []

    def test_ignores_bare_url_in_prose(self) -> None:
        text = "Check https://example.com/cat.png for the image"
        paths, urls = extract_renderable_items(text)
        assert urls == []

    def test_skips_nonexistent_paths(self) -> None:
        text = "Missing: `/nonexistent/file.md`"
        paths, urls = extract_renderable_items(text)
        assert paths == []

    def test_deduplicates(self, tmp_path: Path) -> None:
        f = tmp_path / "dup.md"
        f.write_text("dup")
        text = f"`{f}` and again `{f}`"
        paths, urls = extract_renderable_items(text)
        assert paths == [str(f)]


class TestCreateRenderElements:
    @pytest.fixture
    def mock_elements(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock cl.Text/Image/Pdf/File so they don't need a Chainlit context."""
        for name in ("Text", "Image", "Pdf", "File"):
            monkeypatch.setattr(cl, name, lambda **kw: SimpleNamespace(**kw))

    def test_text_file_becomes_cl_text(
        self, tmp_path: Path, mock_elements: None
    ) -> None:
        f = tmp_path / "report.md"
        f.write_text("# Report")
        elements = create_render_elements([str(f)], [])
        assert len(elements) == 1
        assert elements[0].name == "report.md"

    def test_image_becomes_cl_image(self, tmp_path: Path, mock_elements: None) -> None:
        f = tmp_path / "photo.png"
        f.write_bytes(b"\x89PNG")
        elements = create_render_elements([str(f)], [])
        assert len(elements) == 1
        assert elements[0].name == "photo.png"

    def test_pdf_becomes_cl_pdf(self, tmp_path: Path, mock_elements: None) -> None:
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF")
        elements = create_render_elements([str(f)], [])
        assert len(elements) == 1
        assert elements[0].name == "doc.pdf"

    def test_unknown_ext_becomes_cl_file(
        self, tmp_path: Path, mock_elements: None
    ) -> None:
        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00")
        elements = create_render_elements([str(f)], [])
        assert len(elements) == 1
        assert elements[0].name == "data.bin"

    def test_remote_image_url_becomes_cl_image(self, mock_elements: None) -> None:
        elements = create_render_elements([], ["https://example.com/cat.png"])
        assert len(elements) == 1
        assert elements[0].name == "cat.png"

    def test_mixed_paths_and_urls(self, tmp_path: Path, mock_elements: None) -> None:
        f = tmp_path / "code.py"
        f.write_text("print(1)")
        elements = create_render_elements([str(f)], ["https://example.com/img.jpg"])
        assert len(elements) == 2
