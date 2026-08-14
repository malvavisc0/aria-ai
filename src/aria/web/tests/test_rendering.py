from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import chainlit as cl
import pytest

from aria.web.rendering import (
    MAX_CITATIONS,
    CitationRef,
    create_render_elements,
    extract_renderable_items,
    sources_footer,
)


class TestExtractRenderableItems:
    def test_extracts_backtick_path(self, tmp_path: Path) -> None:
        f = tmp_path / "report.md"
        f.write_text("# Report")
        text = f"I saved it to `{f}` for you"
        paths, refs = extract_renderable_items(text)
        assert paths == [str(f)]
        assert refs == []

    def test_extracts_standalone_path_on_own_line(self, tmp_path: Path) -> None:
        f = tmp_path / "report.md"
        f.write_text("# Report")
        text = f"Here's the summary.\n{f}"
        paths, refs = extract_renderable_items(text)
        assert paths == [str(f)]

    def test_extracts_standalone_path_with_label(self, tmp_path: Path) -> None:
        f = tmp_path / "report.md"
        f.write_text("# Report")
        text = f"Done!\nFile: {f}"
        paths, refs = extract_renderable_items(text)
        assert paths == [str(f)]

    def test_extracts_multiple_backtick_paths(self, tmp_path: Path) -> None:
        f1 = tmp_path / "code.py"
        f1.write_text("print(1)")
        f2 = tmp_path / "data.json"
        f2.write_text("{}")
        text = f"Files: `{f1}` and `{f2}`"
        paths, refs = extract_renderable_items(text)
        assert str(f1) in paths
        assert str(f2) in paths

    def test_extracts_path_from_markdown_link(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.txt"
        f.write_text("notes")
        text = f"See [the notes]({f}) for details"
        paths, refs = extract_renderable_items(text)
        assert paths == [str(f)]

    def test_extracts_backtick_url(self) -> None:
        text = "Image: `https://example.com/cat.png`"
        paths, refs = extract_renderable_items(text)
        assert paths == []
        assert refs == [CitationRef(None, "https://example.com/cat.png")]

    def test_extracts_standalone_url(self) -> None:
        text = "Here's the chart:\nhttps://example.com/chart.pdf"
        paths, refs = extract_renderable_items(text)
        assert refs == [CitationRef(None, "https://example.com/chart.pdf")]

    def test_markdown_link_keeps_link_text_as_name(self) -> None:
        text = "See the [CachyOS wiki page](https://wiki.cachyos.org/switch_desktop/)"
        _, refs = extract_renderable_items(text)
        assert refs == [
            CitationRef("CachyOS wiki page", "https://wiki.cachyos.org/switch_desktop/")
        ]

    def test_markdown_link_with_url_text_has_no_name(self) -> None:
        text = "Source: [https://example.com](https://example.com)"
        _, refs = extract_renderable_items(text)
        assert refs == [CitationRef(None, "https://example.com")]

    def test_ignores_bare_path_in_prose(self, tmp_path: Path) -> None:
        """Bare paths embedded in prose must not be rendered."""
        f = tmp_path / "report.md"
        f.write_text("# Report")
        text = f"The config at {f} needs editing"
        paths, refs = extract_renderable_items(text)
        assert paths == []

    def test_extracts_bare_url_in_prose(self) -> None:
        """Bare URLs are citation candidates — models cite this way often."""
        text = "Check https://example.com/cat.png for the image"
        paths, refs = extract_renderable_items(text)
        assert refs == [CitationRef(None, "https://example.com/cat.png")]

    def test_extracts_bold_wrapped_bare_url(self) -> None:
        text = "The official URL is **https://wiki.cachyos.org/**. Enjoy."
        _, refs = extract_renderable_items(text)
        assert refs == [CitationRef(None, "https://wiki.cachyos.org/")]

    def test_bare_url_balanced_parens_preserved(self) -> None:
        """Wikipedia-style URLs must not be truncated at the parenthesis."""
        text = "see https://en.wikipedia.org/wiki/Linux_(kernel) for details"
        _, refs = extract_renderable_items(text)
        assert refs == [
            CitationRef(None, "https://en.wikipedia.org/wiki/Linux_(kernel)")
        ]

    def test_bare_url_unbalanced_trailing_paren_trimmed(self) -> None:
        text = "(https://example.com/page)."
        _, refs = extract_renderable_items(text)
        assert refs == [CitationRef(None, "https://example.com/page")]

    def test_bare_url_trailing_wildcard_preserved(self) -> None:
        text = "query: https://example.com/?q=* works"
        _, refs = extract_renderable_items(text)
        assert refs == [CitationRef(None, "https://example.com/?q=*")]

    def test_bare_url_sentence_punctuation_trimmed(self) -> None:
        text = "Docs at https://example.com/a_b, really."
        _, refs = extract_renderable_items(text)
        assert refs == [CitationRef(None, "https://example.com/a_b")]

    def test_urls_in_fenced_code_are_not_cited(self) -> None:
        """Fenced blocks hold documentation examples, not citations."""
        text = "```\nhttps://example.com/in-fence\n```\nsee https://example.com/real"
        _, refs = extract_renderable_items(text)
        assert refs == [CitationRef(None, "https://example.com/real")]

    def test_backtick_wrapped_url_is_cited(self) -> None:
        """Inline backtick spans stay eligible (pre-existing behavior)."""
        text = "Run `curl https://example.com/in-span` please"
        _, refs = extract_renderable_items(text)
        assert refs == [CitationRef(None, "https://example.com/in-span")]

    def test_markdown_name_wins_over_bare_duplicate(self) -> None:
        text = "See [the guide](https://example.com/g) — also https://example.com/g"
        _, refs = extract_renderable_items(text)
        assert refs == [CitationRef("the guide", "https://example.com/g")]

    def test_skips_nonexistent_paths(self) -> None:
        text = "Missing: `/nonexistent/file.md`"
        paths, refs = extract_renderable_items(text)
        assert paths == []

    def test_deduplicates(self, tmp_path: Path) -> None:
        f = tmp_path / "dup.md"
        f.write_text("dup")
        text = f"`{f}` and again `{f}`"
        paths, refs = extract_renderable_items(text)
        assert paths == [str(f)]

    def test_deduplicates_urls_keeping_first_name(self) -> None:
        text = "[first](https://example.com/) and [second](https://example.com/)"
        _, refs = extract_renderable_items(text)
        assert refs == [CitationRef("first", "https://example.com/")]


class TestCreateRenderElements:
    @pytest.fixture
    def mock_elements(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock cl.Text/Image/Pdf/File so they don't need a Chainlit context."""
        for name in ("Text", "Image", "Pdf", "File"):
            monkeypatch.setattr(cl, name, lambda **kw: SimpleNamespace(**kw))

    @pytest.fixture
    def mock_citations(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        """Keep citation building offline; records the refs it was given."""
        builder = AsyncMock(return_value=[SimpleNamespace(name="citation")])
        monkeypatch.setattr("aria.web.rendering.build_citation_elements", builder)
        return builder

    async def test_text_file_becomes_cl_text(
        self, tmp_path: Path, mock_elements: None
    ) -> None:
        f = tmp_path / "report.md"
        f.write_text("# Report")
        elements, _ = await create_render_elements([str(f)], [])
        assert len(elements) == 1
        assert elements[0].name == "report.md"

    async def test_image_becomes_cl_image(
        self, tmp_path: Path, mock_elements: None
    ) -> None:
        f = tmp_path / "photo.png"
        f.write_bytes(b"\x89PNG")
        elements, _ = await create_render_elements([str(f)], [])
        assert len(elements) == 1
        assert elements[0].name == "photo.png"

    async def test_pdf_becomes_cl_pdf(
        self, tmp_path: Path, mock_elements: None
    ) -> None:
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF")
        elements, _ = await create_render_elements([str(f)], [])
        assert len(elements) == 1
        assert elements[0].name == "doc.pdf"

    async def test_unknown_ext_becomes_cl_file(
        self, tmp_path: Path, mock_elements: None
    ) -> None:
        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00")
        elements, _ = await create_render_elements([str(f)], [])
        assert len(elements) == 1
        assert elements[0].name == "data.bin"

    async def test_remote_image_url_becomes_cl_image(self, mock_elements: None) -> None:
        elements, _ = await create_render_elements(
            [], [CitationRef(None, "https://example.com/cat.png")]
        )
        assert len(elements) == 1
        assert elements[0].name == "cat.png"

    async def test_mixed_paths_and_urls(
        self, tmp_path: Path, mock_elements: None
    ) -> None:
        f = tmp_path / "code.py"
        f.write_text("print(1)")
        elements, _ = await create_render_elements(
            [str(f)], [CitationRef(None, "https://example.com/img.jpg")]
        )
        assert len(elements) == 2

    async def test_citation_ref_uses_link_text_as_name(
        self, mock_elements: None, mock_citations: AsyncMock
    ) -> None:
        await create_render_elements(
            [], [CitationRef("the guide", "https://example.com/guide")]
        )
        mock_citations.assert_awaited_once_with(
            [("the guide", "https://example.com/guide")]
        )

    async def test_citation_ref_falls_back_to_url_name(
        self, mock_elements: None, mock_citations: AsyncMock
    ) -> None:
        await create_render_elements(
            [], [CitationRef(None, "https://example.com/switch_desktop/")]
        )
        mock_citations.assert_awaited_once_with(
            [("switch_desktop", "https://example.com/switch_desktop/")]
        )

    async def test_citations_capped(
        self, mock_elements: None, mock_citations: AsyncMock
    ) -> None:
        refs = [CitationRef(None, f"https://example.com/page{i}") for i in range(9)]
        elements, names = await create_render_elements([], refs)
        call = mock_citations.await_args
        assert call is not None
        assert len(call.args[0]) == MAX_CITATIONS
        assert len(elements) == 1
        assert names == ["citation"]

    async def test_citation_names_returned(
        self, mock_elements: None, mock_citations: AsyncMock
    ) -> None:
        _, names = await create_render_elements(
            [], [CitationRef("the guide", "https://example.com/guide")]
        )
        assert names == ["citation"]


class TestSourcesFooter:
    def test_footer_lists_names(self) -> None:
        assert sources_footer(["A", "B"]) == "\n\n**Sources:** " + " · ".join(
            ["A", "B"]
        )

    def test_footer_empty_without_names(self) -> None:
        assert sources_footer([]) == ""
