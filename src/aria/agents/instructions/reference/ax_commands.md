# `ax` Command Reference

Call `ax` with four top-level JSON fields: `reason` (string), `family` (string), `command` (string), and `args` (a **JSON object**, not a string). Pass function-specific parameters as keys inside `args` — never as top-level fields, and never as a stringified/escaped copy of an object.

**Correct** — `args` is a real nested object, even when its values are large or contain quotes/newlines:
```json
{
  "reason": "Run a Python script that sends a test email",
  "family": "dev",
  "command": "run",
  "args": {
    "code": "import smtplib\nprint('hello')",
    "check_only": false
  }
}
```

**Incorrect** — do not encode `args` as a JSON string (the dispatcher spreads `args` into the target function's parameters, so a string value fails):
```json
{"reason": "...", "family": "dev", "command": "run", "args": "{\"code\": \"...\", \"check_only\": false}"}
```

`reason` is a **required top-level field** — pass it at the top level, never inside `args`. If you omit it, the call fails with `missing_reason`. `action` is injected automatically from `command` (do not pass it).

## web

| Command | Required | Optional |
|---------|----------|----------|
| `search` | `query` | `max_results` |
| `fetch` | `url` | `output`, `convert_to_markdown`, `custom_headers`, `max_size` |
| `visit` | `url` | — |
| `click` | `selector` | — |
| `close` | — | — |
| `weather` | `location` | — |
| `youtube` | `url` | `languages` |

> **Flow:** `search` → `fetch` (static pages, binary downloads) or `visit` (JS-heavy HTML pages). If a search returns nothing, simplify the query and drop temporal terms; never retry the same pattern more than twice. `weather` for weather, `youtube` for transcripts, `http request` for custom API calls.

## memory

| Command | Required | Optional |
|---------|----------|----------|
| `store` | `key`, `value` | `tags` |
| `recall` | `key` | — |
| `search` | `query` | `max_results` |
| `list` | — | `tags`, `max_results` |
| `update` | `entry_id`, `value` | — |
| `delete` | `entry_id` | — |

## knowledge

| Command | Required | Optional |
|---------|----------|----------|
| `status` | — | — |
| `reindex` | — | `force` |

## finance

| Command | Required | Optional |
|---------|----------|----------|
| `stock` | `ticker` | — |
| `company` | `ticker` | — |
| `news` | `ticker` | `max_articles` |

## imdb

| Command | Required | Optional |
|---------|----------|----------|
| `search` | `query` | `title_type` |
| `movie` | `imdb_id` | — |
| `person` | `person_id` | — |
| `filmography` | `person_id` | — |
| `episodes` | `imdb_id` | — |
| `reviews` | `imdb_id` | — |
| `trivia` | `imdb_id` | — |

## http

| Command | Required | Optional |
|---------|----------|----------|
| `request` | `method`, `url` | `headers`, `body`, `timeout` |

## dev

| Command | Required | Optional |
|---------|----------|----------|
| `run` | `code` (or `file`) | `args`, `timeout`, `check_only` |

> **Prefer over `shell` for computation** — parsing JSON/XML/CSV, calculations, data transformations. Not for CLI tools, file I/O, or long-running processes.

## processes

| Command | Required | Optional |
|---------|----------|----------|
| `start` | `name`, `command` | `args`, `timeout`, `working_dir`, `env`, `use_shell` |
| `stop` | `name` | — |
| `status` | `name` | — |
| `logs` | `name` | — |
| `list` | — | — |
| `restart` | `name` | `timeout`, `working_dir`, `env`, `use_shell` |
| `signal` | `name`, `signal_name` | — |

## documents

| Command | Required | Optional |
|---------|----------|----------|
| `convert` | `file_name` | `backend`, `max_pages` |
| `extract` | `file_name` | — |
| `status` | — | — |

> **Convert office/HTML/PDF to markdown with `ax documents convert`** (`file_name` = absolute path). Output is persisted to a `.md` file — read it with `read_file` in chunks afterwards. Already-text files (`.txt`/`.md`/`.json`/`.py`/...) are rejected — use `read_file` directly for those.
>
> **Extract text from image(s) with `ax documents extract`** (`file_name` = absolute path to png/jpg/jpeg/webp/bmp/tif/tiff, or an array of paths — a batch is OCR'd in one pass into one `.md` file; read it with `read_file` afterwards). For text inside PDFs use `convert` (same OCR engine). `.gif` has no OCR path — use the vision summary. No fallback if the docling worker is missing — the error tells the user to install it.

## check

| Command | Required | Optional |
|---------|----------|----------|
| `extras` | — | `filter_term` |

> **CLI-only commands:** `check` only supports `extras` via the structured `ax()` tool call. Commands like `check instructions` or `check preflight` do not exist in the dispatch table and will always return `unknown_command` if called that way — invoke them as literal CLI strings via `shell` instead (see Resolution Order, step 5).

## worker

| Command | Required | Optional |
|---------|----------|----------|
| `spawn` | `prompt`, `expected`, `steps` | `instructions`, `output_dir`, `thread_id` |
| `list` | — | `thread_id` |
| `status` | `worker_id` | — |
| `logs` | `worker_id` | `tail` |
| `cancel` | `worker_id` | — |
| `clean` | — | `days` |

## mcp

| Command | Required | Optional |
|---------|----------|----------|
| `list` | — | `server` |
| `call` | `server`, `tool` | `arguments` |

> **External MCP servers.** `list` with no `server` returns the connected-server index (names + tool count). `list` with `server` returns that server's tools + input schemas (persisted to a file when large — read via `read_file`). `call` invokes a tool with raw-dict `arguments`. If `list` returns "No MCP servers connected", no external service is available — fall back to `web`/`http`/`shell`.
>
> **`call` shape** — `tool` is the exact tool name from `list` (kebab-case). Pass the tool's inputs as a JSON object in `arguments`:
> ```json
> {"reason": "...", "family": "mcp", "command": "call", "args": {"server": "whatsapp", "tool": "groups-list", "arguments": {}}}
> ```
> Use `tool`/`arguments` — not `method`, `name`, or `params`.

## voice

| Command | Required | Optional |
|---------|----------|----------|
| `transcribe` | `file` | — |

> **In-process speech-to-text** via the whisper server that runs with the web UI — no shell needed. `stt_unavailable` when voice is disabled or the web UI is not running (check `aria voice status` via shell). `.wav` files are read directly; other formats are converted in-memory via ffmpeg (`ffmpeg_missing` if the system binary is absent). Short transcripts return `text` inline; longer ones (>2000 chars) are persisted to `workspace/transcripts/` — read them with `read_file`. An empty `text` means no speech was detected.
