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
| `status` | — | — |

> **Convert office/HTML/PDF to markdown with `ax documents convert`** (`file_name` = absolute path). Output is persisted to a `.md` file — read it with `read_file` in chunks afterwards. Already-text files (`.txt`/`.md`/`.json`/`.py`/...) are rejected — use `read_file` directly for those.

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
