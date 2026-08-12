"""Storage management CLI commands.

Reclaims element files on disk that have no matching ``elements`` row.
These "orphans" accumulate when a thread or element is deleted while the
``objectKey`` column is NULL (the C1 bug fixed in
[`layer.py`](aria/db/layer.py)). ``delete_thread`` / ``delete_element`` key
file cleanup off ``objectKey``, so a NULL value skips the file and leaves it
stranded on disk after the row is gone.
"""

from __future__ import annotations

import typer
from rich.console import Console
from sqlalchemy import create_engine, text

from aria.config.database import SQLite
from aria.config.folders import Storage

app = typer.Typer(
    help="Storage — reclaim orphaned element files on disk.",
)

console = Console()
error_console = Console(stderr=True, style="bold red")


def _iter_orphans() -> list[tuple[str, int]]:
    """Return ``(relative_path, size_bytes)`` for files with no element row.

    The storage layout is ``<user_id>/<element_id>/<filename>``; the second
    path segment is the element id, which should match ``elements.id``. A
    file whose element id has no row is an orphan.
    """
    if not Storage.path.exists():
        return []

    engine = create_engine(SQLite.db_url)
    orphans: list[tuple[str, int]] = []
    try:
        with engine.connect() as conn:
            for path in Storage.path.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(Storage.path).as_posix()
                parts = rel.split("/")
                if len(parts) < 2:
                    continue
                element_id = parts[1]
                exists = conn.execute(
                    text("SELECT 1 FROM elements WHERE id = :id"),
                    {"id": element_id},
                ).first()
                if exists is None:
                    orphans.append((rel, path.stat().st_size))
    finally:
        engine.dispose()

    return orphans


def sweep_orphans() -> tuple[int, int]:
    """Delete orphaned files; return ``(deleted_count, total_bytes)``.

    Shared by the ``aria storage sweep`` CLI command and the web startup
    hook so the reclaim logic lives in one place. Safe to call when the
    storage directory or database is empty (returns ``(0, 0)``).
    """
    orphans = _iter_orphans()
    if not orphans:
        return 0, 0

    deleted = 0
    for rel, _ in orphans:
        full = Storage.path / rel
        try:
            full.unlink()
            deleted += 1
        except OSError:
            pass
    return deleted, sum(size for _, size in orphans)


def _format_size(n: int) -> str:
    """Render a byte count as a human-readable size string."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


@app.command("sweep")
def sweep_cmd(
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Delete orphans without prompting."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="List orphans without deleting."
    ),
):
    """Delete orphaned element files (no matching ``elements`` row).

    A dry run (default when not ``--yes``) lists what would be removed.
    Pass ``--yes`` to delete, or ``--dry-run`` to always list without
    deleting.
    """
    orphans = _iter_orphans()

    if not orphans:
        console.print("[green]✓[/green] No orphaned files found.")
        return

    total = sum(size for _, size in orphans)
    console.print(
        f"Found [yellow]{len(orphans)}[/yellow] orphaned file(s) "
        f"([yellow]{_format_size(total)}[/yellow]):"
    )
    for rel, size in orphans:
        console.print(f"  {rel}  ({_format_size(size)})")

    if dry_run:
        return

    if not yes:
        typer.confirm("Delete these files?", abort=True)

    deleted, reclaimed = sweep_orphans()

    console.print(
        f"[green]✓[/green] Deleted {deleted} of {len(orphans)} orphaned file(s) "
        f"({_format_size(reclaimed)} reclaimed)."
    )
