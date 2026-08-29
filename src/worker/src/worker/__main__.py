"""Docling worker CLI.

Invoked as ``docling convert ...`` / ``docling probe`` from the main Aria
env via the ~/.aria/bin/docling shim. Emits one JSON object on stdout.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def _build_converter(device: str) -> Any:
    """Build a docling ``DocumentConverter`` with the Granite-Docling VLM.

    Imports docling lazily — this module is never imported by Aria's main
    env; only the isolated worker venv has docling installed.
    """
    from docling.backend.image_backend import ImageDocumentBackend
    from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        AcceleratorDevice,
        AcceleratorOptions,
        VlmPipelineOptions,
    )
    from docling.datamodel.vlm_model_specs import GRANITEDOCLING_TRANSFORMERS
    from docling.document_converter import DocumentConverter, FormatOption
    from docling.pipeline.vlm_pipeline import VlmPipeline

    opts = VlmPipelineOptions(
        do_picture_classification=False,
        do_picture_description=False,
        do_table_structure=False,
        generate_page_images=False,
        accelerator_options=AcceleratorOptions(device=AcceleratorDevice(device)),
        vlm_options=GRANITEDOCLING_TRANSFORMERS,
    )
    pdf_fmt = FormatOption(
        pipeline_options=opts,
        backend=PyPdfiumDocumentBackend,
        pipeline_cls=VlmPipeline,
    )
    image_fmt = FormatOption(
        pipeline_options=opts,
        backend=ImageDocumentBackend,
        pipeline_cls=VlmPipeline,
    )
    return DocumentConverter(
        format_options={InputFormat.PDF: pdf_fmt, InputFormat.IMAGE: image_fmt}
    )


def _page_count(pdf: Path) -> int:
    import pypdfium2

    doc = pypdfium2.PdfDocument(str(pdf))
    n = len(doc)
    doc.close()
    return n


def _page_count_safe(path: Path) -> int:
    """Page count for any input: PDF pages, image frames, else 1.

    Images report their frame count (a multi-page TIFF is multi-page);
    anything the backend treats as a single page counts as 1.
    """
    if path.suffix.lower() == ".pdf":
        return _page_count(path)
    from PIL import Image

    with Image.open(path) as img:
        return getattr(img, "n_frames", 1)


def _emit(result: dict[str, Any]) -> int:
    """Print a JSON result and return its exit code (1 when not ok)."""
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


def _page_counts(srcs: list[Path], max_pages: int) -> list[int] | dict[str, Any]:
    """Per-file page counts, enforcing the ``max_pages`` cap.

    Returns a list of counts, or an error result dict when any file
    exceeds the cap.
    """
    counts = []
    for src in srcs:
        n = _page_count_safe(src)
        if max_pages and n > max_pages:
            return {
                "ok": False,
                "error": f"page count {n} exceeds max_pages {max_pages} ({src.name})",
            }
        counts.append(n)
    return counts


def _write_chunks(documents: list[Any], out: Path) -> dict[str, Any]:
    """Emit a JSON chunk array via HierarchicalChunker."""
    from docling_core.transforms.chunker.hierarchical_chunker import (
        HierarchicalChunker,
    )

    chunker = HierarchicalChunker()
    items = [
        {"text": c.text, "headings": c.meta.headings or []}
        for document in documents
        for c in chunker.chunk(document)
    ]
    out.write_text(json.dumps(items), encoding="utf-8")
    return {"chunks": len(items)}


def _write_markdown(
    srcs: list[Path],
    documents: list[Any],
    counts: list[int],
    out: Path,
) -> dict[str, Any]:
    """Emit markdown — per-file section comments when batching."""
    parts = [
        f"<!-- {src.name} -->\n{document.export_to_markdown()}"
        if len(srcs) > 1
        else document.export_to_markdown()
        for src, document in zip(srcs, documents)
    ]
    out.write_text("\n\n".join(parts), encoding="utf-8")
    return {
        "markdown_path": str(out),
        "files": [{"name": src.name, "pages": n} for src, n in zip(srcs, counts)],
    }


def cmd_convert(args: argparse.Namespace) -> int:
    srcs = [Path(p) for p in args.input]
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    # Force CPU before torch import when device=="cpu" — must be set
    # before docling/torch is imported inside _build_converter.
    if args.device == "cpu":
        import os

        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    try:
        counted = _page_counts(srcs, args.max_pages)
        if isinstance(counted, dict):
            return _emit(counted)
        counts = counted
        conv = _build_converter(args.device)
        # One converter (one model load) for all inputs — the reason
        # batching exists.
        documents = [conv.convert(src).document for src in srcs]
        dur_ms = int((time.time() - t0) * 1000)
        if args.chunks:
            result = _write_chunks(documents, out)
        else:
            result = _write_markdown(srcs, documents, counts, out)
        return _emit(
            {
                "ok": True,
                "pages": sum(counts),
                "duration_ms": dur_ms,
                "model": args.model,
                "device": args.device,
                **result,
            }
        )
    except Exception as exc:  # surface to the main env as JSON
        return _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def cmd_probe(args: argparse.Namespace) -> int:
    try:
        import docling  # noqa: F401

        return _emit({"ok": True, "venv": "healthy", "device_hint": args.device})
    except Exception as exc:
        return _emit({"ok": False, "error": str(exc)})


def main() -> int:
    p = argparse.ArgumentParser(prog="docling")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output", required=True)
    c.add_argument("--model", required=True)
    c.add_argument("--device", default="cpu")
    c.add_argument("--max-pages", type=int, default=0)
    c.add_argument(
        "--chunks",
        action="store_true",
        help="emit JSON chunks via HierarchicalChunker instead of markdown",
    )
    pr = sub.add_parser("probe")
    pr.add_argument("--device", default="cpu")
    args = p.parse_args()
    if args.cmd == "convert":
        return cmd_convert(args)
    return cmd_probe(args)


if __name__ == "__main__":
    sys.exit(main())
