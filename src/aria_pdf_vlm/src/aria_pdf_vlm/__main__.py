"""aria-pdf-vlm worker CLI.

Invoked as ``pdf-vlm convert ...`` / ``pdf-vlm probe`` from the main Aria
env via the ~/.aria/bin/pdf-vlm shim. Emits one JSON object on stdout.
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
    fmt = FormatOption(
        pipeline_options=opts,
        backend=PyPdfiumDocumentBackend,
        pipeline_cls=VlmPipeline,
    )
    return DocumentConverter(format_options={InputFormat.PDF: fmt})


def _page_count(pdf: Path) -> int:
    import pypdfium2

    doc = pypdfium2.PdfDocument(str(pdf))
    n = len(doc)
    doc.close()
    return n


def _emit(result: dict[str, Any]) -> int:
    """Print a JSON result and return its exit code (1 when not ok)."""
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


def cmd_convert(args: argparse.Namespace) -> int:
    pdf = Path(args.input)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    # Force CPU before torch import when device=="cpu" — must be set
    # before docling/torch is imported inside _build_converter.
    if args.device == "cpu":
        import os

        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    try:
        n = _page_count(pdf)
        if args.max_pages and n > args.max_pages:
            return _emit(
                {
                    "ok": False,
                    "error": f"page count {n} exceeds max_pages {args.max_pages}",
                }
            )
        conv = _build_converter(args.device)
        result = conv.convert(pdf)
        md = result.document.export_to_markdown()
        dur_ms = int((time.time() - t0) * 1000)
        provenance = (
            f"<!-- converted by Granite-Docling (model={args.model}, "
            f"device={args.device}, pages={n}, duration_ms={dur_ms}) -->\n"
        )
        out.write_text(provenance + md, encoding="utf-8")
        return _emit(
            {
                "ok": True,
                "markdown_path": str(out),
                "pages": n,
                "duration_ms": dur_ms,
                "model": args.model,
                "device": args.device,
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
    p = argparse.ArgumentParser(prog="pdf-vlm")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert")
    c.add_argument("--input", required=True)
    c.add_argument("--output", required=True)
    c.add_argument("--model", required=True)
    c.add_argument("--device", default="cpu")
    c.add_argument("--max-pages", type=int, default=0)
    pr = sub.add_parser("probe")
    pr.add_argument("--device", default="cpu")
    args = p.parse_args()
    if args.cmd == "convert":
        return cmd_convert(args)
    return cmd_probe(args)


if __name__ == "__main__":
    sys.exit(main())
