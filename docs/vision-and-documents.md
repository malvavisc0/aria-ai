# Vision & Document Upload Processing

How Aria handles images and documents uploaded through the chat UI.

## Overview

When a user attaches files to a chat message, Aria processes them in a
pre-processing step **before** the agent sees the prompt. The goal is to
make uploads usable by the agent without bloating the prompt or blocking
the turn on heavy work.

There are three upload types:

| Upload type | At upload time | Agent access |
|---|---|---|
| **Images** (png, jpg, webp, gif, bmp, tiff) | Vision API → text description | `[Image 1 (photo.jpg)]: A red car on a highway…` |
| **Documents** (pdf, docx, xlsx, pptx, csv, html) | Persisted raw (no conversion) | path listed in prompt → `ax documents convert` on demand |
| **Text/code files** (txt, md, json, xml, yaml, toml, py, js, ts, sh, log, ini, cfg, rst) | Persisted raw (no conversion) | read directly with `read_file` |

Raw uploads of **all** types persist to `~/.aria/workspace/uploads/` and
their paths are listed in an `[Uploaded files]` block. **No document is
converted at upload time** — conversion happens only when the agent calls
`ax documents convert`. This keeps uploads instant even for huge files
and leaves the agent in control of *when* and *whether* to convert.

## Architecture

```
User uploads files in Chainlit UI
         │
         ▼
┌─────────────────────────────────┐
│  message_pipeline._handle_message()
│                                 │
│  1. extract_file_paths(msg)     │ ← Non-image files → copy to ~/.aria/workspace/uploads/
│  2. extract_image_data(msg)     │ ← Images → base64 encoded
│  3. _describe_image() per image │ ← Vision API call
│  4. Assemble prompt with metadata│
└─────────────┬───────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│  AgentWorkflow.run(prompt)      │ ← Text-only, unchanged
│  (raw upload paths listed,      │
│   convert on demand via         │
│   ax documents convert)         │
└─────────────────────────────────┘
```

## Image Processing (Vision)

### How it works

1. `extract_image_data()` in `session.py` detects image elements by MIME
   type or file extension, reads them, and returns base64-encoded data.

2. For each image, `_describe_image()` in `message_pipeline.py` sends a
   request to the vLLM chat completions endpoint with the image as a
   `data:` URL. The prompt asks for a concise 2–3 sentence description.

3. The description text is injected into the user prompt:
   ```
   [Attached images]:
   [Image 1 (chart.png)]: A bar chart showing quarterly revenue growth…
   [Image 2 (photo.jpg)]: A group photo in front of a building…
   ```

### Why text descriptions, not multimodal passthrough

Passing raw images through the agent pipeline would break:
- **Memory** — images can't be embedded or fact-extracted
- **Context compression** — base64 blobs are incompressible
- **Token counting** — `len(str(content)) // 4` would massively undercount
- **Session restore** — images aren't persisted in the database

Text descriptions (~200–500 tokens each) flow through all these systems
unchanged.

### Configuration

Set the environment variable to enable vision:

```bash
ARIA_VLLM_VISION_ENABLED=true
```

When disabled, images are still detected but the prompt shows:
```
[Image 1 (photo.jpg)]: <vision disabled — enable ARIA_VLLM_VISION_ENABLED>
```

The model must support vision (e.g., Qwen-VL, LLaVA). If the vision API
call fails (timeout, model error), the prompt falls back to
`<description unavailable>` and the user's text message still goes through.

### Token budget

| Item | Tokens |
|---|---|
| Vision API call (per image) | ~300–2000 input, ~100–256 output |
| Description stored in prompt | ~100–256 per image |
| Max 5 images worst case | ~1,280 tokens total |

Fits comfortably in both 32K and 256K context windows.

## Document Processing (on-demand)

Documents of any type are **not** converted at upload time. The upload
handler persists the raw file into `~/.aria/workspace/uploads/` and the
prompt lists its path. Conversion happens only when the agent calls the
`ax documents convert` tool — there is exactly one conversion path.

### How it works

1. `extract_file_paths()` in `session.py` copies non-image uploads to
   `~/.aria/workspace/uploads/` with unique filenames (thread ID + UUID).

2. The prompt lists the raw paths and tells the agent how to access them:
   ```
   [Uploaded files] (raw paths — use `read_file` directly for text/code
   files, `ax documents convert` for office/HTML/PDF):
   - /path/t1_abc123_report.pdf
   ```

