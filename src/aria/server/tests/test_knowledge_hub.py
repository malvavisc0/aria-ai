"""Tests for the knowledge hub indexer."""

from __future__ import annotations

import hashlib
from pathlib import Path

import chromadb
import pytest

from aria.config.api import KnowledgeHub
from aria.server.knowledge_hub import (
    KnowledgeHubIndexer,
    _chunk_id,
    _merge_small,
)
from aria.web.state import _state

_DIM = 64


class _FakeEmbeddings:
    """Deterministic hash-based embeddings for testing.

    Raises on texts containing *fail_marker* to simulate embedding
    failures for per-file isolation tests.
    """

    def __init__(self, fail_marker: str | None = None) -> None:
        self._fail_marker = fail_marker

    async def aget_text_embedding(self, text: str) -> list[float]:
        if self._fail_marker and self._fail_marker in text:
            raise RuntimeError("fake embed failure")
        return self._embed(text)

    async def aget_text_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        if self._fail_marker and any(self._fail_marker in t for t in texts):
            raise RuntimeError("fake embed failure")
        return [self._embed(t) for t in texts]

    @staticmethod
    def _embed(text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        return [b / 255.0 for b in (h * (_DIM // len(h) + 1))[:_DIM]]


@pytest.fixture(autouse=True)
def _hub_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Point the hub at a temp dir and wire up in-memory infra.

    Depends on ``test_tools_db`` (requested via *request* so the temp
    DB and singleton reset run before this fixture) so
    ``KnowledgeIndexStateModel`` is created in an isolated temp DB.
    """
    request.getfixturevalue("test_tools_db")
    monkeypatch.setattr(KnowledgeHub, "dir", str(tmp_path / "docs"))
    monkeypatch.setattr(KnowledgeHub, "enabled", True)
    monkeypatch.setattr(_state, "vector_db", chromadb.EphemeralClient())
    monkeypatch.setattr(_state, "embeddings", _FakeEmbeddings())


@pytest.fixture()
def indexer() -> KnowledgeHubIndexer:
    return KnowledgeHubIndexer()


class TestMergeSmall:
    """Unit tests for the chunk merge helper."""

    def test_combines_short_chunks(self) -> None:
        chunks = ["aaa", "bbb", "ccc"]
        result = _merge_small(chunks, 10)
        assert len(result) == 1
        assert "aaa" in result[0]
        assert "bbb" in result[0]
        assert "ccc" in result[0]

    def test_keeps_oversize_as_is(self) -> None:
        big = "x" * 50
        result = _merge_small([big, "y"], 10)
        assert big in result
        assert "y" in result

    def test_empty_input(self) -> None:
        assert _merge_small([], 100) == []


class TestChunkId:
    """Unit tests for the source-scoped chunk id."""

    def test_different_sources_get_different_ids(self) -> None:
        text = "same content"
        assert _chunk_id("file_a.txt", text) != _chunk_id("file_b.txt", text)

    def test_same_source_same_text_is_idempotent(self) -> None:
        text = "same content"
        assert _chunk_id("file_a.txt", text) == _chunk_id("file_a.txt", text)


class TestReindex:
    """End-to-end indexer tests using an in-memory ChromaDB."""

    @pytest.mark.asyncio
    async def test_text_file_indexed_and_queryable(
        self, indexer: KnowledgeHubIndexer, tmp_path: Path
    ) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "notes.txt").write_text("The quick brown fox jumps over the dog.")

        result = await indexer.reindex()
        assert result["indexed"] > 0
        assert result["skipped"] == []

        hits = await indexer.query("fox", top_k=4)
        assert len(hits) == 1
        assert hits[0]["source"] == "notes.txt"
        assert "fox" in hits[0]["text"]

    @pytest.mark.asyncio
    async def test_idempotent_rerun_is_noop(
        self, indexer: KnowledgeHubIndexer, tmp_path: Path
    ) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.txt").write_text("hello world content for testing")

        first = await indexer.reindex()
        assert first["indexed"] > 0
        second = await indexer.reindex()
        assert second["indexed"] == 0
        assert second["skipped"] == []

    @pytest.mark.asyncio
    async def test_force_rebuild(
        self, indexer: KnowledgeHubIndexer, tmp_path: Path
    ) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.txt").write_text("hello world content for testing")

        await indexer.reindex()
        result = await indexer.reindex(force=True)
        assert result["forced"] is True
        assert result["indexed"] > 0

    @pytest.mark.asyncio
    async def test_removed_file_purged(
        self, indexer: KnowledgeHubIndexer, tmp_path: Path
    ) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        keep = docs / "keep.txt"
        gone = docs / "gone.txt"
        keep.write_text("keeping this file for retrieval")
        gone.write_text("this file will be deleted soon")

        await indexer.reindex()
        hits_before = await indexer.query("deleted", top_k=10)
        assert any(h["source"] == "gone.txt" for h in hits_before)

        gone.unlink()
        await indexer.reindex()

        hits_after = await indexer.query("deleted", top_k=10)
        assert all(h["source"] != "gone.txt" for h in hits_after)
        assert any(h["source"] == "keep.txt" for h in hits_after)

    @pytest.mark.asyncio
    async def test_skip_too_large(
        self,
        indexer: KnowledgeHubIndexer,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(KnowledgeHub, "max_file_mb", 0)
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "big.txt").write_text("x" * 10)

        result = await indexer.reindex()
        assert result["indexed"] == 0
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["reason"] == "too_large"
        assert result["skipped"][0]["size"] == 10

    @pytest.mark.asyncio
    async def test_skip_unsupported_type(
        self, indexer: KnowledgeHubIndexer, tmp_path: Path
    ) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "data.bin").write_bytes(b"\x00\x01\x02")

        result = await indexer.reindex()
        assert result["indexed"] == 0
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["reason"] == "unsupported_type"

    @pytest.mark.asyncio
    async def test_per_file_isolation(
        self,
        indexer: KnowledgeHubIndexer,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            _state, "embeddings", _FakeEmbeddings(fail_marker="TRIGGER_FAIL")
        )
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "bad.txt").write_text("TRIGGER_FAIL embedding error here")
        (docs / "good.txt").write_text("this file should still be indexed fine")

        result = await indexer.reindex()
        assert any(
            s["path"].endswith("bad.txt") and s["reason"] == "embedding_error"
            for s in result["skipped"]
        )
        assert result["indexed"] > 0
        hits = await indexer.query("file", top_k=10)
        assert any(h["source"] == "good.txt" for h in hits)

    @pytest.mark.asyncio
    async def test_empty_file_clears_stale(
        self, indexer: KnowledgeHubIndexer, tmp_path: Path
    ) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        target = docs / "notes.txt"
        target.write_text("content that was here before but is now gone")

        await indexer.reindex()
        assert await indexer.query("content", top_k=10)

        target.write_text("")
        await indexer.reindex()

        hits = await indexer.query("content", top_k=10)
        assert all(h["source"] != "notes.txt" for h in hits)

    @pytest.mark.asyncio
    async def test_pdf_skipped_when_docling_missing(
        self,
        indexer: KnowledgeHubIndexer,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """PDFs must fail-fast (skipped with reason) when docling is absent.

        No silent fallback to MarkItDown: the hub's value for PDFs is
        structure-aware chunks with section headings. The skip reason
        tells the user to install the worker.
        """
        monkeypatch.setattr("aria.config.folders.Bin.path", tmp_path / "no_such_bin")
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "report.pdf").write_bytes(b"%PDF-1.4\n%fake\n")

        result = await indexer.reindex()
        assert result["indexed"] == 0
        assert len(result["skipped"]) == 1
        skip = result["skipped"][0]
        assert skip["reason"] == "docling_not_installed"
        assert skip["path"].endswith("report.pdf")
