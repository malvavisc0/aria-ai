"""Knowledge hub indexer — walk a documents dir, convert, chunk, embed."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from aria.config.api import KnowledgeHub
from aria.llm.memory import _hash_node_id  # cross-boundary private import
from aria.tools.documents.functions import (
    _HTML_EXTENSIONS,
    _PDF_EXTENSIONS,
    OFFICE_EXTENSIONS,
    TEXT_EXTENSIONS,
)
from aria.tools.knowledge.models import KnowledgeIndexStateModel

_COLLECTION = "aria_knowledge"
_INDEX_LOCK = asyncio.Lock()  # sync primitive, not mutable data (AGENTS.md)

_STATE_INDEXED = "indexed"
_STATE_SKIPPED = "skipped"


class _SkipFile(Exception):
    """Raised to skip a file with a recorded reason (too large, unsupported)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason


def _chunk_id(source: str, text: str) -> str:
    """Content-hash id scoped to *source* so identical text in different
    files cannot collide (and a per-source delete never no-ops on a row
    owned by another file)."""
    return _hash_node_id(f"{source}\x00{text}")


class KnowledgeHubIndexer:
    """Walk the documents dir, convert to text, chunk, embed into Chroma."""

    def __init__(
        self, settings: KnowledgeHub | type[KnowledgeHub] = KnowledgeHub
    ) -> None:
        self._settings = settings

    async def reindex(self, force: bool = False) -> dict[str, Any]:
        async with _INDEX_LOCK:
            return await self._run(force=force)

    async def _run(self, *, force: bool = False) -> dict[str, Any]:
        from llama_index.core.node_parser import SentenceSplitter

        from aria.web.state import _state

        if _state.vector_db is None or _state.embeddings is None:
            return {"indexed": 0, "skipped": [], "error": "infra not ready"}
        if self._settings.chunk_overlap > self._settings.chunk_size:
            return {"indexed": 0, "skipped": [], "error": "overlap > chunk_size"}

        collection = _state.vector_db.get_or_create_collection(_COLLECTION)
        if force:
            _state.vector_db.delete_collection(_COLLECTION)
            collection = _state.vector_db.get_or_create_collection(_COLLECTION)
            _clear_index_state()
        splitter = SentenceSplitter(
            chunk_size=self._settings.chunk_size,
            chunk_overlap=self._settings.chunk_overlap,
        )
        root = Path(self._settings.dir)
        root.mkdir(parents=True, exist_ok=True)

        state_cache = _load_state_cache()
        indexed = 0
        skipped: list[dict[str, Any]] = []
        walked: set[str] = set()
        dirty = False
        for fp in root.rglob("*"):
            if fp.is_dir() or fp.name.startswith("."):
                continue
            rel = str(fp.relative_to(root))
            walked.add(rel)
            n, skip, did_write = await self._index_one(
                fp,
                rel,
                collection,
                _state.embeddings,
                splitter,
                state_cache,
                force=force,
            )
            indexed += n
            if skip is not None:
                skipped.append(skip)
            dirty = dirty or did_write
        if dirty:
            _flush_state_cache(state_cache)
        await asyncio.to_thread(_purge_removed, collection, walked)
        return {"indexed": indexed, "skipped": skipped, "forced": force}

    async def _index_one(
        self,
        fp: Path,
        rel: str,
        collection: Any,
        embed_model: Any,
        splitter: Any,
        state_cache: dict[str, _FileState],
        *,
        force: bool,
    ) -> tuple[int, dict[str, Any] | None, bool]:
        """Process one file: extract, merge, embed, store.

        Returns ``(chunks_added, skip_entry, did_write)`` where
        *skip_entry* is ``None`` for a successful index or an
        already-processed no-op, and *did_write* is True when the
        state cache was mutated (caller flushes once at the end).

        Per-file isolation: any failure records a skip and returns
        ``0`` instead of propagating, so one bad file never aborts the
        run. The prior-source delete only runs after embedding succeeds,
        so a transient embed failure cannot drop already-stored chunks.

        Transient errors (conversion_error, embedding_error) are NOT
        persisted — they're retried on the next run. Only deterministic
        skips (too_large, unsupported_type) and successful indexes are
        cached.
        """
        st = fp.stat()
        size = st.st_size
        if not force and _is_cached(state_cache, rel, st):
            return 0, None, False
        try:
            chunks = await self._extract_chunks(fp, size, splitter)
        except _SkipFile as exc:
            _set_cached(state_cache, rel, st, _STATE_SKIPPED, exc.reason)
            return 0, {"path": str(fp), "reason": exc.reason, "size": size}, True
        except Exception as exc:
            logger.warning(f"knowledge hub: convert failed {fp}: {exc}")
            return (
                0,
                {"path": str(fp), "reason": "conversion_error", "size": size},
                False,
            )
        chunks = _merge_small(chunks, self._settings.chunk_size)
        if not chunks:
            await asyncio.to_thread(collection.delete, where={"source": rel})
            _set_cached(state_cache, rel, st, _STATE_INDEXED)
            return 0, None, True
        try:
            embeddings = await embed_model.aget_text_embedding_batch(chunks)
        except Exception as exc:
            logger.warning(f"knowledge hub: embed failed {fp}: {exc}")
            return (
                0,
                {"path": str(fp), "reason": "embedding_error", "size": size},
                False,
            )
        ids = [_chunk_id(rel, c) for c in chunks]
        metadatas = [{"source": rel} for _ in chunks]

        def _store() -> None:
            collection.delete(where={"source": rel})
            collection.add(
                ids=ids,
                embeddings=embeddings,  # type: ignore[arg-type]
                metadatas=metadatas,  # type: ignore[arg-type]
                documents=chunks,
            )

        await asyncio.to_thread(_store)
        _set_cached(state_cache, rel, st, _STATE_INDEXED)
        return len(chunks), None, True

    async def _extract_chunks(self, fp: Path, size: int, splitter: Any) -> list[str]:
        """Convert *fp* to text and chunk it, dispatching by extension.

        Raises :class:`_SkipFile` for deterministic skips (too large,
        unsupported type); any other exception propagates to the caller
        (recorded as ``conversion_error`` there).
        """
        if size > self._settings.max_file_mb * 1024 * 1024:
            raise _SkipFile("too_large")
        ext = fp.suffix.lower()
        if ext in TEXT_EXTENSIONS:
            text = fp.read_text(encoding="utf-8", errors="ignore")
            return splitter.split_text(text)
        if ext in OFFICE_EXTENSIONS or ext in _HTML_EXTENSIONS:
            text = await self._markitdown(fp)
            return splitter.split_text(text)
        if ext in _PDF_EXTENSIONS:
            return await self._pdf_chunks(fp)
        raise _SkipFile("unsupported_type")

    async def _markitdown(self, fp: Path) -> str:
        """Raw markdown via MarkItDown directly (not the _convert_markitdown helper)."""
        from markitdown import MarkItDown

        return MarkItDown().convert(str(fp)).text_content or ""

    async def _pdf_chunks(self, fp: Path) -> list[str]:
        """Structure-aware chunks via the docling worker's --chunks flag.

        Falls back to MarkItDown + SentenceSplitter if the docling worker
        isn't installed.
        """
        from aria.config.folders import Bin
        from aria.config.pdf import Pdf

        shim = Bin.path / "docling"
        if not shim.exists():
            logger.info(
                "knowledge hub: docling worker not installed; "
                "falling back to markitdown for PDF"
            )
            from llama_index.core.node_parser import SentenceSplitter

            md = await self._markitdown(fp)
            return SentenceSplitter(
                chunk_size=self._settings.chunk_size,
                chunk_overlap=self._settings.chunk_overlap,
            ).split_text(md)
        from aria.tools.documents._subprocess import convert as vlm_convert

        fd, tmp_name = tempfile.mkstemp(suffix=".json")
        out = Path(tmp_name)
        try:
            os.close(fd)
            device = Pdf.vlm_device
            if device == "auto":
                from aria.scripts.docling import detect_device

                device = detect_device()
            res = vlm_convert(
                fp,
                output_path=out,
                model_id=Pdf.vlm_model_id,
                device=device,
                max_pages=Pdf.vlm_max_pages,
                timeout=Pdf.vlm_timeout_seconds,
                chunks=True,
            )
            if not res.get("ok"):
                raise RuntimeError(res.get("error", "docling --chunks failed"))
            items = json.loads(out.read_text(encoding="utf-8"))
            return [it["text"] for it in items]
        finally:
            out.unlink(missing_ok=True)

    async def query(self, q: str, top_k: int) -> list[dict[str, Any]]:
        """Retrieve the top-k chunks for *q* from the shared collection.

        Read-only — no index lock needed (a ``force`` reindex drops and
        recreates the collection, but a query racing it returns empty or
        stale results, never corrupts state).
        """
        from aria.web.state import _state

        if _state.embeddings is None or _state.vector_db is None:
            return []
        emb = await _state.embeddings.aget_text_embedding(q)

        def _query_chroma() -> dict[str, Any]:
            return _state.vector_db.get_or_create_collection(_COLLECTION).query(  # type: ignore[union-attr]
                query_embeddings=[emb], n_results=top_k
            )

        res = await asyncio.to_thread(_query_chroma)
        results = res or {}
        docs: list[str] = (results.get("documents") or [[]])[0]
        metas: list[dict[str, Any]] = (results.get("metadatas") or [[]])[0]  # type: ignore[assignment]
        dists: list[float] = (results.get("distances") or [[]])[0]
        return [
            {"text": d, "source": m.get("source"), "distance": dist}
            for d, m, dist in zip(docs, metas, dists)
        ]


