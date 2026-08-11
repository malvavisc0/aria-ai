"""AX CLI — Agent Experience command-line interface.

A stripped-down Typer app exposing only agent-facing commands.
Human management commands (users, server, config, system, models, vllm,
lightpanda) are only available through the full ``aria`` CLI.
"""

import typer
from loguru import logger
from rich.console import Console
from rich.panel import Panel

from aria.cli import check as check_cli
from aria.cli import dev as dev_cli
from aria.cli import knowledge as knowledge_cli
from aria.cli import memory as memory_cli
from aria.cli import processes as processes_cli
from aria.cli import web as web_cli
from aria.cli import worker as worker_cli
from aria.config import DEBUG

app = typer.Typer(
    name="ax",
    help=(
        "AX — Agent Experience CLI\n\n"
        "Streamlined interface for agent-facing operations: web research, "
        "memory management, code execution, worker agents, and "
        "background processes. For full system management use ``aria``."
    ),
    rich_markup_mode="rich",
    add_completion=False,
)

app.add_typer(check_cli.app, name="check")
app.add_typer(processes_cli.app, name="processes")
app.add_typer(memory_cli.app, name="memory")
app.add_typer(knowledge_cli.app, name="knowledge")
app.add_typer(web_cli.app, name="web")
app.add_typer(dev_cli.app, name="dev")
app.add_typer(worker_cli.app, name="worker")

console = Console()


def _configure_logging():
    """Silence noisy loggers for clean CLI output."""
    import logging

    logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO)

    # Keep CLI entry points clean: Loguru logs go to files, not stdout/stderr.
    logger.remove()

    for _name in (
        "httpcore",
        "httpx",
        "huggingface_hub",
        "urllib3",
        "filelock",
    ):
        logging.getLogger(_name).setLevel(logging.WARNING)


def _print_banner():
    """Print the AX banner with version info."""
    from aria import __version__

    console.print()
    console.print(
        Panel(
            f"[bold]AX CLI[/bold]\n[dim]Agent Experience CLI • v{__version__}[/dim]",
            border_style="magenta",
            expand=False,
            padding=(0, 2),
        )
    )
    console.print()
    console.print("[dim]For system management, use: [bold]aria[/bold][/dim]")
    console.print()


# Command groups for display
COMMAND_GROUPS = [
    {
        "title": "Research",
        "commands": [
            ("web", "Search, fetch pages, get weather"),
        ],
    },
    {
        "title": "Agents",
        "commands": [
            ("worker", "Spawn background agents"),
            ("memory", "Store and recall facts"),
            ("knowledge", "Document knowledge hub"),
            ("dev", "Run Python code"),
        ],
    },
    {
        "title": "System",
        "commands": [
            ("processes", "Manage background processes"),
            ("check", "Preflight checks and agent instructions"),
        ],
    },
]


def _get_prog_name() -> str:
    """Return the CLI program name based on how it was invoked."""
    import sys
    from pathlib import Path

    return Path(sys.argv[0]).stem if sys.argv else "ax"


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """AX — Agent Experience CLI.

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
