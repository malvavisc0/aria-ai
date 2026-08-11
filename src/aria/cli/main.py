"""Main CLI entry point for the Aria application.

This module defines the root CLI application and registers sub-commands
for human-facing system management of the Aria AI assistant.

Agent-facing commands (web, memory, knowledge, dev, worker, processes, check)
are available through the ``ax`` CLI instead.

Sub-commands:
    config: Configuration display (show, paths, database, api, optimize)
    users: User management (list, add, reset, edit, delete)
    models: Model management (download, list, memory)
    vllm: vLLM inference engine management (install, status, info)
    lightpanda: Lightpanda browser binary management (download, status)
    server: Webserver management (run, start, stop, status)
    system: Hardware inspection and process management
    tools: Tool state maintenance (cleanup-sessions)

Example:
    ```bash
    # Show help
    aria --help

    # Start the web server
    aria server run

    # Manage users
    aria users list
    ```
"""

import typer
from loguru import logger
from rich.console import Console
from rich.panel import Panel

from aria.cli import (
    config,
    lightpanda,
    models,
    server,
    system,
    users,
)
from aria.cli import (
    docling as docling_cli,
)
from aria.cli import (
    tools as tools_cli,
)
from aria.cli import vllm as vllm_cli
from aria.config import DEBUG

app = typer.Typer(
    name="aria",
    help=(
        "Aria — local AI assistant management CLI\n\n"
        "Human-facing commands for server, user, model, and system management.\n"
        "Agent-facing commands (web, memory, knowledge, dev, worker, processes, check) "
        "are available via the ``ax`` CLI."
    ),
    rich_markup_mode="rich",
    add_completion=False,
)
app.add_typer(users.app, name="users")
app.add_typer(vllm_cli.app, name="vllm")
app.add_typer(docling_cli.app, name="docling")
app.add_typer(lightpanda.app, name="lightpanda")
app.add_typer(models.app, name="models")
app.add_typer(config.app, name="config")
app.add_typer(server.app, name="server")
app.add_typer(system.app, name="system")
app.add_typer(tools_cli.app, name="tools")

console = Console()


def _configure_logging():
    # Rich handles CLI output formatting; set root level via DEBUG flag.
    import logging

    logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO)

    # Keep CLI entry points clean: Loguru logs go to files, not stdout/stderr.
    logger.remove()

    # Always silence noisy low-level loggers — never useful in CLI output.
    for _name in (
        "httpcore",
        "httpx",
        "huggingface_hub",
        "urllib3",
        "filelock",
    ):
        logging.getLogger(_name).setLevel(logging.WARNING)


def _print_banner():
    """Print the Aria banner with version info."""
    from aria import __version__

    console.print()
    console.print(
        Panel(
            f"[bold]ARIA CLI[/bold]\n[dim]Management CLI • v{__version__}[/dim]",
            border_style="cyan",
            expand=False,
            padding=(0, 2),
        )
    )
    console.print()
    console.print("[dim]For agent commands, use: [bold]ax[/bold][/dim]")
    console.print()


# Command groups for display
COMMAND_GROUPS = [
    {
        "title": "Setup",
        "commands": [
            ("config", "Show settings, paths, and keys"),
            ("users", "Manage user accounts"),
        ],
    },
    {
        "title": "Infrastructure",
        "commands": [
            ("models", "Download and manage models"),
            ("vllm", "Install and manage vLLM"),
            ("docling", "Install and manage Granite-Docling worker"),
            ("lightpanda", "Download and manage Lightpanda browser"),
            ("server", "Start or stop the web UI"),
            ("system", "Inspect hardware and GPU"),
        ],
    },
]


def _get_prog_name() -> str:
    """Return the CLI program name based on how it was invoked."""
    import sys
    from pathlib import Path

    return Path(sys.argv[0]).stem if sys.argv else "aria"


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Aria - AI Assistant Management CLI.

    Display banner and help when called without a command.
    """
    _configure_logging()
    if ctx.invoked_subcommand is None:
        _print_banner()
        prog = _get_prog_name()

        for group in COMMAND_GROUPS:
            console.print(f"[bold]{group['title']}[/bold]")
            for cmd, desc in group["commands"]:
                padded = f"{prog} {cmd}".ljust(18)
                console.print(f"   [cyan]{padded}[/cyan]{desc}")
            console.print()

        console.print(f"[dim]Run '{prog} <command> --help' for details.[/dim]")
