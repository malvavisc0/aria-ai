"""User management commands for the Aria CLI.

This module provides commands to manage users in the Aria database,
including listing, creating, and modifying user accounts.

Commands:
    list: Display all users in a formatted table
    add: Create a new user with email and password
    reset: Reset a user's password
    edit: Modify user metadata and role
    delete: Delete a user and all associated data

Example:
    ```bash
    # List all users
    aria users list

    # Add a new user
    aria users add --identifier user@example.com --role admin

    # Reset password
    aria users reset --identifier user@example.com

    # Edit user role
    aria users edit --identifier user@example.com --role admin

    # Delete a user
    aria users delete --identifier user@example.com
    ```
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from aria.cli import get_db_session
from aria.db.auth import hash_password
from aria.db.models import User

app = typer.Typer(
    name="users",
    help="User management commands for the Aria application.",
)


console = Console()
error_console = Console(stderr=True, style="bold red")


@app.command("list")
def list_users():
    """List all users in the database.

    Displays a formatted table with user information including:
    - User ID (UUID)
    - Identifier (email)
    - Role (from metadata)
    - Creation timestamp

    Shows total count of users at the bottom of the table.

    Example:
        ```bash
        aria users list
        ```
    """
    with get_db_session() as session:
        users = session.execute(select(User)).scalars().all()

        if not users:
            console.print("[yellow]No users found in database.[/yellow]")
            return

        console.print(f"[bold]Users[/bold] ({len(users)} total)\n")

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("ID", style="dim", width=36)
        table.add_column("Identifier", style="green")
        table.add_column("Role", style="yellow")
        table.add_column("Created At", style="dim")

        for user in users:
            metadata = json.loads(user.metadata_)
            role = metadata.get("role", "unknown")
            table.add_row(
                str(user.id),
                str(user.identifier),
                role,
                str(user.createdAt or ""),
            )

        console.print(table)


@app.command("add")
def add_user(
    identifier: Annotated[
        str,
        typer.Option(prompt="User identifier (email)", help="User email address"),
    ],
    name: Annotated[str, typer.Option(help="User name)")],
    role: Annotated[str, typer.Option(help="User role (user, admin, etc.)")] = "user",
):
    """Create a new user account.

    Creates a new user with the specified email and role. The password
    will be prompted securely (hidden input with confirmation).

    Args:
        identifier: User email address (used for login)
        name: Display name for the user
        role: User role for access control (default: "user")

    Example:
        ```bash
        # Create admin user
        aria users add --identifier admin@example.com --name "Admin" --role admin

        # Create regular user (default role)
        aria users add --identifier user@example.com --name "User"
        ```
    """
    with get_db_session() as session:
        existing = session.execute(
            select(User).where(User.identifier == identifier)
        ).scalar_one_or_none()

        if existing:
            error_console.print(f"[red]✗[/red] User '{identifier}' already exists")
            raise typer.Exit(1)

        password = typer.prompt(
            text="Password",
            confirmation_prompt=True,
            type=str,
            hide_input=True,
        )

        user = User(
            id=str(uuid.uuid4()),
            display_name=name,
            identifier=identifier,
            metadata_=json.dumps(
                {
                    "role": role,
                    "created_by": "cli",
                }
            ),
            password=hash_password(password),
            createdAt=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

        session.add(user)

        console.print(
            f"[green]✓[/green] User '[cyan]{identifier}[/cyan]' created (role: {role})"
        )


@app.command("reset")
def reset_password(
    identifier: Annotated[
        str,
        typer.Option(prompt="User identifier (email)", help="User email address"),
    ],
):
    """Reset a user's password.

    Updates the password for an existing user. The password is prompted
    securely (with confirmation) and the metadata is updated with a
    timestamp for audit trail.

    Args:
        identifier: User email address

    Example:
        ```bash
        aria users reset --identifier user@example.com
        ```
    """
    password = typer.prompt(
        text="New password",
        confirmation_prompt=True,
        hide_input=True,
    )

    with get_db_session() as session:
        user = session.execute(
            select(User).where(User.identifier == identifier)
        ).scalar_one_or_none()

        if not user:
            error_console.print(f"[red]✗[/red] User '{identifier}' not found")
            raise typer.Exit(1)

        user.password = hash_password(password)

        metadata = json.loads(user.metadata_)
        metadata["password_updated_at"] = datetime.now().isoformat()
        user.metadata_ = json.dumps(metadata)

        console.print(
            f"[green]✓[/green] Password reset for '[cyan]{identifier}[/cyan]'"
        )


@app.command("edit")
def update_user(
    identifier: Annotated[
        str,
        typer.Option(prompt="User identifier (email)", help="User email address"),
    ],
    role: Annotated[str | None, typer.Option(help="New role for the user")] = None,
    metadata_json: Annotated[
        str | None, typer.Option(help="JSON string of metadata to merge")
    ] = None,
):
    """Modify user metadata and role.

    Updates user metadata by merging the provided values. At least one
    of --role or --metadata-json must be provided.

    Args:
        identifier: User email address
        role: New role to assign (optional)
        metadata_json: JSON object to merge into existing metadata (optional)

    Example:
        ```bash
        # Change user role
        aria users edit --identifier user@example.com --role admin

        # Update metadata
        aria users edit --identifier user@example.com --metadata-json '{"department": "engineering"}'

        # Update both
        aria users edit --identifier user@example.com --role admin --metadata-json '{"department": "engineering"}'
        ```
    """
    if not role and not metadata_json:
        error_console.print(
            "[red]✗[/red] Provide at least one of --role or --metadata-json"
        )
        raise typer.Exit(1)

    with get_db_session() as session:
        user = session.execute(
            select(User).where(User.identifier == identifier)
        ).scalar_one_or_none()

        if not user:
            error_console.print(f"[red]✗[/red] User '{identifier}' not found")
            raise typer.Exit(1)

        metadata = json.loads(user.metadata_)

        if role:
            metadata["role"] = role

        if metadata_json:
            try:
                new_metadata = json.loads(metadata_json)
                metadata.update(new_metadata)
            except json.JSONDecodeError as e:
                error_console.print(f"[red]✗[/red] Invalid JSON: {e}")
                raise typer.Exit(1)

        metadata["updated_at"] = datetime.now().isoformat()
        user.metadata_ = json.dumps(metadata)

        console.print(f"[green]✓[/green] User '[cyan]{identifier}[/cyan]' updated")


@app.command("delete")
def delete_user(
    identifier: Annotated[str, typer.Option(help="User identifier (email)")],
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Delete a user and all associated data.

    Deletes the user and cascades to:
    - All threads owned by the user
    - All steps, elements, feedbacks in those threads

    Args:
        identifier: User email address
        yes: Skip confirmation prompt

    Example:
        ```bash
        # Delete with interactive confirmation
        aria users delete --identifier user@example.com

        # Delete without confirmation
        aria users delete --identifier user@example.com --yes
        ```
    """
    with get_db_session() as session:
        user = session.execute(
            select(User).where(User.identifier == identifier)
        ).scalar_one_or_none()

        if not user:
            error_console.print(f"[red]✗[/red] User '{identifier}' not found")
            raise typer.Exit(1)

        thread_count = len(user.threads)

        if not yes:
            console.print(
                f"[yellow]Warning:[/yellow] This will delete user '[cyan]{identifier}[/cyan]' "
                f"and {thread_count} thread(s) with all associated data."
            )
            typer.confirm("Proceed?", abort=True)

        session.delete(user)

        console.print(
            f"[green]✓[/green] User '[cyan]{identifier}[/cyan]' deleted ({thread_count} threads removed)"
        )


