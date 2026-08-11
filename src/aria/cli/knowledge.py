"""Knowledge hub CLI commands.

Wraps the documents knowledge hub (mini-RAG) as CLI sub-commands.
"""

import typer

app = typer.Typer(
    help="Knowledge hub — index and query user documents (mini-RAG).",
)


@app.command("reindex")
def reindex_cmd(
    force: bool = typer.Option(
        False, "--force", help="Full rebuild (drop collection + clear state)."
    ),
):
    """Re-index the documents directory."""
    import asyncio

    from aria.tools.knowledge.functions import knowledge_reindex

    typer.echo(
        asyncio.run(knowledge_reindex(reason="CLI knowledge reindex", force=force))
    )


@app.command("status")
def status_cmd():
    """Show knowledge hub index status."""
    import asyncio

    from aria.tools.knowledge.functions import knowledge_status

    typer.echo(asyncio.run(knowledge_status(reason="CLI knowledge status")))