3. When the agent decides it needs a document, it calls
   `ax documents convert` with the absolute path. Routing is decided by
   file extension:
   - **Already-text** (`.txt`, `.md`, `.json`, `.csv`, `.py`, …) → refused;
     the agent reads them directly with `read_file`.
   - **Office/HTML** (`.docx`, `.xlsx`, `.pptx`, `.html`, …) → MarkItDown
     (in-process).
   - **PDF** → Granite-Docling (isolated worker) when installed, else
     MarkItDown. Homegrown Granite-Docling handles digital and scanned
     PDFs uniformly and preserves structure (tables, lists, headings,
     reading order).

4. The converted `.md` is written to `~/.aria/workspace/uploads/<stem>.md`
   (next to the raw upload) and the tool returns the path + metadata —
   never the content:
   ```
   {"file_path": ".../workspace/uploads/report.md",
    "metadata": {"pages": 42, "backend_used": "granite-docling", ...}}
   ```

5. The agent then reads the `.md` in chunks with `read_file`
   (`offset` / `length` / `max_lines`), searches within it, or answers
   questions about its content.

### Why on-demand, not upload-time conversion

- **Huge documents** — a 200-page PDF converted at upload would block the
  turn even if the agent never reads it. On-demand conversion lets the
  agent decide *when* and *whether*.
- **One conversion path** — every document converts through the same
  tool; there is no separate upload-time route to drift from it.

### Granite-Docling worker

Granite-Docling (`ibm-granite/granite-docling-258M`) runs **locally**
(no external OCR API) and is **PDF-only**. Because it pulls in the same
heavy stack as vLLM (`torch`, `transformers`, `docling`), it is installed
into an **isolated venv** at `~/.aria/venvs/docling/` and invoked as a
subprocess — Aria's own dependency tree never imports it.

Install:

```bash
uv run aria docling install
```

This auto-pulls CUDA torch when an NVIDIA GPU is detected, else CPU
torch. Check the worker state with either of:

```bash
uv run aria docling status
# or, agent-side:
ax documents status
```

The worker is optional. If it is not installed, `ax documents convert`
falls back to MarkItDown for PDFs (`auto` backend) — a quality
downgrade, not a functional failure.

### Supported formats

The tool converts office/HTML/PDF via MarkItDown and Granite-Docling.
Already-text formats (`.txt`, `.md`, `.rst`, `.json`, `.csv`, `.xml`,
`.yaml`/`.yml`, `.toml`, `.log`, `.ini`, `.cfg`, `.py`, `.js`, `.ts`,
`.sh`) are refused — use `read_file` directly.

### Error handling

`ax documents convert` returns a structured error for missing files,
unsupported extensions, oversized files, or failed conversion. The agent
reads the error and adapts (e.g. falls back, or reports the failure).

## File locations

| Directory | Purpose |
|---|---|
| `~/.aria/workspace/uploads/` | Raw uploads and converted markdown (agent-accessible) |
| `~/.aria/venvs/docling/` | Isolated Granite-Docling worker venv |
| `~/.aria/bin/docling` | Worker shim (symlink to the venv console-script) |

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `ARIA_PDF_BACKEND` | `auto` | `auto` / `granite-docling` / `markitdown` |
| `ARIA_DOCLING_MODEL` | `ibm-granite/granite-docling-258M` | Model ID |
| `ARIA_DOCLING_DEVICE` | `auto` | `auto` → `cuda` if NVIDIA else `cpu`; override with `cpu`/`cuda`/`mps` |
| `ARIA_DOCLING_MAX_PAGES` | `200` | Max pages per PDF |
| `ARIA_DOCLING_TIMEOUT_SECONDS` | `600` | Subprocess timeout |
| `ARIA_PDF_MAX_FILE_MB` | `100` | Max input file size |
| `ARIA_DOCLING_VENV` | — | Override the isolated venv path |
| `ARIA_DOCLING_MODEL_PATH` | — | Local model snapshot dir |

Model snapshot: `~/.aria/models/<model-name>/` when
`ARIA_DOCLING_MODEL_PATH` is set or pre-downloaded via
`aria models download`; otherwise docling downloads to the HF cache
(`~/.cache/huggingface/`) on first PDF conversion.

## Source files

| File | Responsibility |
|---|---|
| `src/aria/web/session.py` | `extract_image_data()`, `extract_file_paths()` |
| `src/aria/web/message_pipeline.py` | `_describe_image()`, `_handle_message()` prompt assembly |
| `src/aria/config/pdf.py` | `Pdf`, `DoclingVenv` configuration |
| `src/aria/scripts/docling.py` | Worker install/detect/uninstall |
| `src/worker/` | Isolated Granite-Docling worker package |
| `src/aria/tools/documents/` | `ax documents` tool family (`convert`, `status`) |
| `src/aria/config/api.py` | `Vllm.vision_enabled` configuration |
| `src/aria/.chainlit/config.toml` | File upload UI settings (`spontaneous_file_upload`) |
