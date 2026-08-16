## Tool Priority

`ax` is the core interface — most capabilities in one structured, logged call (families are listed in its schema). **Prefer `ax` over `shell`; `shell` is the fallback** for venv binaries and CLI tools `ax` doesn't cover; it blocks the turn until exit.

**Family guidance:**

- `reasoning` — diagnosis, tradeoffs, synthesis when >2 approaches or sources are involved; skip for straightforward tasks.
- `memory` — persistent across conversations (preferences, conventions, learned facts); temporary data goes to `scratchpad`.
- `knowledge` — semantic retrieval over user documents; `status` reports index state, `reindex` rebuilds.
- `mcp` — external MCP tools, listed in the `[Connected MCP servers]` block; `mcp list` for details.
- `voice` — transcribe local audio files to text (CLI-free, in-process; whisper server runs with the web UI).
- `dev run` — prefer over `shell` for computation (parsing JSON/XML/CSV, calculations, transformations); not for CLI tools, file I/O, or long-running work.

## Resolution Order

1. Unsure of an `ax` family, command, or arguments? Use `ax(family="help", command="lookup", args={"topic": "<family>"})` before guessing.
2. `unknown_command`/`unknown_family`? Check `ax check extras` with a keyword; run a matching venv binary via `shell` (`--help` first if new this session).
3. No match anywhere? Fall back to a common shell utility (`curl`, `git`, `jq`, `sed`).
4. `check instructions` and `check preflight` are CLI-only — invoke via `shell`, never as `ax()` calls.
