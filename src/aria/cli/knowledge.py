"""Knowledge hub CLI commands.

Wraps the documents knowledge hub (mini-RAG) as CLI sub-commands.
"""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Knowledge hub (mini-RAG) — index status.")

console = Console()


def _extract_data(payload: str) -> dict | None:
    """Return the data dict from a success envelope, or None on any failure."""
    try:
        envelope = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if envelope.get("status") != "success":
        return None
    return envelope.get("data") or {}


def _docling_value(installed: bool) -> str:
    return (
        "[green]installed[/green]"
        if installed
        else "[red]NOT installed[/red] (Run: aria docling install)"
    )


def _render_status(payload: str) -> None:
    """Pretty-print the hub status; warn loudly if docling is missing."""
    data = _extract_data(payload)
    if data is None:
        typer.echo(payload)
        return
    if not data.get("enabled"):
        typer.echo("Knowledge hub: disabled (ARIA_KNOWLEDGE_ENABLED != 'true')")
        return
    last = data.get("last_index_at") or "never"
    skipped = data.get("skipped") or []
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Property", style="cyan")
    table.add_column("Value")
    table.add_row("Directory", data.get("dir", ""))
    table.add_row("Collection", data.get("collection", ""))
    table.add_row("Docling worker", _docling_value(bool(data.get("docling_installed"))))
    table.add_row("Indexed files", str(data.get("indexed_files", 0)))
    table.add_row("Last index", str(last))
    console.print(table)
    if skipped:
        console.print(f"\n[yellow]⚠ {len(skipped)} file(s) skipped:[/yellow]")
        for s in skipped:
            console.print(
                f"  • {s.get('path', '')}  [dim]({s.get('reason', '')})[/dim]"
            )


@app.command("status")
def status_cmd():
    """Show knowledge hub index status."""
    import asyncio

    from aria.tools.knowledge.functions import knowledge_status

    payload = asyncio.run(knowledge_status(reason="CLI knowledge status"))
    _render_status(payload)