def _merge_small(chunks: list[str], target_chars: int) -> list[str]:
    """Greedily merge adjacent chunks up to ~*target_chars* characters.

    *target_chars* is a **character** budget, not a token count — the
    SentenceSplitter already applies the token-based ``chunk_size`` for
    text/office paths; this merge only combines the small structure
    chunks produced by docling's HierarchicalChunker (one paragraph or
    list item each) so each embedded unit carries enough context.
    Oversize chunks are kept as-is.
    """
    out: list[str] = []
    buf = ""
    for c in chunks:
        if buf and len(buf) + len(c) > target_chars:
            out.append(buf)
            buf = c
        else:
            buf = f"{buf}\n{c}" if buf else c
    if buf:
        out.append(buf)
    return out


# --- index-state persistence ----------------------------------------------
class _FileState:
    """In-memory snapshot of one file's index state."""

    __slots__ = ("mtime", "size", "state", "skip_reason")

    def __init__(
        self, mtime: float, size: int, state: str, skip_reason: str | None
    ) -> None:
        self.mtime = mtime
        self.size = size
        self.state = state
        self.skip_reason = skip_reason


def _session():
    """Shared tools-DB session (context manager)."""
    from aria.tools.database import get_tools_database

    return get_tools_database().get_session()


def _load_state_cache() -> dict[str, _FileState]:
    """Load all index-state rows into a {path: _FileState} dict in one query."""
    cache: dict[str, _FileState] = {}
    with _session() as session:
        rows = session.execute(
            select(
                KnowledgeIndexStateModel.path,
                KnowledgeIndexStateModel.mtime,
                KnowledgeIndexStateModel.size,
                KnowledgeIndexStateModel.state,
                KnowledgeIndexStateModel.skip_reason,
            )
        ).all()
    for path, mtime, size, state, skip_reason in rows:
        cache[path] = _FileState(mtime, size, state, skip_reason)
    return cache


