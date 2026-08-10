"""Tool management commands for the Aria CLI.

Provides maintenance commands for tool-persisted state, currently
focused on cleaning up inactive reasoning sessions.

Commands:
    cleanup-sessions: Permanently delete inactive reasoning sessions
                     older than a given age.

Example:
    ```bash
    # Delete inactive reasoning sessions older than 30 days (default)
    aria tools cleanup-sessions

    # Delete sessions older than 7 days
    aria tools cleanup-sessions --days 7

    # Limit cleanup to a specific agent
    aria tools cleanup-sessions --agent-id aria
    ```
"""

import typer
from rich.console import Console

from aria.tools.reasoning.database import ReasoningDatabase

app = typer.Typer(
    name="tools",
    help="Tool state maintenance commands.",
)

console = Console()
error_console = Console(stderr=True, style="bold red")


@app.command("cleanup-sessions")
def cleanup_sessions(
    days: int = typer.Option(
        30,
        "--days",
        "-d",
        help="Permanently delete inactive sessions older than this many days.",
    ),
    agent_id: str | None = typer.Option(
        None,
        "--agent-id",
        "-a",
        help="Limit cleanup to a specific agent (default: all agents).",
    ),
) -> None:
    """Permanently delete inactive reasoning sessions older than --days.

    Sessions are only deleted when ``is_active=False`` AND
    ``updated_at`` is older than the cutoff. Active sessions are
    never deleted.
    """
    if days < 1:
        error_console.print("[red]✗[/red] --days must be >= 1")
        raise typer.Exit(1)

    db = ReasoningDatabase()
    count = db.cleanup_old_sessions(days=days, agent_id=agent_id)

    scope = f"for agent '{agent_id}'" if agent_id else "across all agents"
    console.print(
        f"[green]✓[/green] Cleaned up {count} inactive session(s) older than "
        f"{days} day(s) {scope}"
    )
