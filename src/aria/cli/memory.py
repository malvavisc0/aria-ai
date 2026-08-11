"""Memory CLI commands.

Wraps the persistent key-value memory store as CLI sub-commands
that output JSON.
"""

import typer

app = typer.Typer(
    help="Persistent key-value memory — store and recall facts across sessions.",
)


@app.command("store")
def store_cmd(
    key: str = typer.Argument(..., help="Unique key for the entry"),
    value: str = typer.Argument(..., help="Value to store"),
    tags: list[str] | None = typer.Option(
        None, "--tags", "-t", help="Tags for categorization"
    ),
):
    """Store a new memory entry."""
    from aria.tools.memory.functions import memory

    result = memory(
        reason="CLI memory store",
        action="store",
        key=key,
        value=value,
        tags=tags,
    )
    typer.echo(result)


@app.command("recall")
def recall_cmd(
    key: str = typer.Argument(..., help="Key to retrieve"),
):
    """Retrieve a stored fact by key."""
    from aria.tools.memory.functions import memory

    result = memory(
        reason="CLI memory recall",
        action="recall",
        key=key,
    )
    typer.echo(result)


@app.command("search")
def search_cmd(
    query: str = typer.Argument(..., help="Search query"),
    max_results: int = typer.Option(10, "--max-results", "-n", help="Maximum results"),
):
    """Search stored memory entries."""
    from aria.tools.memory.functions import memory

    result = memory(
        reason="CLI memory search",
        action="search",
        query=query,
        max_results=max_results,
    )
    typer.echo(result)


@app.command("list")
def list_cmd(
    tags: list[str] | None = typer.Option(None, "--tags", "-t", help="Filter by tags"),
    max_results: int = typer.Option(10, "--max-results", "-n", help="Maximum results"),
):
    """List all stored memory entries."""
    from aria.tools.memory.functions import memory

    result = memory(
        reason="CLI memory list",
        action="list",
        tags=tags,
        max_results=max_results,
    )
    typer.echo(result)


@app.command("update")
def update_cmd(
    entry_id: str = typer.Argument(..., help="UUID of entry to update"),
    value: str = typer.Argument(..., help="New value"),
):
    """Update an existing memory entry."""
    from aria.tools.memory.functions import memory

    result = memory(
        reason="CLI memory update",
        action="update",
        entry_id=entry_id,
        value=value,
    )
    typer.echo(result)


@app.command("delete")
def delete_cmd(
    entry_id: str = typer.Argument(..., help="UUID of entry to delete"),
):
    """Remove a memory entry."""
    from aria.tools.memory.functions import memory

    result = memory(
        reason="CLI memory delete",
        action="delete",
        entry_id=entry_id,
    )
    typer.echo(result)