def _is_cached(cache: dict[str, _FileState], rel: str, st: Any) -> bool:
    """True if *rel* was already processed and its mtime/size are unchanged."""
    row = cache.get(rel)
    return row is not None and row.mtime == st.st_mtime and row.size == st.st_size


def _set_cached(
    cache: dict[str, _FileState],
    rel: str,
    st: Any,
    state: str,
    skip_reason: str | None = None,
) -> None:
    """Update the in-memory cache for *rel* (flushed once at end of run)."""
    cache[rel] = _FileState(st.st_mtime, st.st_size, state, skip_reason)


def _flush_state_cache(cache: dict[str, _FileState]) -> None:
    """Persist the mutated state cache to the DB in one session."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    with _session() as session:
        existing = {
            row.path: row
            for row in session.execute(select(KnowledgeIndexStateModel)).scalars().all()
        }
        for path, fs in cache.items():
            if path in existing:
                row = existing[path]
                row.mtime = fs.mtime
                row.size = fs.size
                row.state = fs.state
                row.skip_reason = fs.skip_reason
                row.indexed_at = now
            else:
                session.add(
                    KnowledgeIndexStateModel(
                        path=path,
                        mtime=fs.mtime,
                        size=fs.size,
                        state=fs.state,
                        skip_reason=fs.skip_reason,
                        indexed_at=now,
                    )
                )
        session.commit()


def _clear_index_state() -> None:
    with _session() as session:
        session.execute(sa_delete(KnowledgeIndexStateModel))
        session.commit()


def _purge_removed(collection: Any, walked: set[str]) -> None:
    """Delete collection chunks and state rows for files no longer on disk.

    Only ``indexed`` rows have chunks in Chroma; ``skipped`` rows just
    need their state row removed. Selects only path+state columns.
    """
    with _session() as session:
        rows = session.execute(
            select(KnowledgeIndexStateModel.path, KnowledgeIndexStateModel.state)
        ).all()
    removed = [(path, state) for path, state in rows if path not in walked]
    for path, state in removed:
        if state == _STATE_INDEXED:
            collection.delete(where={"source": path})
    if removed:
        with _session() as session:
            session.execute(
                sa_delete(KnowledgeIndexStateModel).where(
                    KnowledgeIndexStateModel.path.in_([p for p, _ in removed])
                )
            )
            session.commit()
