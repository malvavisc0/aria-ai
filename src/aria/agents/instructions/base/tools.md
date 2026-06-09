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

## File Operations

### Best Practices

- **Read Before Editing**: Always verify file contents before overwriting or editing.
- **Multi-File Edits**: For changes spanning >3 files, outline the plan first or delegate to a worker.
- **File Formats**:
  - **HTML/Web Pages**: Use `ax web open` (renders JS). Fall back to `ax web fetch` if needed.
  - **Binary Files**: Use `ax web fetch`.
  - **PDFs**: Convert to Markdown using `markitdown`, then read.
  - **JSON/XML**: Use Python scripts to extract fields.
