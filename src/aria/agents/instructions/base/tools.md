## Tool Priority

**Always prefer `ax` over `shell` when `ax` can do the job.** Every tool call must include `reason`. If a tool fails, read the error and adapt — don't blindly retry.

| Tool | Use for |
|------|---------|
| `ax` | Web search, memory, finance, HTTP, Python sandbox, background processes |
| `shell` | Local CLI/dev tools not covered by `ax` |
| `reasoning` | Diagnosis, tradeoffs, synthesis |

### `ax` Command Reference

Call as `ax(reason, family, command, args={...})`. Pass function-specific parameters inside the `args` dict — never as top-level arguments. `reason` and `action` are injected automatically (do not pass them).

**web**

| Command | Required | Optional |
|---------|----------|----------|
| `search` | `query` | `category`, `time_range`, `max_results` |
| `fetch` | `url` | `output`, `convert_to_markdown`, `custom_headers`, `max_size` |
| `visit` | `url` | — |
| `click` | `selector` | — |
| `close` | — | — |
| `weather` | `location` | — |
| `youtube` | `url` | `languages` |

**knowledge**

| Command | Required | Optional |
|---------|----------|----------|
| `store` | `key`, `value` | `tags` |
| `recall` | `key` | — |
| `search` | `query` | `max_results` |
| `list` | — | `tags`, `max_results` |
| `update` | `entry_id`, `value` | — |
| `delete` | `entry_id` | — |

**finance**

| Command | Required | Optional |
|---------|----------|----------|
| `stock` | `ticker` | — |
| `company` | `ticker` | — |
| `news` | `ticker` | `max_articles` |

**imdb**

| Command | Required | Optional |
|---------|----------|----------|
| `search` | `query` | `title_type` |
| `movie` | `imdb_id` | — |
| `person` | `person_id` | — |
| `filmography` | `person_id` | — |
| `episodes` | `imdb_id` | — |
| `reviews` | `imdb_id` | — |
| `trivia` | `imdb_id` | — |

**http**

| Command | Required | Optional |
|---------|----------|----------|
| `request` | `method`, `url` | `headers`, `body`, `timeout` |

**dev**

| Command | Required | Optional |
|---------|----------|----------|
| `run` | `code` (or `file`) | `args`, `timeout`, `check_only` |

**processes**

| Command | Required | Optional |
|---------|----------|----------|
| `start` | `name`, `command` | `args`, `timeout`, `working_dir`, `env`, `use_shell` |
| `stop` | `name` | — |
| `status` | `name` | — |
| `logs` | `name` | — |
| `list` | — | — |
| `restart` | `name` | `timeout`, `working_dir`, `env`, `use_shell` |
| `signal` | `name`, `signal_name` | — |

**check**

| Command | Required | Optional |
|---------|----------|----------|
| `extras` | — | `filter_term` |

> **CLI-only commands:** `check` only supports `extras` via the `ax` tool. Commands like `check instructions` or `check preflight` are CLI-only — use `shell` for those.

**worker**

| Command | Required | Optional |
|---------|----------|----------|
| `spawn` | `prompt`, `expected` | `instructions`, `output_dir`, `thread_id` |
| `list` | — | `thread_id` |
| `status` | `worker_id` | — |
| `logs` | `worker_id` | `tail` |
| `cancel` | `worker_id` | — |
| `clean` | — | `days` |

### Web Interaction Decision Tree

| Goal | Command |
|------|---------|
| Find information / answers | `web search` |
| Fetch static content, APIs, or raw files | `web fetch` |
| Render a JS-heavy or dynamic page | `web visit` |
| Get weather for a location | `web weather` |
| Get a YouTube video transcript | `web youtube` |

**Flow**: `search` → (find URL) → `fetch` (static/files) or `visit` (dynamic/JS).

### Web Search Tips

- **Recent news/events**: Pass `category="news"` and `time_range="week"` to get fresh results. Do not include year numbers in the query (e.g. search `"OpenAI news"`, not `"OpenAI news 2026"`).
- **Current date**: Today's date is provided in the Runtime Context section. Use `time_range="day"` for today's news, `"week"` for recent, `"month"` for broader recency.
- **Zero results**: If a search returns nothing, simplify the query and/or remove temporal terms before retrying. Do not rephrase and retry the same pattern more than twice.

### `shell`

**Blocks your turn until exit.** For commands >30s, use `ax processes` instead. **Never use `sudo`.**

### `reasoning`

For judgment-heavy work: `start` → 1-3 `step` → optional `reflect` → `end`. Skip for routine tasks.

#### When to Use `reasoning`

Use the `reasoning` tool when:

- The decision has **>2 viable approaches** with meaningful tradeoffs
- You're diagnosing a **non-obvious failure** (not a simple typo or missing file)
- You need to **synthesize** information from multiple sources before acting

Skip it for straightforward tasks — don't reason about what you can just do.

## File Operations

### Best Practices

- **Read Before Editing**: Always verify file contents before overwriting or editing.
- **Multi-File Edits**: For changes spanning >3 files, outline a plan first or delegate to a worker.
- **File Formats**:
  - **HTML/Web Pages**: Use `ax web visit` (renders JS). Fall back to `ax web fetch` if needed.
  - **Binary Files**: Use `ax web fetch`.
  - **PDFs**: Convert to Markdown using `markitdown`, then read.
  - **JSON/XML**: Use Python scripts to extract fields.
