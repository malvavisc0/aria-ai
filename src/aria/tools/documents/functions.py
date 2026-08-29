"""`ax documents` family — on-demand document → markdown conversion.

Routing:
    already-text (.txt/.md/.json/...)  → refuse, point to read_file
    office (.docx/.xlsx/...) + html    → MarkItDown, always
    pdf                               → Granite-Docling (isolated venv)
                                        when available, else MarkItDown
    image (.png/.jpg/...)             → Granite-Docling OCR (`extract`)

Output is persisted to ~/.aria/workspace/uploads/<stem>.md and the agent
reads it via `read_file` in chunks — never returned inline.
"""

import asyncio
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from aria.config.folders import Workspace
from aria.config.pdf import Pdf
from aria.tools import Reason, tool_response
from aria.tools.decorators import log_tool_call

from ._internals import resolve_doc_path

_TOOL = "documents"

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".rst",
    ".json",
    ".csv",
    ".xml",
    ".yaml",
    ".yml",
    ".toml",
    ".log",
    ".ini",
    ".cfg",
    ".py",
    ".js",
    ".ts",
    ".sh",
}
OFFICE_EXTENSIONS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}
_HTML_EXTENSIONS = {".html", ".htm"}
_PDF_EXTENSIONS = {".pdf"}
# Docling's IMAGE format: jpg, jpeg, png, tif, tiff, bmp, webp (no gif).
# Public: the web layer derives its image-detection set from this so the
# two never drift.
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def _ok(reason: str, data: dict[str, Any]) -> str:
    return tool_response(tool=_TOOL, reason=reason, data=data)


def _err(
    reason: str,
    code: str,
    message: str,
    recoverable: bool = True,
    how_to_fix: str | None = None,
) -> str:
    err: dict[str, Any] = {"code": code, "message": message, "recoverable": recoverable}
    if how_to_fix:
        err["how_to_fix"] = how_to_fix
    return tool_response(tool=_TOOL, reason=reason, data={"error": err})


def _output_dir() -> Path:
    d = Workspace.path / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _unique_path(stem: str, ext: str = ".md") -> Path:
    dest = _output_dir() / f"{stem}{ext}"
    if dest.exists():
        dest = _output_dir() / f"{stem}_{uuid.uuid4().hex[:8]}{ext}"
    return dest


def _convert_markitdown(fp: Path, reason: str, *, note: str | None = None) -> str:
    """In-process MarkItDown conversion → persisted .md; returns _ok/_err."""
    try:
        from markitdown import MarkItDown

        md = MarkItDown().convert(str(fp)).text_content or ""
        dest = _unique_path(fp.stem)
        dest.write_text(md, encoding="utf-8")
        lines = len(md.splitlines())
        meta: dict[str, Any] = {
            "lines": lines,
            "chars": len(md),
            "backend_used": "markitdown",
        }
        if note:
            meta["note"] = note
        return _ok(reason, {"file_path": str(dest), "metadata": meta})
    except Exception as exc:
        return _err(reason, "markitdown_failed", str(exc))


def _worker_shim() -> Path:
    from aria.config.folders import Bin

    return Bin.path / "docling"


def _docling_device() -> str:
    """Resolve the docling device (auto → cuda|cpu)."""
    device = Pdf.vlm_device
    if device == "auto":
        from aria.scripts.docling import detect_device

        device = detect_device()
    return device


def _warn_if_model_uncached() -> None:
    """Warn when the model isn't cached — the conversion may trigger a
    multi-hundred-MB download inside the subprocess timeout."""
    from aria.config.models import _resolve_model_path

    model_path = Pdf.model_path or _resolve_model_path(Pdf.vlm_model_id)
    if not Path(model_path).is_dir():
        logger.warning(
            "aria.tools.documents: model snapshot not found at "
            f"{model_path}; conversion may download it. "
            "Run: uv run aria docling download"
        )


def _convert_docling(
    paths: Path | list[Path],
    reason: str,
    *,
    explicit: bool,
    max_pages: int | None = None,
) -> str:
    """Granite-Docling via isolated subprocess. See _subprocess.convert.

    Accepts one path or a batch (one worker invocation, one model load).
    With ``explicit=False`` (auto backend), failures fall back to
    MarkItDown; ``explicit=True`` hard-fails.
    """
    from aria.tools.documents._subprocess import convert as vlm_convert

    batch = [paths] if isinstance(paths, Path) else list(paths)
    shim = _worker_shim()
    if not shim.exists():
        if explicit:
            return _err(
                reason,
                "worker_not_installed",
                "ARIA_PDF_BACKEND=granite-docling but docling worker not "
                "installed (run: uv run aria docling install)",
                how_to_fix="Run: uv run aria docling install",
            )
        logger.info(
            "aria.tools.documents: docling worker not installed; falling back to "
            "markitdown. Install with: uv run aria docling install"
        )
        return _convert_markitdown(batch[0], reason)
    _warn_if_model_uncached()
    dest = _unique_path(batch[0].stem)
    pages = max_pages if max_pages is not None else Pdf.vlm_max_pages
    res = vlm_convert(
        batch,
        output_path=dest,
        model_id=Pdf.vlm_model_id,
        device=_docling_device(),
        max_pages=pages,
        timeout=Pdf.vlm_timeout_seconds,
    )
    if not res.get("ok"):
        if not explicit:
            logger.info(
                f"VLM conversion failed ({res.get('error')}); "
                "falling back to markitdown"
            )
            return _convert_markitdown(
                batch[0],
                reason,
                note="VLM failed; max_pages not honored by markitdown fallback",
            )
        return _err(reason, "vlm_failed", res.get("error", "unknown"))
    meta: dict[str, Any] = {
        "pages": res.get("pages"),
        "backend_used": "granite-docling",
        "device": res.get("device"),
        "duration_ms": res.get("duration_ms"),
        "model": res.get("model"),
    }
    if res.get("files"):
        meta["files"] = res["files"]
    return _ok(reason, {"file_path": str(dest), "metadata": meta})


