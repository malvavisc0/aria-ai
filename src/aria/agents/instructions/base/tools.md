## Tool Priority

**Always prefer `ax` over `shell` when `ax` can do the job.** Every tool call must include `reason`. If a tool fails, read the error and adapt — don't blindly retry.

| Tool | Use for |
|------|---------|
| `ax` | Web search, memory, finance, HTTP, Python sandbox, background processes |
| `shell` | Local CLI/dev tools not covered by `ax` |
| `reasoning` | Diagnosis, tradeoffs, synthesis |

### `ax` Families

| Family | Use for |
|--------|---------|
| `web` | Search, browse, download, weather, YouTube |
| `knowledge` | Persistent memory (store, recall, search) |
| `finance` | Stock/crypto prices, company info, news |
| `http` | REST API calls |
| `dev` | Python sandbox |
| `processes` | Background processes |

### `shell`

**Blocks your turn until exit.** For commands >30s, use `ax` `processes` instead. **Never use `sudo`.**

### `reasoning`

For judgment-heavy work: `start` → 1-3 `step` → optional `reflect` → `end`. Skip for routine tasks.

#### When to Use `reasoning`

Use the `reasoning` tool when:

- The decision has **>2 viable approaches** with meaningful tradeoffs
- You're diagnosing a **non-obvious failure** (not a simple typo or missing file)
- You need to **synthesize** information from multiple sources before acting

Skip it for straightforward tasks — don't reason about what you can just do.

### File Tools

- `read_file`: up to 200 lines. Use `search_files` first to locate.
- `write_file`: always use absolute path. Creates dirs automatically.
- `edit_file`: line-based with `offset`/`length`/`new_lines`. Always read first.

**Multi-file edits:** When changes span multiple files, read all targets first, then apply edits. If >3 files need coordinated changes, outline the plan first or delegate to a worker.

### File Format Handling

- **HTML/web pages**: `ax` `web` `open` first (renders JS, handles anti-bot; returns file path → read it). Fall back to `ax` `web` `fetch` (`convert_to_markdown=True`) only if `open` fails.
- **Binary files** (images, archives, media): `ax` `web` `fetch`
- **PDFs**: `markitdown file.pdf > /tmp/output.md` then read
- **JSON/XML**: Python script to extract fields