@app.command("clean")
def clean_user_chats(
    identifier: Annotated[str, typer.Option(help="User identifier (email)")],
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Delete all chat threads for a user.

    Removes all threads (and their steps, elements, and feedbacks) owned
    by the user. The user account itself is preserved.

    Args:
        identifier: User email address
        yes: Skip confirmation prompt

    Example:
        ```bash
        # Clean with interactive confirmation
        aria users clean --identifier user@example.com

        # Clean without confirmation
        aria users clean --identifier user@example.com --yes
        ```
    """
    with get_db_session() as session:
        user = session.execute(
            select(User).where(User.identifier == identifier)
        ).scalar_one_or_none()

        if not user:
            error_console.print(f"[red]✗[/red] User '{identifier}' not found")
            raise typer.Exit(1)

        thread_count = len(user.threads)

        if thread_count == 0:
            console.print(
                f"[yellow]No threads found for user '[cyan]{identifier}[/cyan]'.[/yellow]"
            )
            return

        if not yes:
            console.print(
                f"[yellow]Warning:[/yellow] This will delete {thread_count} thread(s) "
                f"for user '[cyan]{identifier}[/cyan]' with all associated data."
            )
            typer.confirm("Proceed?", abort=True)

        for thread in list(user.threads):
            session.delete(thread)

        console.print(
            f"[green]✓[/green] Deleted {thread_count} thread(s) for user '[cyan]{identifier}[/cyan]'"
        )