def _status_data() -> dict[str, Any]:
    """Query worker state — runs in a thread from :func:`status`."""
    from aria.config.folders import Bin
    from aria.config.models import _resolve_model_path
    from aria.config.pdf import DoclingVenv
    from aria.scripts.docling import detect_device, is_installed

    installed = is_installed()
    device = Pdf.vlm_device
    if device == "auto":
        device = detect_device()
    model_path = Pdf.model_path or _resolve_model_path(Pdf.vlm_model_id)
    model_cached = bool(model_path) and Path(model_path).is_dir()
    return {
        "installed": installed,
        "model_cached": model_cached,
        "model_path": model_path or "(docling default HF cache)",
        "device": device,
        "venv": str(DoclingVenv.get_venv_path()),
        "shim": str(Bin.path / "docling"),
    }


@log_tool_call
async def convert(
    reason: Reason,
    action: str,
    file_name: str,
    backend: str | None = None,
    max_pages: int | None = None,
) -> str:
    """Convert a document to a persisted markdown file.

    Routing: already-text → refuse (use read_file); office/HTML →
    MarkItDown; PDF → Granite-Docling when available, else MarkItDown.
    ``backend`` only affects PDF routing.

    Args:
        reason: Why you are converting this document.
        action: Injected by the ax dispatcher ("convert").
        file_name: Absolute path to the document (same convention as read_file).
        backend: auto|granite-docling|markitdown. Defaults to ARIA_PDF_BACKEND.
        max_pages: Override ARIA_DOCLING_MAX_PAGES for this PDF.

    Returns:
        JSON with {file_path, metadata}. Content is persisted to disk —
        read it with read_file (offset/length/max_lines).
    """
    try:
        fp = resolve_doc_path(file_name)
    except Exception as exc:
        return _err(reason, "path_error", str(exc))

    ext = fp.suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return _err(
            reason,
            "already_text",
            f"{fp.name} is already a text file; use read_file directly",
            how_to_fix="Call read_file with this path directly.",
        )
    if fp.stat().st_size > Pdf.max_file_mb * 1024 * 1024:
        return _err(reason, "too_large", f"exceeds {Pdf.max_file_mb} MB limit")
    if ext in OFFICE_EXTENSIONS or ext in _HTML_EXTENSIONS:
        return await asyncio.to_thread(_convert_markitdown, fp, reason)
    if ext in _PDF_EXTENSIONS:
        be = (backend or Pdf.backend).lower()
        if be not in ("auto", "granite-docling", "markitdown"):
            return _err(reason, "invalid_backend", f"unknown backend: {be}")
        if be == "markitdown":
            return await asyncio.to_thread(_convert_markitdown, fp, reason)
        return await asyncio.to_thread(
            _convert_docling,
            fp,
            reason,
            explicit=(be == "granite-docling"),
            max_pages=max_pages,
        )
    return _err(reason, "unsupported", f"unsupported extension: {ext}")


@log_tool_call
async def extract(reason: Reason, action: str, file_name: str | list[str]) -> str:
    """Extract text from image(s) via OCR, persisted to a markdown file.

    Images (png/jpg/jpeg/webp/bmp/tif/tiff) are OCR'd by Granite-Docling.
    Pass a single path or a list — a batch is converted in one worker
    invocation (one model load) into one markdown file. PDFs and scanned
    documents use ``convert`` — same OCR engine. No MarkItDown fallback:
    it cannot OCR images, so a missing worker is a hard error.

    Args:
        reason: Why you are extracting text from this image.
        action: Injected by the ax dispatcher ("extract").
        file_name: Absolute path (or list of paths) to the image(s).

    Returns:
        JSON with {file_path, metadata}. Content is persisted to disk —
        read it with read_file (offset/length/max_lines).
    """
    names = [file_name] if isinstance(file_name, str) else list(file_name)
    if not names:
        return _err(reason, "missing_file", "file_name is required")
    batch: list[Path] = []
    for name in names:
        try:
            fp = resolve_doc_path(name)
        except Exception as exc:
            return _err(reason, "path_error", str(exc))
        ext = fp.suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            return _err(
                reason,
                "not_an_image",
                f"unsupported image extension: {ext}",
                how_to_fix=(
                    f"extract OCRs {', '.join(sorted(IMAGE_EXTENSIONS))}. "
                    ".gif has no OCR path — use the vision summary. "
                    "For PDF/office/HTML use convert."
                ),
            )
        if fp.stat().st_size > Pdf.max_file_mb * 1024 * 1024:
            return _err(
                reason, "too_large", f"{fp.name} exceeds {Pdf.max_file_mb} MB limit"
            )
        batch.append(fp)
    return await asyncio.to_thread(_convert_docling, batch, reason, explicit=True)


@log_tool_call
async def status(reason: Reason, action: str) -> str:
    """Report the Granite-Docling worker state.

    Returns: installed (bool, cheap FS check), model_cached (bool, FS
    snapshot check — no torch load), device (resolved auto→cuda|cpu),
    venv + shim paths.
    """
    data = await asyncio.to_thread(_status_data)
    return _ok(reason, data)
