# Aria Tools Inventory

A comprehensive guide to all tools available in the `src/aria/tools` package. Each tool returns JSON-formatted responses. Tools are organized into **categories** managed by a centralized registry, plus a unified `ax` dispatcher that routes to domain tools (web, memory, knowledge, finance, IMDb, HTTP, dev, processes, documents, worker, mcp).

## Docstring Convention

All tool function docstrings follow an LLM-friendly format designed to help the LLM make good tool-selection decisions. Each docstring includes:

- **One-line summary** — what the tool does.
- **When to use** — positive signals (use when) and negative signals (do NOT use when) with cross-references to alternative tools.
- **Why** — the tool's purpose in the ecosystem and what problem it solves.
- **Args** — parameter descriptions (with `reason` noted as for logging/auditing).
- **Returns** — response structure.
- **Important** — gotchas, constraints, and tips.

This format is consumed by LlamaIndex's `FunctionTool.from_defaults()` which extracts the docstring as the tool description sent to the LLM.

---

## Table of Contents

1. [Core Infrastructure](#1-core-infrastructure)
2. [Tool Registry](#2-tool-registry)
3. [Browser Tools](#3-browser-tools)
4. [Development Tools](#4-development-tools)
5. [File Operations](#5-file-operations)
6. [HTTP Tools](#6-http-tools)
7. [IMDb Tools](#7-imdb-tools)
8. [Memory Tools](#8-memory-tools)
9. [Planner Tools](#9-planner-tools)
10. [Process Tools](#10-process-tools)
11. [Reasoning Tools](#11-reasoning-tools)
12. [Search Tools](#12-search-tools)
13. [Shell Tools](#13-shell-tools)
14. [ax Dispatcher](#14-ax-dispatcher)

---

## 1. Core Infrastructure

**Package:** `aria.tools`

### Overview

Shared utilities, decorators, constants, error handling, and retry mechanisms used across all tool modules.

### Constants (`aria.tools.constants`)

| Constant | Value | Description |
|----------|-------|-------------|
| `BASE_DIR` | `Path` | Base directory for file operations (defaults to `Data.path`, overridable via `TOOLS_DATA_FOLDER`) |
| `CODE_DIR` | `BASE_DIR / "code"` | Directory for code files |
| `DOWNLOADS_DIR` | `BASE_DIR / "downloads"` | Directory for downloads |
| `REPORTS_DIR` | `BASE_DIR / "reports"` | Directory for reports |
| `MAX_FILE_SIZE` | `5 * 1024 * 1024` | Maximum file size for processing (5 MB) |
| `DEFAULT_TIMEOUT` | `30` | Default timeout for operations (env: `ARIA_DEFAULT_TIMEOUT`) |
| `MAX_TIMEOUT` | `600` | Maximum timeout limit (env: `ARIA_MAX_TIMEOUT`) |
| `NETWORK_TIMEOUT` | `10` | Network request timeout (seconds) |

### Decorators (`aria.tools.decorators`)

#### `log_tool_call(func)`

Logs tool calls with reason parameter. Extracts reason from the first argument. Auto-detects sync/async.

```python
@log_tool_call
def my_tool(reason: str, ...) -> str:
    ...
```

### Utilities (`aria.tools.utils`)

| Function | Description |
|----------|-------------|
| `utc_timestamp() -> str` | Generate UTC ISO 8601 timestamp |
| `safe_json(data, *, default, indent, ensure_ascii) -> str` | Safe JSON serialization with fallback to `str()` |
| `tool_response(tool, reason, data=None, exc=None, **context) -> str` | Auto-selects success/error response |
| `tool_success_response(tool, reason, data, **context) -> str` | Standardized success JSON |
| `tool_error_response(tool, reason, exc, **context) -> str` | Standardized error JSON |
| `get_function_name(depth=1) -> str` | Get calling function name |

**Success response structure:**
```json
{
  "status": "success",
  "tool": "tool_name",
  "reason": "why this was called",
  "timestamp": "2024-01-01T12:00:00Z",
  "data": { }
}
```

**Error response structure:**
```json
{
  "status": "error",
  "tool": "tool_name",
  "reason": "why this was called",
  "timestamp": "2024-01-01T12:00:00Z",
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "type": "ExceptionClassName",
    "recoverable": false,
    "how_to_fix": "Recovery guidance"
  }
}
```

> **Convention:** Tools return `tool_error_response` on failure (status `"error"`), never a success payload embedding an error string.

### Error Handling (`aria.tools.errors`)

`ToolError` -- base exception for all tool operations:

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `code` | `str` | `"INTERNAL_ERROR"` | Machine-readable error code |
| `recoverable` | `bool` | `False` | Whether the agent can retry |
| `how_to_fix` | `str` | `"An unexpected error occurred."` | Recovery guidance |

---

## 2. Tool Registry

**Module:** `aria.tools.registry`

### Overview

Centralized, categorized tool loading. Agents load tools by category through the registry. Tools are wrapped as `llama_index.core.tools.FunctionTool` instances.

### Categories

The registry exposes three primary categories plus two "lite" variants used by the Aria agent:

| Category | Constant | Used by | Tools |
|----------|----------|---------|-------|
| **CORE** | `"core"` | Worker | `reasoning`, `plan`, `scratchpad`, `shell` (4 tools) |
| **FILES** | `"files"` | Worker | `read_file`, `write_file`, `edit_file`, `file_info`, `list_files`, `search_files`, `copy_file` (7 tools) |
| **AX** | `"ax"` | Both | Single unified `ax` dispatcher tool |
| **CORE_LITE** | `"core_lite"` | Aria agent | `reasoning`, `shell` (2 tools) |
| **FILES_LITE** | `"files_lite"` | Aria agent | `read_file`, `write_file`, `edit_file`, `list_files`, `search_files` (5 tools) |

`ALL_CATEGORIES` = `[CORE, FILES, AX]`.

> Domain tools (web, knowledge, finance, IMDb, HTTP, dev, processes, worker) are **not** separate categories anymore — they are all routed through the single `ax` dispatcher (the `AX` category).

### Which agent loads what

| Agent | Categories |
|-------|------------|
| Aria agent | `[CORE_LITE, FILES_LITE, AX]` |
| Worker agent | `[CORE, FILES, AX]` |

### API

#### `get_tools(categories=None) -> List[FunctionTool]`

Load tools by category. `None` loads `ALL_CATEGORIES`. Deduplicates by name so the same tool is never registered twice when multiple categories are combined.

```python
from aria.tools.registry import get_tools, CORE, FILES, AX

all_tools = get_tools()
tools = get_tools([CORE, FILES, AX])
```

Each category has a private loader (e.g. `_get_core_tools()`, `_get_file_tools()`, `_get_ax_tools()`) that lazily imports and wraps with `FunctionTool.from_defaults()`. Browser-backed `ax` commands use async targets.

---

## 3. Browser Tools

**Package:** `aria.tools.browser` -- **Routed via:** `ax` (family `web`: `visit`, `click`, `close`) -- **Requires:** Lightpanda (`aria lightpanda download`)

Browser automation using Lightpanda with Playwright CDP. Bypasses anti-bot protection. Browser starts automatically with the Aria server.

### `visit_url(reason, url)` -- async

Visit a URL and get rendered page content. The page stays open so you can interact with it via `browser_click`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `reason` | `str` | Yes | Why you are visiting this URL |
| `url` | `str` | Yes | The URL to navigate to |

**Returns:** JSON with URL, title, persisted content metadata (`content_file`, `content_preview`, `content_size`).

### `browser_click(reason, selector)` -- async

Click an element by CSS selector on the currently open page.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `reason` | `str` | Yes | Why you are clicking |
| `selector` | `str` | Yes | CSS selector (e.g., `button.accept`, `a[href="/next"]`, `#submit-button`) |

**Returns:** JSON with updated page content metadata.

### `browser_close(reason)` -- async

Close the current browser page (navigates to `about:blank`; the browser itself stays running).

```python
await browser_click("Accepting cookies", "button.accept")
await browser_click("Going to next page", "a.next-page")
```

---

## 4. Development Tools

**Package:** `aria.tools.development` -- **Routed via:** `ax` (family `dev`, command `run`)

Consolidates `check_python_syntax`, `check_python_file_syntax`, `execute_python_code`, `execute_python_file` into one tool.

### `python(reason, code?, file?, args?, timeout=30, check_only=False)`

Execute or validate Python code. Provide **exactly one** of `code` or `file`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `reason` | `str` | Yes | -- | Why you're running this |
| `code` | `str` | One of code/file | `None` | Python code string |
| `file` | `str` | One of code/file | `None` | Path to Python file |
| `args` | `List[str]` | No | `None` | CLI arguments for `sys.argv` |
| `timeout` | `int` | No | `30` | Max seconds (capped at `MAX_TIMEOUT`, default 600, env: `ARIA_MAX_TIMEOUT`) |
| `check_only` | `bool` | No | `False` | Validate syntax only |

**Returns (check_only):** `{ "valid": true, "message": "Syntax is valid" }`

**Returns (execution):** `{ "success": true, "stdout_file": "/path/to/output.txt", "exit_code": 0 }`

Fields `stdout_file` and `stderr_file` are present only when the corresponding
output is non-empty. Use `read_file` on the returned paths to inspect output.

```python
python("Testing algorithm", code="print(sum(range(10)))")
python("Running tests", file="test_suite.py", args=["--verbose"])
python("Validating module", file="module.py", check_only=True)
```

---

## 5. File Operations

**Package:** `aria.tools.files` -- **Category:** `FILES` (worker) / `FILES_LITE` (Aria agent)

| Module | Tools |
|--------|-------|
| `unified_read` | `read_file`, `file_info`, `list_files`, `search_files` |
| `write_operations` | `write_file`, `edit_file` |
| `file_management` | `copy_file` |

All paths resolved relative to `BASE_DIR` with security validation.

### `read_file(reason, file_name, offset=0, length=0, max_lines=500)`

Read file contents with optional chunking.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reason` | `str` | -- | Why you're reading |
| `file_name` | `str` | -- | Path relative to `BASE_DIR` |
| `offset` | `int` | `0` | 0-indexed starting line |
| `length` | `int` | `0` | Lines to read (0 = all) |
| `max_lines` | `int` | `500` | Max lines for full read |

- `offset=0, length=0`: Full file (subject to `max_lines`)
- Otherwise: Chunked read with `has_more`, `next_offset`

**Returns:** JSON with `file_name`, `content`, `lines[]`, `total_lines`, `mode`.

### `file_info(reason, file_name)`

Get file metadata: `exists`, `is_file`, `is_directory`, `size`, `created`, `modified`, `permissions`, `mime_type`. (Worker-only; not in `FILES_LITE`.)

### `list_files(reason, pattern="*", recursive=False, max_depth=3, max_results=100, path=".")`

List files/directories. `recursive=True` gives tree view; `False` gives flat list.

**Returns:** JSON with `files` or `tree`, plus `count`.

### `search_files(reason, pattern, mode="name", file_pattern="**/*", recursive=True, max_results=500, context_lines=2, path=".")`

Search by filename (`mode="name"`) or content (`mode="content"`) regex.

**Returns:** JSON with `matches[]`, `count`.

### `write_file(reason, file_name, contents, mode="overwrite")`

Write or append. Auto-creates parent dirs. Atomic writes with backup.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reason` | `str` | -- | Why you're writing |
| `file_name` | `str` | -- | Absolute path |
| `contents` | `str` | -- | Content to write |
| `mode` | `str` | `"overwrite"` | `"overwrite"` or `"append"` |

**Returns (overwrite):** `bytes_written`, `lines_written`, `created`, `backup_created`
**Returns (append):** `bytes_appended`, `new_total_lines`, `new_file_size`

### `edit_file(reason, file_name, offset, length=0, new_lines?)`

Insert, replace, or delete lines. Always creates backup.

| `length` | `new_lines` | Operation |
|----------|-------------|-----------|
| `0` | provided | **Insert** at offset |
| `> 0` | provided | **Replace** lines |
| `> 0` | `None` | **Delete** lines |

**Returns:** `operation`, `offset`, `length`, `lines_affected`, `old_total_lines`, `new_total_lines`, `backup_created`.

```python
edit_file("Adding import", "module.py", offset=2, new_lines=["import os"])
edit_file("Updating fn", "module.py", offset=2, length=3, new_lines=["def new():"])
edit_file("Removing code", "module.py", offset=2, length=3)
```

### `copy_file(reason, source, destination, overwrite=False)`

Copy a file. Returns `source`, `destination`, `bytes_copied`, `success`. (Worker-only; not in `FILES_LITE`.)

---

## 6. HTTP Tools

**Package:** `aria.tools.http` -- **Routed via:** `ax` (family `http`, command `request`)

### `http_request(reason, method, url, headers?, body?, timeout?)`

General-purpose HTTP requests via `httpx` with redirect following.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reason` | `str` | -- | Why you're requesting |
| `method` | `str` | -- | `GET`, `POST`, `PUT`, `DELETE`, `PATCH`, `HEAD`, `OPTIONS` |
| `url` | `str` | -- | URL to request |
| `headers` | `Dict[str, str]` | `None` | Request headers |
| `body` | `str` | `None` | Request body |
| `timeout` | `int` | `30` | Timeout seconds (capped at `MAX_TIMEOUT`, default 600, env: `ARIA_MAX_TIMEOUT`) |

**Returns:** `status_code`, `headers`, `url`, `body_file`, `body_size`, `content_type`. The body is persisted to disk and returned as a file path. Never raises -- returns error data on failure.

```python
http_request("Fetching data", "GET", "https://api.example.com/users")
http_request(
    "Creating user",
    "POST",
    "https://api.example.com/users",
    headers={"Content-Type": "application/json"},
    body='{"name": "Alice"}',
)
```

---

## 7. IMDb Tools

**Package:** `aria.tools.imdb` -- **Routed via:** `ax` (family `imdb`)

Movie/TV information via the `imdbinfo` package. Returns curated field subsets.

### `search_imdb_titles(reason, query, title_type?)`

Search titles. `title_type`: `movie`, `series`, `episode`, `short`, `tv_movie`, `video`.

**Returns:** `titles[{imdbId, title, year, kind, rating}]`, `names[{imdbId, name, job}]`.

### `get_movie_details(reason, imdb_id)`

Full movie/series details: `title`, `year`, `rating`, `genres`, `plot`, `runtime`, `directors[]`, `writers[]`, `cast[]`, `stars[]`, `awards`.

### `get_person_details(reason, person_id)`

Person bio and filmography highlights.

### `get_person_filmography(reason, person_id)`

Full filmography: `director[]`, `actor[]`, `producer[]`, `writer[]`.

### `get_all_series_episodes(reason, imdb_id)`

All episodes with season, episode number, title, rating, air date.

### `get_movie_reviews(reason, imdb_id)`

User reviews for a title.

### `get_movie_trivia(reason, imdb_id)`

Trivia for a title.

---

## 8. Memory Tools

**Package:** `aria.tools.memory` -- **Routed via:** `ax` (family `memory`, `inject_action` enabled)

Persistent key-value store across conversations. SQLite-backed. This is the
long-term memory store (entries survive restarts and conversation
boundaries). For ephemeral working memory within a task use `scratchpad`
(`CORE`); for structured execution plans use `plan` (`CORE`).

> **Renamed family.** This store used to be exposed under the `ax knowledge`
> family. The `knowledge` family now serves a **different** purpose — see
> the Knowledge Hub section below.

### `memory(reason, action, key?, value?, tags?, entry_id?, query?, max_results=10, agent_id="aria")`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reason` | `str` | -- | Why you're using the store |
| `action` | `str` | -- | `store`, `recall`, `search`, `list`, `update`, `delete` |
| `key` | `str` | `None` | Entry key (for `store`/`recall`) |
| `value` | `str` | `None` | Value (for `store`/`update`) |
| `tags` | `List[str]` | `None` | Tags for categorization |
| `entry_id` | `str` | `None` | UUID (for `update`/`delete`) |
| `query` | `str` | `None` | Search query |
| `max_results` | `int` | `10` | Max results |
| `agent_id` | `str` | `"aria"` | Auto-injected by the dispatcher, do not provide |

| Action | Required | Returns |
|--------|----------|---------|
| `store` | `key`, `value` | `entry_id`, `key`, message |
| `recall` | `key` | `found`, entry data |
| `search` | `query` | `results_count`, `results[]` |
| `list` | -- | `count`, `entries[]` |
| `update` | `entry_id`, `value` | `entry_id`, message |
| `delete` | `entry_id` | `entry_id`, message |

> `action` is injected automatically by the `ax` dispatcher from the
> `command` argument (do not pass it in `args`).

```python
ax(reason="Save preference", family="memory", command="store", args={"key": "lang", "value": "Python", "tags": ["prefs"]})
ax(reason="Check preference", family="memory", command="recall", args={"key": "lang"})
ax(reason="Search memory", family="memory", command="search", args={"query": "Python"})
```

### Knowledge Hub (`ax knowledge`) -- on-demand document indexing

**Routed via:** `ax` (family `knowledge`) -- **Requires:** `KnowledgeHub.enabled` (`ARIA_KNOWLEDGE_ENABLED=true`)

A separate, optional subsystem that indexes a configured documents directory
into the vector store for grounded answers. It is **not** the key-value
memory store. Only two commands:

| Command | Description |
|---------|-------------|
| `status` | Report indexing state (counts, indexed/skipped files) |
| `reindex` | Re-scan the configured directory and index new/changed documents |

The background reindex also runs automatically at startup when enabled
(see the Web UI initialization docs).

---

## 9. Planner Tools

**Package:** `aria.tools.planner` -- **Category:** `CORE` (worker only; not in `CORE_LITE`)

Consolidates 7 previous functions into one. SQLite-backed execution plans.

### `plan(reason, action, task?, steps?, step_id?, status?, result?, description?, after_step_id?, step_ids?, execution_id?, agent_id="default")`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reason` | `str` | -- | What and why |
| `action` | `str` | -- | `create`, `get`, `update`, `add`, `remove`, `replace`, `reorder` |
| `task` | `str` | `None` | Task description (for `create`) |
| `steps` | `List[str]` | `None` | Step descriptions (for `create`) |
| `step_id` | `str` | `None` | Step ID (for `update`/`remove`/`replace`) |
| `status` | `str` | `None` | `pending`, `in_progress`, `completed`, `failed` |
| `result` | `str` | `None` | Result message (for `update`) |
| `description` | `str` | `None` | Step text (for `add`/`replace`) |
| `after_step_id` | `str` | `None` | Insert position (for `add`) |
| `step_ids` | `List[str]` | `None` | New order (for `reorder`) |
| `execution_id` | `str` | `None` | Plan ID (from `create`, required for others) |
| `agent_id` | `str` | `"default"` | Multi-agent isolation |

| Action | Required | Returns |
|--------|----------|---------|
| `create` | `task`, `steps` | `execution_id`, plan data |
| `get` | `execution_id` | Full plan with statuses |
| `update` | `execution_id`, `step_id`, `status` | Updated step |
| `add` | `execution_id`, `description` | New step |
| `remove` | `execution_id`, `step_id` | Confirmation |
| `replace` | `execution_id`, `step_id`, `description` | Updated step |
| `reorder` | `execution_id`, `step_ids` | Reordered steps |

```python
result = plan(
    "Planning deploy",
    action="create",
    task="Deploy v2.0",
    steps=["Run tests", "Build image", "Deploy staging", "Deploy prod"],
)

plan(
    "Starting tests",
    action="update",
    execution_id="abc123",
    step_id="step_1",
    status="in_progress",
)

plan(
    "Tests passed",
    action="update",
    execution_id="abc123",
    step_id="step_1",
    status="completed",
    result="All 42 tests passed",
)
```

---

## 10. Process Tools

**Package:** `aria.tools.process` -- **Routed via:** `ax` (family `processes`)

Background process manager. State is persisted to `data/processes.json` (survives restarts); stdout/stderr are redirected to log files so child processes survive parent exit. Default concurrency limit is 10 (configurable via `ARIA_MAX_PROCESSES`).

### `process(reason, action, name?, command?, args?, timeout?, working_dir?, env?, use_shell=False, signal_name?)`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reason` | `str` | -- | Why |
| `action` | `str` | -- | `start`, `stop`, `status`, `logs`, `list`, `restart`, `signal` |
| `name` | `str` | `None` | Unique process name |
| `command` | `str` | `None` | Command (for `start`) |
| `args` | `List[str]` | `None` | Arguments |
| `timeout` | `int` | `None` | Timeout seconds |
| `working_dir` | `str` | `None` | Working directory |
| `env` | `Dict[str, str]` | `None` | Additional environment variables |
| `use_shell` | `bool` | `False` | Execute via system shell (pipes/redirects) |
| `signal_name` | `str` | `None` | Signal name for `signal` (e.g. `SIGTERM`, `SIGKILL`) |

| Action | Required | Returns |
|--------|----------|---------|
| `start` | `name`, `command` | `name`, `pid`, message |
| `stop` | `name` | `name`, message |
| `status` | `name` | `name`, `pid`, `status`, `return_code` |
| `logs` | `name` | `stdout`, `stderr` (tail) |
| `list` | -- | `processes[]` |
| `restart` | `name` | `name`, `pid`, message |
| `signal` | `name`, `signal_name` | `name`, message |

> `action` is injected automatically by the `ax` dispatcher (do not pass it in `args`).

**Security:** Blocklist includes `shutdown`, `reboot`, `halt`, `poweroff`, `mkfs`, `dd`, `shred`, `wipe` (matched by command name).

```python
process(
    "Starting server",
    action="start",
    name="devserver",
    command="python",
    args=["-m", "http.server", "8080"],
)
process("Checking", action="status", name="devserver")
process("Reading logs", action="logs", name="devserver")
process("Stopping", action="stop", name="devserver")
```

---

## 11. Reasoning Tools

**Package:** `aria.tools.reasoning` + `aria.tools.scratchpad` -- **Category:** `CORE` (worker) / `CORE_LITE` (Aria agent)

`reasoning` is a structured analysis tool; `scratchpad` is independent key-value working memory. Both persist across sessions.

### `reasoning(reason, action, content?, cognitive_mode?, reasoning_type?, evidence?, confidence?, on_step?, agent_id="aria")`

Structured analysis tool. One active session per agent (auto-managed).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reason` | `str` | -- | What and why |
| `action` | `str` | -- | `start`, `step`, `reflect`, `evaluate`, `summary`, `end` |
| `content` | `str` | `None` | Reasoning content (for `step`/`reflect`) |
| `cognitive_mode` | `str` | `None` | `planning`, `analysis`, `evaluation`, `synthesis`, `creative`, `reflection` |
| `reasoning_type` | `str` | `None` | `deductive`, `inductive`, `abductive`, `causal`, `probabilistic`, `analogical` |
| `evidence` | `List[str]` | `None` | Supporting evidence |
| `confidence` | `float` | `None` | 0.0--1.0 |
| `on_step` | `int` | `None` | Step number (for `reflect`) |
| `agent_id` | `str` | `"aria"` | Auto-set |

| Action | Required | Returns |
|--------|----------|---------|
| `start` | -- | `session_id`, message |
| `step` | `content` | Step data with number, mode, type, confidence |
| `reflect` | `content` | Reflection data |
| `evaluate` | -- | Quality scores |
| `summary` | -- | Session summary |
| `end` | -- | Closure confirmation |

**Typical workflow:** `start` -> `step` (multiple) -> `reflect` -> `evaluate` -> `end`

```python
reasoning("Analyzing options", action="start")
reasoning(
    "Evaluating A",
    action="step",
    content="Microservices provide better scalability...",
    cognitive_mode="analysis",
    reasoning_type="deductive",
    evidence=["Netflix case study"],
    confidence=0.8,
)
reasoning(
    "Checking bias",
    action="reflect",
    content="May be over-weighting scalability",
    on_step=1,
)
reasoning("Quality check", action="evaluate")
reasoning("Done", action="end")
```

### `scratchpad(reason, key, value?, operation="get", agent_id="aria")`

Independent key-value working memory. Persists across sessions.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reason` | `str` | -- | Why |
| `key` | `str` | -- | Key (ignored for `list`) |
| `value` | `str` | `None` | Value (for `set`) |
| `operation` | `str` | `"get"` | `get`, `set`, `delete`, `list` |
| `agent_id` | `str` | `"aria"` | Auto-set |

| Operation | Required | Returns |
|-----------|----------|---------|
| `get` | `key` | `key`, `value` |
| `set` | `key`, `value` | Confirmation |
| `delete` | `key` | Confirmation (`key="all"` clears everything) |
| `list` | -- | All keys and values |

```python
scratchpad("Saving results", key="analysis_v1", value="Option A: 8/10", operation="set")
scratchpad("Checking", key="analysis_v1")
scratchpad("Listing all", key="_", operation="list")
scratchpad("Clearing", key="all", operation="delete")
```

---

## 12. Search Tools

**Package:** `aria.tools.search` -- **Routed via:** `ax` (family `web`)

### `web_search(reason, query, max_results=5)`

Searches the web using webserp — a metasearch CLI that queries Google, DuckDuckGo, Brave, Yahoo, Mojeek, Startpage, and Presearch in parallel with browser impersonation. No API keys required.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reason` | `str` | -- | Why |
| `query` | `str` | -- | Search query |
| `max_results` | `int` | `5` | Max results |

**Returns:** `findings[]` with `url`, `title`, `content`, and `engine` per result. Returns URLs, not page content -- use `visit_url` or `download` to fetch full pages.

### `download(reason, url, output="auto", custom_headers?, max_size?, convert_to_markdown=False)`

Download files (PDFs, images, archives, HTML, etc.) to disk.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reason` | `str` | -- | Why |
| `url` | `str` | -- | Direct URL |
| `output` | `str` | `"auto"` | `auto`, `markdown`, `text`, `binary` |
| `custom_headers` | `Dict[str, str]` | `None` | HTTP headers |
| `max_size` | `int` | `None` | Max bytes (default 5 MB) |
| `convert_to_markdown` | `bool` | `False` | Convert HTML to markdown |

**Returns:** `file_path`, `metadata` (mime_type, size_bytes), optionally a markdown version.

### `get_current_weather(reason, location)`

Current weather via Open-Meteo (no API key).

| Parameter | Type | Description |
|-----------|------|-------------|
| `reason` | `str` | Why |
| `location` | `str` | City name or place (e.g., `"Berlin"`) |

**Returns:**
```json
{
  "resolved": { "name": "Berlin", "country": "Germany", "latitude": 52.52 },
  "current": { "temperature_c": 5.2, "wind_speed_kmh": 12.3, "conditions": "Overcast" }
}
```

### Finance Tools (routed via `ax` family `finance`)

#### `fetch_current_stock_price(reason, ticker)`

Current price via Yahoo Finance. Returns `current_price`, `currency`, `market_state`, `day_change`, `day_change_percent`.

#### `fetch_company_information(reason, ticker)`

Company fundamentals. Returns `basic_info`, `financial_metrics`, `price_data`, `financial_health`, `analyst_data`, `location`.

#### `fetch_ticker_news(reason, ticker, max_articles=10)`

Recent news. Returns `articles[{title, publisher, link, publish_time}]`. Max 50 articles.

### YouTube Transcription -- routed via `ax web youtube`

**Function:** `get_youtube_video_transcription` -- downloads YouTube captions to disk.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reason` | `str` | -- | Why you need this transcript |
| `url` | `str` | -- | Full YouTube video URL |
| `languages` | `List[str]` | `None` | Preferred languages in order (e.g. `["en", "es"]`). Default: English |

**Returns:** `file_path`, `metadata` (with `video_id`, `transcript_segments`, `estimated_duration`).

> Persistence-first: writes to disk, returns file metadata (not content).

---

## 13. Shell Tools

**Package:** `aria.tools.shell` -- **Category:** `CORE` (worker) / `CORE_LITE` (Aria agent)

Execute shell commands with timeout handling, output capture, and security constraints.

### `shell(reason, commands, stop_on_error=True, timeout?, working_dir?, env?)`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reason` | `str` | -- | Why |
| `commands` | `str`, `List[str]`, `Dict`, or `List[Dict]` | -- | Command(s) to execute |
| `stop_on_error` | `bool` | `True` | Stop batch on failure |
| `timeout` | `int` | `30` | Default timeout (capped at `MAX_TIMEOUT`, default 600, env: `ARIA_MAX_TIMEOUT`) |
| `working_dir` | `str` | `BASE_DIR` | Default working directory |
| `env` | `Dict[str, str]` | `None` | Additional environment variables |

**Input formats:**

| Format | Example |
|--------|---------|
| Single string | `"git status"` |
| List of strings | `["git pull", "pip install -r reqs"]` |
| Single dict | `{"command": "git status"}` |
| List of dicts | `[{"command": "git pull"}, {"command": "pytest"}]` |

**Command dict fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `command` | `str` | Yes | Full command string (supports pipes, redirects, chaining) |
| `timeout` | `int` | No | Per-command timeout |
| `working_dir` | `str` | No | Per-command directory |
| `env` | `Dict[str, str]` | No | Per-command environment variables |
| `continue_on_error` | `bool` | No | Continue batch on failure |

**Response format:**

Single commands return a **flat response** (no wrapper):

```json
{
  "command": "echo hello",
  "return_code": 0,
  "execution_time": 0.001,
  "stdout_file": "/path/to/shell_output/20260101_120000_stdout_a1b2c3d4.txt",
  "stdout_head_tail": "hello"
}
```

Fields `stdout_file`/`stderr_file` and `stdout_head_tail`/`stderr_head_tail`
are present only when the corresponding output is non-empty. Use `read_file`
on the returned paths to inspect full output.

Batch commands (2+) return a **results array**:

```json
{
  "results": [
    {"command": "echo hello", "return_code": 0, "stdout_file": "/path/.../stdout_*.txt", "stdout_head_tail": "hello", "execution_time": 0.001},
    {"command": "echo world", "return_code": 0, "stdout_file": "/path/.../stdout_*.txt", "stdout_head_tail": "world", "execution_time": 0.001}
  ],
  "execution_time": 0.002,
  "stopped_early": false
}
```

Blocked commands return `return_code: 1` with an `error` field. Timed-out commands include `timed_out: true`.

```python
shell("Git status", commands="git status")
shell(
    "Building",
    commands=[
        "git pull",
        "pip install -r requirements.txt",
        "python -m pytest",
    ],
)
```

---

## 14. ax Dispatcher

**Module:** `aria.tools.ax` -- **Category:** `AX` (loaded by both Aria and Worker agents)

Unified dispatcher that routes `family`/`command` pairs to native Python functions. Replaces shell-based `ax <family> <command>` calls with direct function dispatch -- same structured JSON responses, zero subprocess overhead. Use `family="help"` to list families, and `family="help"`, `command="lookup"` with `args={"topic": "<family>"}` to fetch a family's detailed on-demand reference.

### `ax(reason, family, command, args?)`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `reason` | `str` | Yes | Why you are calling this |
| `family` | `str` | Yes | Command family (see table below) |
| `command` | `str` | Yes | Subcommand within the family. Use `"help"` to list available commands |
| `args` | `Dict[str, Any]` | No | Keyword arguments for the target function (excluding `reason`) |

> `reason` is always required and passed by the caller. For families with `inject_action` enabled (`memory`, `processes`, `documents`, `worker`), `action` is set automatically from `command` -- do not pass it in `args`. The dispatcher strips unknown kwargs that the target function does not accept.

### Command Matrix

| Family | Commands | Description |
|--------|----------|-------------|
| `web` | `search`, `fetch`, `visit`, `click`, `close`, `weather`, `youtube` | Web search, page visiting, content download, weather, YouTube transcripts |
| `memory` | `store`, `recall`, `search`, `list`, `update`, `delete` | Persistent key-value memory across sessions (SQLite-backed) |
| `knowledge` | `status`, `reindex` | Knowledge hub document indexing (requires `ARIA_KNOWLEDGE_ENABLED`) |
| `finance` | `stock`, `company`, `news` | Stock/crypto prices, company fundamentals, ticker news |
| `imdb` | `search`, `movie`, `person`, `filmography`, `episodes`, `reviews`, `trivia` | Movies, shows, people via IMDb |
| `http` | `request` | REST API calls (GET/POST/PUT/DELETE/PATCH). Responses persisted to disk |
| `dev` | `run` | Execute Python code or file in a sandboxed subprocess |
| `processes` | `start`, `stop`, `status`, `logs`, `list`, `restart`, `signal` | Manage background processes (dev servers, build watchers, pipelines) |
| `documents` | `convert`, `status` | Convert office/PDF/HTML to markdown; check the Granite-Docling worker status |
| `check` | `extras` | Discover additional CLI tools available in the virtual environment |
| `worker` | `spawn`, `list`, `status`, `logs`, `cancel`, `clean` | Manage background worker agents |
| `mcp` | `list`, `call` | Discover and invoke Model Context Protocol servers |
| `help` | *(any)*, `lookup` | List families/commands; `lookup` fetches a family's detailed reference |

### Web command arguments

| Command | Required | Optional |
|---------|----------|----------|
| `search` | `query` | `category`, `time_range`, `max_results` |
| `fetch` | `url` | `output`, `convert_to_markdown`, `custom_headers`, `max_size` |
| `visit` | `url` | -- |
| `click` | `selector` | -- |
| `close` | -- | -- |
| `weather` | `location` | -- |
| `youtube` | `url` | `languages` |

### Examples

```python
# Web search
ax(
    reason="Find Python tutorials",
    family="web",
    command="search",
    args={"query": "python asyncio tutorial"},
)

# Visit a page (renders JS)
ax(
    reason="Reading docs",
    family="web",
    command="visit",
    args={"url": "https://example.com"},
)

# Stock price
ax(
    reason="Check AAPL price",
    family="finance",
    command="stock",
    args={"ticker": "AAPL"},
)

# Memory store
ax(
    reason="Save preference",
    family="memory",
    command="store",
    args={"key": "lang", "value": "Python", "tags": ["prefs"]},
)

# Process management
ax(
    reason="Start dev server",
    family="processes",
    command="start",
    args={"name": "dev", "command": "python", "args": ["-m", "http.server"]},
)

# Spawn a worker
ax(
    reason="Delegate research",
    family="worker",
    command="spawn",
    args={"prompt": "...", "expected": "report.md", "steps": ["...", "..."]},
)

# Discover available CLI tools
ax(reason="Check available tools", family="check", command="extras")

# Help
ax(reason="List web commands", family="web", command="help")
ax(reason="Detailed web reference", family="help", command="lookup", args={"topic": "web"})
```

### Error Handling

| Error Code | Meaning |
|------------|---------|
| `missing_reason` | The `reason` argument was not provided. |
| `missing_required_args` | `family` and/or `command` missing. |
| `unknown_family` | Invalid family name. Lists available families. |
| `unknown_command` | Invalid command for the family. Lists available commands. |
| `import_error` | Could not load the target module. |
| `invalid_args` | Wrong arguments passed to the target function. |
| `dispatch_error` | `AxDispatchError` raised by the target. |
| `execution_error` | Runtime error in the target function. |

---

## CLI Access

The `aria` CLI mirrors several `ax` families as `aria web ...` subcommands:

| CLI Command | ax equivalent | Description |
|-------------|---------------|-------------|
| `aria web search "query"` | `ax web search` | Web search |
| `aria web fetch "url"` | `ax web fetch` | Fetch URL content (auto-detects file vs website) |
| `aria web visit "url"` | `ax web visit` | Visit a page in the browser (stays open for click) |
| `aria web click "selector"` | `ax web click` | Click element on the current page |
| `aria web close` | `ax web close` | Close browser page |
| `aria web weather "city"` | `ax web weather` | Weather forecast |
| `aria web youtube "url"` | `ax web youtube` | YouTube transcript |

---

## Quick Reference

| Task | Tool / ax command |
|------|-------------------|
| Think through a problem | `reasoning` |
| Store working notes | `scratchpad` |
| Create execution plan | `plan` (worker only) |
| Run shell commands | `shell` |
| Read a file | `read_file` |
| Write/create a file | `write_file` |
| Edit lines in a file | `edit_file` |
| Get file metadata | `file_info` (worker only) |
| List directory contents | `list_files` |
| Search files by name/content | `search_files` |
| Copy a file | `copy_file` (worker only) |
| Search the web | `ax web search` |
| Visit a website (render JS) | `ax web visit` |
| Click a web element | `ax web click` |
| Close the browser page | `ax web close` |
| Download a file | `ax web fetch` |
| Get weather | `ax web weather` |
| Get a YouTube transcript | `ax web youtube` |
| Run Python code | `ax dev run` |
| Make HTTP requests | `ax http request` |
| Manage background processes | `ax processes <action>` |
| Get stock prices | `ax finance stock` |
| Get company info | `ax finance company` |
| Get ticker news | `ax finance news` |
| Search movies/TV | `ax imdb search` |
| Get movie details | `ax imdb movie` |
| Get person details | `ax imdb person` |
| Get filmography | `ax imdb filmography` |
| Get series episodes | `ax imdb episodes` |
| Get movie reviews | `ax imdb reviews` |
| Get movie trivia | `ax imdb trivia` |
| Persistent memory | `ax memory <action>` |
| Reindex knowledge hub | `ax knowledge reindex` |
| Spawn a background worker | `ax worker spawn` |
| Discover extra CLI tools | `ax check extras` |
| Convert office/PDF to markdown | `ax documents convert` |
| Check Granite-Docling worker | `ax documents status` |
| List MCP servers | `ax mcp list` |
| Call an MCP tool | `ax mcp call` |
