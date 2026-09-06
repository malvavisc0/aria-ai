"""MCP server management CLI.

Chainlit 2.12 removed user-provided stdio MCP servers: the only way to
offer a stdio (or pre-approved remote) server in the web UI is a
``[[features.mcp.servers]]`` entry in ``$ARIA_HOME/.chainlit/config.toml``.
These commands are the user-facing interface to that file.

Writes append/remove ``[[features.mcp.servers]]`` blocks at the end of the
file (TOML allows a top-level array-of-tables anywhere), so existing
formatting and comments are never rewritten. Reads use ``tomllib``.
"""

from __future__ import annotations

import shlex
import tomllib
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from aria.config.folders import Data

app = typer.Typer(help="Manage MCP servers available in the web UI.")

console = Console()

_TYPES = ("stdio", "sse", "streamable-http")


def _config_path() -> Path:
    return Data.path / ".chainlit" / "config.toml"


def _toml_string(value: str) -> str:
    """Quote *value* as a TOML basic string."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render_server_block(
    name: str,
    server_type: str,
    command: str | None,
    url: str | None,
    env: dict[str, str] | None,
) -> str:
    """Render one ``[[features.mcp.servers]]`` block."""
    lines = [
        "[[features.mcp.servers]]",
        f"name = {_toml_string(name)}",
        f"type = {_toml_string(server_type)}",
    ]
    if server_type == "stdio":
        if command is None:
            raise ValueError("stdio server requires a command")
        lines.append(f"command = {_toml_string(command)}")
        if env:
            pairs = ", ".join(f"{k} = {_toml_string(v)}" for k, v in env.items())
            lines.append(f"env = {{ {pairs} }}")
    else:
        if url is None:
            raise ValueError(f"{server_type} server requires a url")
        lines.append(f"url = {_toml_string(url)}")
    block = "\n".join(lines) + "\n"
    tomllib.loads(block)  # fail fast on a rendering bug instead of corrupting the file
    return block


def _load_servers(path: Path) -> list[dict]:
    """Return the configured MCP servers ([] when the file is absent)."""
    if not path.is_file():
        return []
    data = tomllib.loads(path.read_text())
    servers = data.get("features", {}).get("mcp", {}).get("servers", [])
    return [s for s in servers if isinstance(s, dict)]


def _remove_server_block(content: str, name: str) -> str | None:
    """Remove the ``[[features.mcp.servers]]`` block whose name matches.

    A block runs from its header line to the next section header (a line
    starting with ``[`` at column 0) or EOF. Matching is case-insensitive,
    mirroring Chainlit's name collision rule. Returns None when no block
    matches.
    """
    lines = content.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    removed = False
    while i < len(lines):
        line = lines[i]
        if line.strip() == "[[features.mcp.servers]]":
            block = [line]
            i += 1
            while i < len(lines) and not lines[i].startswith("["):
                block.append(lines[i])
                i += 1
            if _block_name(block) == name.strip().casefold():
                removed = True
                continue  # drop the block
            out.extend(block)
        else:
            out.append(line)
            i += 1
    return "".join(out) if removed else None


def _block_name(block: list[str]) -> str | None:
    """Return the normalised ``name`` of a server block, or None.

    Only bare ``name = ...`` key lines are considered (a leading ``#`` or
    a longer key like ``nameserver`` must not match).
    """
    for line in block:
        key, sep, value = line.partition("=")
        if not sep or key.strip() != "name":
            continue
        try:
            parsed = tomllib.loads(f"value = {value.strip()}")
        except tomllib.TOMLDecodeError:
            return None
        name = parsed.get("value")
        return name.strip().casefold() if isinstance(name, str) else None
    return None


def _parse_env(pairs: list[str]) -> dict[str, str]:
    """Parse repeated ``KEY=VALUE`` options, failing fast on bad input."""
    env: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise typer.BadParameter(f"--env expects KEY=VALUE, got {pair!r}")
        env[key.strip()] = value
    return env


def _check_stdio(command: str | None) -> None:
    if not command:
        raise typer.BadParameter("--type stdio requires --command.")
    if not shlex.split(command):
        raise typer.BadParameter("--command is empty.")


def _check_remote(url: str | None, server_type: str, env: list[str]) -> None:
    if not url:
        raise typer.BadParameter(f"--type {server_type} requires --url.")
    if env:
        raise typer.BadParameter("--env only applies to stdio servers.")


def _resolve_add_args(
    command: str | None,
    url: str | None,
    server_type: str | None,
    env: list[str],
) -> str:
    """Validate the add options and return the resolved server type."""
    if bool(command) == bool(url):
        raise typer.BadParameter(
            "Pass exactly one of --command (stdio) or --url (sse/streamable-http)."
        )

    resolved_type = server_type or ("stdio" if command else "streamable-http")
    if resolved_type not in _TYPES:
        raise typer.BadParameter(f"--type must be one of: {', '.join(_TYPES)}")

    if resolved_type == "stdio":
        _check_stdio(command)
    else:
        _check_remote(url, resolved_type, env)
    return resolved_type


@app.command("add")
def add_cmd(
    name: str = typer.Argument(..., help="Server name shown in the web UI."),
    command: str | None = typer.Option(
        None, "--command", "-c", help="stdio command, e.g. 'uvx mcp-server-fs ~'"
    ),
    url: str | None = typer.Option(
        None, "--url", "-u", help="Server URL for sse / streamable-http."
    ),
    server_type: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="stdio | sse | streamable-http (inferred from --command/--url).",
    ),
    env: list[str] = typer.Option(
        [], "--env", "-e", help="stdio env var, KEY=VALUE (repeatable)."
    ),
) -> None:
    """Add an MCP server to the web UI's server list."""
    resolved_type = _resolve_add_args(command, url, server_type, env)

    path = _config_path()
    if not path.is_file():
        console.print(f"[red]Config not found:[/red] {path}")
        console.print("[dim]Run `aria init` first.[/dim]")
        raise typer.Exit(1)

    try:
        existing = _load_servers(path)
    except tomllib.TOMLDecodeError as exc:
        console.print(f"[red]Config is not valid TOML:[/red] {path}\n{exc}")
        raise typer.Exit(1) from exc
    if any(
        s.get("name", "").strip().casefold() == name.strip().casefold()
        for s in existing
    ):
        console.print(f"[red]Server {name!r} already exists.[/red] Remove it first.")
        raise typer.Exit(1)

    block = _render_server_block(
        name, resolved_type, command, url, _parse_env(env) or None
    )
    with path.open("a") as f:
        f.write("\n" + block)

    target = command if resolved_type == "stdio" else url
    console.print(f"[green]Added[/green] {name!r} ({resolved_type}: {target})")
    console.print("[dim]Restart the server (`aria server start`) to apply.[/dim]")


@app.command("list")
def list_cmd() -> None:
    """List configured MCP servers."""
    path = _config_path()
    try:
        servers = _load_servers(path)
    except tomllib.TOMLDecodeError as exc:
        console.print(f"[red]Config is not valid TOML:[/red] {path}\n{exc}")
        raise typer.Exit(1) from exc
    if not servers:
        console.print("No MCP servers configured.")
        console.print(
            "[dim]Add one with: aria mcp add <name> --command 'uvx <package>'[/dim]"
        )
        return
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Name", style="cyan")
    table.add_column("Type")
    table.add_column("Target")
    for s in servers:
        table.add_row(
            str(s.get("name", "")),
            str(s.get("type", "")),
            str(s.get("command") or s.get("url") or ""),
        )
    console.print(table)


@app.command("remove")
def remove_cmd(
    name: str = typer.Argument(..., help="Name of the server to remove."),
) -> None:
    """Remove an MCP server from the web UI's server list."""
    path = _config_path()
    if not path.is_file():
        console.print(f"[red]Config not found:[/red] {path}")
        raise typer.Exit(1)

    content = path.read_text()
    updated = _remove_server_block(content, name)
    if updated is None:
        console.print(f"[red]No server named {name!r}.[/red]")
        raise typer.Exit(1)
    path.write_text(updated)
    console.print(f"[green]Removed[/green] {name!r}")
    console.print("[dim]Restart the server (`aria server start`) to apply.[/dim]")
